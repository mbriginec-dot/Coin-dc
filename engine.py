"""
Рушій сканування: для кожного інструмента зі списку — тягне бари з потрібних
таймфреймів, будує рівні, рахує ATR, запускає всі застосовні стратегії,
уникає дублікатів через StateStore і надсилає повідомлення в Telegram.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Union

from bot.config import AppConfig
from bot.data.aggregator import DataAggregator
from bot.indicators.atr import full_atr_report
from bot.models import AssetClass, Bar, FormationAlert, Instrument, StrategyId, TradeSignal
from bot.notify.telegram import TelegramNotifier
from bot.risk.commissions import estimate_commission
from bot.session import minutes_since_session_open
from bot.state.store import StateStore
from bot.strategies import levels as lv
from bot.strategies.base import StrategyContext
from bot.strategies.s1_bounce import BounceStrategy
from bot.strategies.s2_breakout import BreakoutStrategy
from bot.strategies.s3_false_breakout import FalseBreakoutStrategy
from bot.strategies.s4_momentum import MomentumStrategy
from bot.strategies.s5_channel import ChannelStrategy
from bot.strategies.s6_staircase import StaircaseStrategy
from bot.strategies.s7_engulfing import EngulfingStrategy
from bot.strategies.s8_key_levels import KeyLevelsStrategy

log = logging.getLogger(__name__)

_STRATEGIES = [
    BounceStrategy(), BreakoutStrategy(), FalseBreakoutStrategy(), MomentumStrategy(),
    ChannelStrategy(), StaircaseStrategy(), EngulfingStrategy(), KeyLevelsStrategy(),
]
ALL_STRATEGIES = {s.id: s for s in _STRATEGIES}

WORKING_BAR_LOOKBACK = 250   # ~ кілька сесій 5-хв барів — достатньо для БСУ/БПУ, акумуляції, поглинання, сходинок
HOURLY_BAR_LOOKBACK = 120


class Engine:
    def __init__(self, config: AppConfig, data: DataAggregator, notifier: TelegramNotifier, state: StateStore):
        self.config = config
        self.data = data
        self.notifier = notifier
        self.state = state
        self._sp500_cache: Optional[Tuple[float, float, datetime]] = None

    def run_once(self) -> int:
        """Один прохід сканування всього watchlist. Повертає кількість надісланих повідомлень."""
        now = datetime.now(timezone.utc)
        sent = 0
        for instrument in self.config.instruments:
            try:
                sent += self._scan_instrument(instrument, now)
            except Exception:
                log.exception("Помилка сканування %s", instrument.symbol)
        return sent

    # -- допоміжні дані ------------------------------------------------------
    def _today_high_low(self, working_bars: List[Bar]) -> Tuple[float, float, List[Bar]]:
        if not working_bars:
            return 0.0, 0.0, []
        today = working_bars[-1].ts.date()
        todays = [b for b in working_bars if b.ts.date() == today]
        if not todays:
            todays = working_bars[-1:]
        return max(b.high for b in todays), min(b.low for b in todays), todays

    def _get_sp500_context(self, now: datetime) -> Tuple[Optional[float], Optional[float]]:
        """Закриття S&P500 попереднього дня + відкриття сьогодні (розділ 5.1 алгоритму,
        потрібно для Стратегії 4). Кешується на годину, щоб не робити зайвих запитів."""
        if self._sp500_cache and (now - self._sp500_cache[2]).total_seconds() < 3600:
            return self._sp500_cache[0], self._sp500_cache[1]
        try:
            sp500 = Instrument(
                symbol="^GSPC", display_name="S&P 500", asset_class=AssetClass.STOCK,
                provider="yfinance", point_value=0.01,
            )
            bars = self.data.get_bars(sp500, "1d", 3)
            if len(bars) >= 2:
                prev_close = bars[-2].close
                today_open = bars[-1].open
                self._sp500_cache = (prev_close, today_open, now)
                return prev_close, today_open
        except Exception as e:
            log.warning("Не вдалось отримати контекст S&P500: %s", e)
        return None, None

    def _get_prev_day_intraday(self, instrument: Instrument, all_working_bars: List[Bar]) -> List[Bar]:
        """Внутрішньоденні бари ПОПЕРЕДНЬОГО дня — для розрахунку POC (Стратегія 8)."""
        if not all_working_bars:
            return []
        today = all_working_bars[-1].ts.date()
        prev_bars = [b for b in all_working_bars if b.ts.date() < today]
        if not prev_bars:
            return []
        prev_day = prev_bars[-1].ts.date()
        return [b for b in prev_bars if b.ts.date() == prev_day]

    # -- основна логіка --------------------------------------------------------
    def _scan_instrument(self, instrument: Instrument, now: datetime) -> int:
        if not self.data.is_market_open(instrument):
            return 0

        cfg = self.config
        daily_bars_full = self.data.get_bars(instrument, "1d", cfg.scan.daily_atr_lookback_days + 10)
        working_bars = self.data.get_bars(instrument, "5m", WORKING_BAR_LOOKBACK)
        hourly_bars = self.data.get_bars(instrument, "1h", HOURLY_BAR_LOOKBACK)

        if len(daily_bars_full) < 2 or not working_bars:
            log.debug("Недостатньо даних для %s — пропуск цього циклу", instrument.symbol)
            return 0

        today_high, today_low, todays_wbars = self._today_high_low(working_bars)
        daily_history = daily_bars_full[:-1] if daily_bars_full[-1].ts.date() == working_bars[-1].ts.date() else daily_bars_full

        atr = full_atr_report(
            daily_history, today_high, today_low,
            lookback_days=cfg.scan.daily_atr_lookback_days,
            min_days=cfg.scan.daily_atr_min_days,
            anomaly_multiplier=cfg.scan.anomaly_range_multiplier,
        )

        levels = lv.build_levels(
            daily_history, timeframe="1d",
            lookback=cfg.scan.swing_lookback_bars,
            merge_tolerance_pct=cfg.scan.level_merge_tolerance_pct,
        )

        # --- Повний розрахунок сили рівня (розділ 4.3 алгоритму) ---
        # Раніше тут викликався score_strength(level) БЕЗ жодного з бонус-факторів,
        # тому сила рівня завжди виходила 0. Тепер рахуємо всі п'ять факторів:
        weekly_bars = lv.aggregate_to_weekly(daily_history)
        weekly_levels = lv.build_levels(
            weekly_bars, timeframe="1w",
            lookback=min(cfg.scan.swing_lookback_bars, max(1, len(weekly_bars) // 3)),
            merge_tolerance_pct=cfg.scan.level_merge_tolerance_pct,
        ) if len(weekly_bars) >= 6 else []

        channel_window = daily_history[-30:]
        channel_bounds = (
            [max(b.high for b in channel_window), min(b.low for b in channel_window)]
            if channel_window else None
        )

        for level in levels:
            level.strength = lv.score_strength(
                level,
                higher_tf_levels=weekly_levels,
                channel_bounds=channel_bounds,
                false_breakout_count=lv.count_false_breakout_history(daily_history, level),
                is_extremum=lv.is_built_on_extremum(level, daily_history),
                merge_tolerance_pct=cfg.scan.level_merge_tolerance_pct * 3,
            )

        global_trend = lv.trend_direction(daily_history, lookback=10)

        session_minutes = minutes_since_session_open(instrument.asset_class, now)
        today_bar = Bar(
            ts=now,
            open=todays_wbars[0].open if todays_wbars else working_bars[-1].open,
            high=today_high, low=today_low, close=working_bars[-1].close,
        )

        ctx = StrategyContext(
            instrument=instrument, now=now, daily_bars=daily_history, today_bar=today_bar,
            working_bars=working_bars, hourly_bars=hourly_bars, weekly_bars=weekly_bars,
            levels=levels, atr=atr, cfg=cfg, commission=0.0,
            session_open_minutes_ago=session_minutes, global_trend=global_trend,
        )

        enabled_ids = instrument.enabled_strategies or list(ALL_STRATEGIES.keys())
        events: List[Union[FormationAlert, TradeSignal]] = []

        for sid in enabled_ids:
            strat = ALL_STRATEGIES.get(sid)
            if strat is None:
                continue
            try:
                if sid == StrategyId.S4_MOMENTUM:
                    sp500_prev, sp500_open = self._get_sp500_context(now)
                    events.extend(strat.scan(ctx, sp500_prev_close=sp500_prev, sp500_today_open=sp500_open))
                elif sid == StrategyId.S8_KEY_LEVELS:
                    prev_day_intraday = self._get_prev_day_intraday(instrument, working_bars)
                    events.extend(strat.scan(ctx, prev_day_intraday_bars=prev_day_intraday))
                else:
                    events.extend(strat.scan(ctx))
            except Exception:
                log.exception("Помилка стратегії %s для %s", sid, instrument.symbol)

        current_price = working_bars[-1].close
        levels_by_price = {round(l.price, 6): l for l in levels}
        for event in events:
            if event.current_price is None:
                event.current_price = current_price
            if "level_notes" not in event.extra:
                matched = min(levels, key=lambda l: abs(l.price - event.level_price), default=None) if levels else None
                if matched is not None and abs(matched.price - event.level_price) / max(event.level_price, 1e-9) <= 0.01:
                    event.extra["level_notes"] = list(matched.notes)

        sent = 0
        for event in events:
            if self._dispatch(event, instrument, cfg):
                sent += 1
        return sent

    def _dispatch(self, event: Union[FormationAlert, TradeSignal], instrument: Instrument, cfg: AppConfig) -> bool:
        if isinstance(event, FormationAlert):
            if not self.state.should_send_formation(event, cooldown_minutes=30.0):
                return False
            ok = self.notifier.send_formation_alert(event)
            if ok:
                self.state.mark_formation_sent(event)
            return ok

        if isinstance(event, TradeSignal):
            # Комісія залежить від фактичного обсягу позиції (qty), відомого лише
            # після розрахунку в стратегії — донараховуємо тут і коригуємо R:R.
            notional = event.order.entry * event.order.qty
            commission = estimate_commission(instrument, event.order.qty, notional, cfg.commissions)
            if commission:
                old_risk = event.order.qty * event.delta_stop  # стратегії рахували з commission=0
                total_profit = event.rr_actual * old_risk
                new_risk = old_risk + commission
                event.rr_actual = (total_profit / new_risk) if new_risk > 0 else event.rr_actual
                event.risk_money = new_risk
                event.commission = commission

            if not self.state.should_send_signal(event, cooldown_minutes=240.0):
                return False
            ok = self.notifier.send_trade_signal(event)
            if ok:
                self.state.mark_signal_sent(event)
            return ok

        return False
