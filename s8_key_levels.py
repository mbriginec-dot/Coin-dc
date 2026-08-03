"""
Авторська стратегія — КЛЮЧОВІ РІВНІ ДНЯ (PDH · PDL · POC · 1H-High · 1H-Low).

На відміну від Стратегій 1-7, тут усі рівні визначаються ОДНОЗНАЧНО й
АВТОМАТИЧНО з цінових/об'ємних даних (розділ 1.2 "Авторської стратегії") —
це найбільш надійна для повної автоматизації з восьми стратегій.

До кожного з п'яти рівнів застосовується одна з трьох базових моделей
(Відбій/Пробій/Хибний пробій, розділ 6), тому цей модуль повторно використовує
bot/strategies/levels.py, patterns.py та bot/risk/calculator.py напряму.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Union

from bot.indicators.atr import is_atr_exhausted
from bot.models import Bar, Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import levels as lv
from bot.strategies import patterns as pt
from bot.strategies.base import Strategy, StrategyContext

ONE_HOUR_STRENGTH_MIN_TOUCHES = 1  # мінімум 1 чітке підтвердження (розділ 4.1 "Авторської стратегії")


def compute_poc(intraday_bars: List[Bar], bucket_pct: float = 0.0005) -> Optional[float]:
    """POC (Point of Control) — ціна з найбільшим сумарним обсягом за сесію (розділ 3 "Авторської стратегії")."""
    poc, _, _ = compute_poc_and_value_area(intraday_bars, bucket_pct)
    return poc


def compute_poc_and_value_area(
    intraday_bars: List[Bar], bucket_pct: float = 0.0005, value_area_pct: float = 0.70
) -> "tuple[Optional[float], Optional[float], Optional[float]]":
    """
    POC + Value Area (VAH/VAL) — розділ 3.1/3.4 "Авторської стратегії": VAH/VAL
    обмежують діапазон, у якому пройшло ≈70% обсягу дня, розширюючись від POC
    у той бік, де на кожному кроці більше обсягу (стандартний алгоритм Volume Profile).
    Повертає (POC, VAH, VAL).
    """
    if not intraday_bars:
        return None, None, None
    prices = [b.close for b in intraday_bars]
    lo, hi = min(prices), max(prices)
    if hi <= lo:
        return prices[0], prices[0], prices[0]
    bucket_size = max((hi - lo) * bucket_pct, 1e-9)
    buckets: Dict[int, float] = defaultdict(float)
    for b in intraday_bars:
        key = int(round((b.close - lo) / bucket_size))
        buckets[key] += b.volume
    if not buckets:
        return None, None, None

    total_volume = sum(buckets.values())
    poc_key = max(buckets, key=buckets.get)
    target = total_volume * value_area_pct

    sorted_keys = sorted(buckets.keys())
    lo_i = hi_i = poc_key
    acc = buckets[poc_key]
    while acc < target:
        below = buckets.get(lo_i - 1, 0.0)
        above = buckets.get(hi_i + 1, 0.0)
        if below == 0.0 and above == 0.0:
            break
        if below >= above:
            lo_i -= 1
            acc += below
        else:
            hi_i += 1
            acc += above

    poc = lo + poc_key * bucket_size
    val = lo + lo_i * bucket_size
    vah = lo + hi_i * bucket_size
    return poc, vah, val


def compute_1h_levels(today_working_bars: List[Bar], session_open_minutes_ago: Optional[float]) -> Dict[str, Optional[float]]:
    if session_open_minutes_ago is None or session_open_minutes_ago < 60 or not today_working_bars:
        return {"1H-High": None, "1H-Low": None}
    first_hour = [b for b in today_working_bars if _minutes_from_start(today_working_bars, b) <= 60]
    if not first_hour:
        return {"1H-High": None, "1H-Low": None}
    return {"1H-High": max(b.high for b in first_hour), "1H-Low": min(b.low for b in first_hour)}


def _minutes_from_start(bars: List[Bar], bar: Bar) -> float:
    if not bars:
        return 0.0
    return (bar.ts - bars[0].ts).total_seconds() / 60.0


def confirm_1h_strength(working_bars: List[Bar], level_price: float, tolerance: float) -> int:
    """Кількість чітких реакцій ціни на рівень після завершення 1-ї години (розділ 4.1)."""
    touches = 0
    for b in working_bars:
        if abs(b.high - level_price) <= tolerance or abs(b.low - level_price) <= tolerance:
            touches += 1
    return touches


class KeyLevelsStrategy(Strategy):
    id = StrategyId.S8_KEY_LEVELS
    name = "Ключові рівні дня"

    def scan(
        self,
        ctx: StrategyContext,
        prev_day_intraday_bars: Optional[List[Bar]] = None,
    ) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events
        if not ctx.daily_bars or not ctx.working_bars:
            return events

        pdh = ctx.daily_bars[-1].high
        pdl = ctx.daily_bars[-1].low
        poc, vah, val = compute_poc_and_value_area(prev_day_intraday_bars) if prev_day_intraday_bars else (None, None, None)
        one_h = compute_1h_levels(ctx.working_bars, ctx.session_open_minutes_ago)

        technical_stop = ctx.atr.atr_value * 0.25 if ctx.atr.atr_value else ctx.instrument.point_value * 15
        tolerance = technical_stop * 0.5
        offset_mid = (cfg.breakout_offset_points_min + cfg.breakout_offset_points_max) / 2

        # Базові п'ять рівнів (розділ 2 "Авторської стратегії") + VAH/VAL як
        # додатковий контекст для моделі "Пробій" (розділ 3.4/6.4: "на пробитті
        # VAH/VAL і закріпленні за ним — пробій").
        levels_map: Dict[str, Optional[float]] = {"PDH": pdh, "PDL": pdl, "POC": poc, **one_h, "VAH": vah, "VAL": val}

        # Яка з трьох базових моделей застосовна до кожного рівня — розділ 6.4:
        # PDH/PDL: усі три; POC: лише Відбій (пробій живе на межах VA, тобто VAH/VAL);
        # VAH/VAL: Пробій + Хибний пробій; 1H-рівні: Пробій + Хибний пробій (пріоритетно).
        applicable_models: Dict[str, set] = {
            "PDH": {"bounce", "breakout", "false_breakout"},
            "PDL": {"bounce", "breakout", "false_breakout"},
            "POC": {"bounce"},
            "VAH": {"breakout", "false_breakout"},
            "VAL": {"breakout", "false_breakout"},
            "1H-High": {"breakout", "false_breakout", "bounce"},
            "1H-Low": {"breakout", "false_breakout", "bounce"},
        }

        # 1H рівні торгуються лише після підтвердження сили (розділ 4)
        confirmed_levels: Dict[str, float] = {}
        for name, price in levels_map.items():
            if price is None:
                continue
            if name in ("1H-High", "1H-Low"):
                if confirm_1h_strength(ctx.working_bars, price, tolerance) < ONE_HOUR_STRENGTH_MIN_TOUCHES:
                    continue
            confirmed_levels[name] = price

        zones = calc.confluence_zones(levels_map, technical_stop, cfg.confluence_threshold_stops)
        confluence_names = {n for z in zones for n in z["pair"]}

        for name, price in confirmed_levels.items():
            models = applicable_models.get(name, {"bounce"})
            kind = "support" if name in ("PDL", "1H-Low", "VAL") else "resistance"
            if name == "POC":
                kind = "support" if ctx.working_bars[-1].close >= price else "resistance"

            direction = Direction.LONG if kind == "support" else Direction.SHORT
            is_confluence = name in confluence_names
            label = f"{name}" + (" [ЗОНА КОНФЛЮЕНСУ]" if is_confluence else "")
            level_strength = 2 if is_confluence else 0

            if "bounce" in models:
                self._scan_bounce(ctx, events, name, label, price, kind, direction, technical_stop, tolerance, level_strength, is_confluence, cfg)
            if "breakout" in models:
                self._scan_breakout(ctx, events, name, label, price, direction, offset_mid, level_strength, is_confluence, cfg)
            if "false_breakout" in models:
                self._scan_false_breakout(ctx, events, name, label, price, kind, direction, level_strength, is_confluence, cfg)

        return events

    def _scan_bounce(self, ctx, events, name, label, price, kind, direction, technical_stop, tolerance, level_strength, is_confluence, cfg):
        bounce_state = lv.detect_bsu_bpu_sequence(
            ctx.working_bars, price, kind, touch_tolerance=tolerance, luft=technical_stop * cfg.luft_pct_of_stop,
        )
        if bounce_state.stage in ("bsu", "bsu_bpu1"):
            events.append(FormationAlert(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                level_price=price, level_kind=kind,
                stage=f"{label}: {bounce_state.detail}",
                detail=f"[Відбій] Рівень {label} = {price:.5g}. {bounce_state.detail}",
                ts=ctx.now, extra={"level_name": name, "confluence": is_confluence},
            ))
        elif bounce_state.stage == "ready_bpu2":
            pos = calc.bounce_position(price, technical_stop, direction, cfg, ctx.commission)
            if pos.rr_ok:
                order_type = "Buy Limit" if direction == Direction.LONG else "Sell Limit"
                events.append(TradeSignal(
                    instrument=ctx.instrument, strategy=self.id, direction=direction,
                    scenario=f"Відбій від {label}",
                    level_price=price, level_kind=kind, level_strength=level_strength,
                    order=pos.to_order(order_type),
                    delta_stop=technical_stop, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                    atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                    commission=ctx.commission, ts=ctx.now,
                    extra={"level_name": name, "confluence": is_confluence},
                ))

    def _scan_breakout(self, ctx, events, name, label, price, direction, offset_mid, level_strength, is_confluence, cfg):
        """Модель 'Пробій' для рівнів дня (розд. 6.4) — раніше була ВІДСУТНЯ в цій
        стратегії; тепер застосовується до PDH/PDL/VAH/VAL/1H за тією ж логікою,
        що й Стратегія 2 (акумуляція -> фактичний вихід за рівень)."""
        last = ctx.working_bars[-1]
        accumulating = lv.detect_accumulation(ctx.working_bars, price, n=5)
        broke_up = last.close > price + offset_mid * ctx.instrument.point_value
        broke_down = last.close < price - offset_mid * ctx.instrument.point_value
        triggered = (direction == Direction.LONG and broke_up) or (direction == Direction.SHORT and broke_down)

        if not triggered:
            if accumulating:
                events.append(FormationAlert(
                    instrument=ctx.instrument, strategy=self.id, direction=direction,
                    level_price=price, level_kind="breakout-watch",
                    stage=f"{label}: акумуляція перед рівнем",
                    detail=f"[Пробій] Акумуляція біля {label} = {price:.5g}. Можливий пробій у бік {direction.value}.",
                    ts=ctx.now, extra={"level_name": name, "confluence": is_confluence},
                ))
            return
        pos, methods = calc.breakout_position(
            level=price, direction=direction, offset_points=offset_mid,
            point_value=ctx.instrument.point_value, cfg=cfg, atr_value=ctx.atr.atr_value,
            commission=ctx.commission,
        )
        if pos.rr_ok:
            order_type = "Buy Stop" if direction == Direction.LONG else "Sell Stop"
            events.append(TradeSignal(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                scenario=f"Пробій {label} (метод стопу: {methods.chosen_method})",
                level_price=price, level_kind="breakout", level_strength=level_strength,
                order=pos.to_order(order_type),
                delta_stop=methods.chosen, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                commission=ctx.commission, ts=ctx.now,
                extra={"level_name": name, "confluence": is_confluence},
            ))

    def _scan_false_breakout(self, ctx, events, name, label, price, kind, direction, level_strength, is_confluence, cfg):
        fb_state = pt.detect_false_breakout(ctx.working_bars, price, kind)
        if fb_state.stage in ("pierced", "watching_scenario3"):
            events.append(FormationAlert(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                level_price=price, level_kind=kind,
                stage=f"{label}: {fb_state.detail}",
                detail=f"[Хибний пробій] Рівень {label} = {price:.5g}. {fb_state.detail}",
                ts=ctx.now, extra={"level_name": name, "confluence": is_confluence},
            ))
        elif fb_state.stage in ("reversed_scenario1", "reversed_scenario2") and fb_state.tail_distance:
            pos, stop = calc.false_breakout_position(
                price, direction, fb_state.tail_distance, ctx.instrument.point_value, cfg, ctx.commission,
            )
            if pos.rr_ok:
                order_type = "Buy Stop" if direction == Direction.LONG else "Sell Stop"
                events.append(TradeSignal(
                    instrument=ctx.instrument, strategy=self.id, direction=direction,
                    scenario=f"Хибний пробій {label}",
                    level_price=price, level_kind=kind, level_strength=level_strength,
                    order=pos.to_order(order_type),
                    delta_stop=stop.chosen, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                    atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                    commission=ctx.commission, ts=ctx.now,
                    extra={"level_name": name, "confluence": is_confluence},
                ))
