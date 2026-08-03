"""
Стратегія 6 — СХОДИНКИ (нисхідна база / висхідні низи).
Формація: 2 підтверджені кроки (розділ 3-4 "Стратегії 6"). Сигнал: закриття
бару за попереднім ключовим хаєм/лоу. Стоп — за ПОПЕРЕДНІМ з двох екстремумів
("правило двох стопів", розділ 7).
"""
from __future__ import annotations

from typing import List, Optional, Union

from bot.indicators.atr import is_atr_exhausted
from bot.models import Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import levels as lv
from bot.strategies import patterns as pt
from bot.strategies.base import Strategy, StrategyContext


class StaircaseStrategy(Strategy):
    id = StrategyId.S6_STAIRCASE
    name = "Сходинки"

    def scan(self, ctx: StrategyContext) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events
        if len(ctx.working_bars) < 15:
            return events

        swings = lv.find_swing_points(ctx.working_bars, lookback=cfg.__dict__.get("swing_lookback_bars", 3) or 3)
        low_swings = [s for s in swings if s.kind == "low"]
        high_swings = [s for s in swings if s.kind == "high"]
        lows = [s.price for s in low_swings[-4:]]
        highs = [s.price for s in high_swings[-4:]]
        last_close = ctx.working_bars[-1].close

        state = pt.detect_staircase(lows, highs, last_close)
        if state.stage == "none":
            return events

        direction = Direction.LONG if state.direction == "LONG" else Direction.SHORT

        def _volume_fading(direction: Direction) -> Optional[bool]:
            """Обсяги на кожному новому кроці НЕ повинні згасати (розділ 2.2, обов'язкова
            умова; розділ 10 — умова скасування). Повертає None, якщо даних про обсяг
            замало для оцінки (не блокуємо угоду через відсутність даних)."""
            relevant = low_swings if direction == Direction.LONG else high_swings
            if len(relevant) < 2:
                return None
            v_prev = ctx.working_bars[relevant[-2].index].volume
            v_last = ctx.working_bars[relevant[-1].index].volume
            if not v_prev or not v_last:
                return None
            return v_last < v_prev * 0.7  # допуск ~30% — не вимагаємо строгої монотонності

        fading = _volume_fading(direction)

        if state.stage == "two_steps_ready":
            detail = f"{state.detail}. Ключова точка входу: {state.key_point:.5g}." if state.key_point else state.detail
            if fading:
                detail += " ⚠️ Обсяги на останньому кроці згасають — розділ 10 'Стратегії 6' (ризик слабшого руху)."
            events.append(FormationAlert(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                level_price=state.key_point or last_close, level_kind="staircase",
                stage=state.detail, detail=detail, ts=ctx.now,
            ))
            return events

        if state.stage == "signal" and state.key_point and state.prior_extreme:
            try:
                pos = calc.staircase_position(
                    trigger_price=state.key_point, prior_extreme_price=state.prior_extreme,
                    direction=direction, cfg=cfg,
                    buffer_abs=ctx.atr.atr_value * 0.05 if ctx.atr.atr_value else 0.0,
                    commission=ctx.commission,
                )
            except ValueError:
                return events
            if not pos.rr_ok:
                return events

            warns = []
            if fading:
                warns.append("Обсяги на останньому кроці згасають — розділ 2.2/10 'Стратегії 6' (умова скасування в оригінальній методиці)")

            order_type = "Buy Stop" if direction == Direction.LONG else "Sell Stop"
            events.append(TradeSignal(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                scenario="Правило двох стопів (стоп за попереднім екстремумом)",
                level_price=state.key_point, level_kind="staircase", level_strength=0,
                order=pos.to_order(order_type),
                delta_stop=pos.stop_distance, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                commission=ctx.commission, ts=ctx.now, warnings=warns,
                extra={
                    "prior_extreme": state.prior_extreme,
                    "note": "Після фіксації 3R активуйте трейлінг-стоп (bot/strategies/s6 не веде відкриті позиції — це робить bot/state)",
                },
            ))
        return events
