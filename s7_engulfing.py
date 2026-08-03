"""
Стратегія 7 — ПОГЛИНАННЯ.
Один бар перекриває >= 3 попередні (розділ 2 "Стратегії 7"). Через природу
формації (сигнал стає відомий лише на закритті бару) — раннє попередження
видається, коли бар ЩЕ ФОРМУЄТЬСЯ і вже зараз перекриває потрібну кількість
попередніх барів (спостерігається на кожному 5-хв опитуванні до закриття бару).
"""
from __future__ import annotations

from typing import List, Union

from bot.indicators.atr import is_atr_exhausted
from bot.models import Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import levels as lv
from bot.strategies import patterns as pt
from bot.strategies.base import Strategy, StrategyContext


class EngulfingStrategy(Strategy):
    id = StrategyId.S7_ENGULFING
    name = "Поглинання"

    def scan(self, ctx: StrategyContext) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events
        if len(ctx.working_bars) < cfg.engulfing_min_bars + 2:
            return events

        result = pt.detect_engulfing(ctx.working_bars, min_bars=cfg.engulfing_min_bars)
        if not result.detected:
            return events

        last_bar = ctx.working_bars[-1]
        if lv.is_paranormal_bar(last_bar, ctx.working_bars[-15:]):
            return events  # аномально великий поглинаючий бар — скасування (розділ 9 "Стратегії 7")

        direction = Direction.LONG if result.kind == "bullish" else Direction.SHORT
        strength = calc.engulfing_signal_strength(result.bars_engulfed)

        pos = calc.engulfing_position(
            bar_high=result.engulf_high, bar_low=result.engulf_low, direction=direction,
            offset_points=3, buffer_points=3, point_value=ctx.instrument.point_value,
            cfg=cfg, commission=ctx.commission,
        )
        if not pos.rr_ok:
            return events

        order_type = "Buy Stop" if direction == Direction.LONG else "Sell Stop"
        events.append(TradeSignal(
            instrument=ctx.instrument, strategy=self.id, direction=direction,
            scenario=f"Поглинуто {result.bars_engulfed} бар(и) — {strength}",
            level_price=result.engulf_high if direction == Direction.LONG else result.engulf_low,
            level_kind="engulfing", level_strength=result.bars_engulfed,
            order=pos.to_order(order_type),
            delta_stop=pos.stop_distance, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
            atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
            commission=ctx.commission, ts=ctx.now,
            extra={"bars_engulfed": result.bars_engulfed, "signal_strength": strength,
                   "context_note": "Перевірте контекст самостійно: розворот (на екстремумі) чи продовження (на пробитті рівня) — розділ 4 'Стратегії 7'"},
        ))
        return events
