"""
Стратегія 4 — РІЗКИЙ ІМПУЛЬС (momentum на відкритті сесії).
На відміну від інших стратегій, це не аналіз одного рівня, а перевірка
контексту S&P500 + гep-фільтр + наближення до ключового рівня саме в перші
хвилини сесії (розділ 2-9 "Стратегії 4"). Активна лише для акцій/ф'ючерсів
і лише в вікні часу після відкриття (типово перші 30-60 хв).
"""
from __future__ import annotations

from typing import List, Optional, Union

from bot.models import AssetClass, Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies.base import Strategy, StrategyContext

MOMENTUM_WINDOW_MINUTES = 30  # активне вікно після відкриття сесії (розділ 1.2 "Стратегії 4")


class MomentumStrategy(Strategy):
    id = StrategyId.S4_MOMENTUM
    name = "Різкий імпульс"

    def scan(
        self,
        ctx: StrategyContext,
        sp500_prev_close: Optional[float] = None,
        sp500_today_open: Optional[float] = None,
    ) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if ctx.instrument.asset_class not in (AssetClass.STOCK, AssetClass.FUTURES):
            return events
        if ctx.session_open_minutes_ago is None or ctx.session_open_minutes_ago > MOMENTUM_WINDOW_MINUTES:
            return events
        if not ctx.today_bar or not ctx.daily_bars:
            return events

        prev_close = ctx.daily_bars[-1].close
        today_open = ctx.working_bars[0].open if ctx.working_bars else ctx.today_bar.open
        gap_pct = abs(today_open - prev_close) / prev_close if prev_close else 0.0
        if gap_pct > cfg.momentum_max_gap_pct:
            return events  # гep-фільтр (розділ 9.1)

        priority = "mixed"
        sp500_change_pct = None
        if sp500_prev_close is not None and sp500_today_open is not None and sp500_prev_close:
            sp500_change_pct = (sp500_today_open - sp500_prev_close) / sp500_prev_close
            priority = "long" if sp500_today_open >= sp500_prev_close else "short"

        # Відносна сила/слабкість до ринку (розділ 9.2 "Стратегії 4") — акція, що
        # рухається "власним життям" незалежно від S&P500, є пріоритетним кандидатом.
        instrument_change_pct = (today_open - prev_close) / prev_close if prev_close else 0.0
        relative_strength = None
        if sp500_change_pct is not None:
            relative_strength = instrument_change_pct - sp500_change_pct

        # Обережність з розтягнутим багатоденним рухом (розділ 2.3/11 "Стратегії 4"):
        # якщо інструмент уже пройшов значний шлях за останні кілька днів в один бік,
        # продовження руху статистично менш надійне.
        extended_move_pct = None
        if len(ctx.daily_bars) >= 4:
            base_close = ctx.daily_bars[-4].close
            if base_close:
                extended_move_pct = (ctx.daily_bars[-1].close - base_close) / base_close

        last = ctx.working_bars[-1] if ctx.working_bars else None
        if not last:
            return events

        for level in ctx.levels:
            direction = Direction.LONG if level.kind == "resistance" else Direction.SHORT
            if priority == "long" and direction != Direction.LONG:
                continue
            if priority == "short" and direction != Direction.SHORT:
                continue

            near_level = abs(last.close - level.price) <= ctx.atr.atr_value * 0.3 if ctx.atr.atr_value else False
            offset = (cfg.breakout_offset_points_min + cfg.breakout_offset_points_max) / 2
            triggered = (
                (direction == Direction.LONG and last.close > level.price + offset * ctx.instrument.point_value)
                or (direction == Direction.SHORT and last.close < level.price - offset * ctx.instrument.point_value)
            )

            rel_strength_note = ""
            if relative_strength is not None:
                aligned = (direction == Direction.LONG and relative_strength > 0) or (direction == Direction.SHORT and relative_strength < 0)
                if aligned and abs(relative_strength) >= 0.003:
                    rel_strength_note = f" Відносна сила до S&P500: {relative_strength*100:+.2f}% (незалежний рух — сильніший сетап)."

            if not triggered:
                if near_level:
                    events.append(FormationAlert(
                        instrument=ctx.instrument, strategy=self.id, direction=direction,
                        level_price=level.price, level_kind=level.kind,
                        stage="Наближення до ключового рівня на відкритті",
                        detail=(
                            f"S&P500 пріоритет: {priority}. Гep на відкритті: {gap_pct*100:.2f}%. "
                            f"Ціна наближається до рівня {level.price:.5g}.{rel_strength_note}"
                        ),
                        ts=ctx.now,
                    ))
                continue

            technical_stop = ctx.atr.atr_value * 0.25 if ctx.atr.atr_value else ctx.instrument.point_value * 15
            pos, limit_price = calc.momentum_position(
                level=level.price, direction=direction, offset_points=offset,
                point_value=ctx.instrument.point_value, technical_stop=technical_stop, cfg=cfg,
                use_stop_limit=True, limit_buffer_points=offset, commission=ctx.commission,
            )
            if not pos.rr_ok:
                continue

            warns = []
            if extended_move_pct is not None:
                extended_same_direction = (direction == Direction.LONG and extended_move_pct >= 0.08) or \
                                           (direction == Direction.SHORT and extended_move_pct <= -0.08)
                if extended_same_direction:
                    warns.append(
                        f"Інструмент уже пройшов {extended_move_pct*100:+.1f}% за останні ~3 дні в тому ж напрямку "
                        f"— продовження статистично менш надійне (розділ 2.3 'Стратегії 4')"
                    )

            order_type = "Buy Stop-Limit" if direction == Direction.LONG else "Sell Stop-Limit"
            events.append(TradeSignal(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                scenario=f"S&P500 пріоритет: {priority}, гep {gap_pct*100:.2f}%" + (
                    f", відн. сила {relative_strength*100:+.2f}%" if relative_strength is not None else ""
                ),
                level_price=level.price, level_kind=level.kind, level_strength=level.strength,
                order=pos.to_order(order_type, limit_price=limit_price),
                delta_stop=technical_stop, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                commission=ctx.commission, ts=ctx.now, warnings=warns,
            ))
        return events
