"""
Стратегія 3 — ХИБНИЙ ПРОБІЙ.
Формація: рівень пробитий, бар(и) закрились за рівнем без імпульсу (розділ 3 "Стратегії 3").
Сигнал: розворот підтверджено (ціна повернулась за рівень) в одному з 3 сценаріїв.
"""
from __future__ import annotations

from typing import List, Union

from bot.indicators.atr import is_atr_exhausted
from bot.models import Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import patterns as pt
from bot.strategies.base import Strategy, StrategyContext

_SCENARIO_LABELS = {1: "Сценарій 1 (простий, 1 бар)", 2: "Сценарій 2 (складний, 2 бари)", 3: "Сценарій 3 (складний, 3+ барів)"}


class FalseBreakoutStrategy(Strategy):
    id = StrategyId.S3_FALSE_BREAKOUT
    name = "Хибний пробій"

    def scan(self, ctx: StrategyContext) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events
        if len(ctx.working_bars) < 3:
            return events

        for level in ctx.levels:
            state = pt.detect_false_breakout(ctx.working_bars, level.price, level.kind)

            if state.stage == "none":
                continue

            # LONG очікуємо після хибного пробою підтримки вниз; SHORT — після хибного пробою опору вгору
            direction = Direction.LONG if level.kind == "support" else Direction.SHORT

            if state.stage in ("pierced", "watching_scenario3"):
                events.append(FormationAlert(
                    instrument=ctx.instrument, strategy=self.id, direction=direction,
                    level_price=level.price, level_kind=level.kind,
                    stage=state.detail,
                    detail=(
                        f"Рівень {level.kind} {level.price:.5g} пробито ({state.bars_beyond_level} бар(и) за рівнем). "
                        f"{state.detail}. Очікуємо підтвердження розвороту."
                    ),
                    ts=ctx.now,
                    extra={"tail_distance": state.tail_distance},
                ))
                continue

            if state.stage in ("reversed_scenario1", "reversed_scenario2") and state.tail_distance:
                try:
                    pos, stop = calc.false_breakout_position(
                        level=level.price, direction=direction, tail_distance=state.tail_distance,
                        point_value=ctx.instrument.point_value, cfg=cfg, commission=ctx.commission,
                    )
                except ValueError:
                    continue
                if not pos.rr_ok:
                    continue

                order_type = "Buy Stop" if direction == Direction.LONG else "Sell Stop"
                events.append(TradeSignal(
                    instrument=ctx.instrument, strategy=self.id, direction=direction,
                    scenario=_SCENARIO_LABELS.get(state.scenario, "Сценарій"),
                    level_price=level.price, level_kind=level.kind, level_strength=level.strength,
                    order=pos.to_order(order_type),
                    delta_stop=stop.chosen, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                    atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                    commission=ctx.commission, ts=ctx.now,
                    extra={
                        "хвіст+буфер": stop.tail_plus_buffer,
                        "резерв 0.2%": stop.reserve_pct,
                        "резерв пункти": (stop.reserve_points_min, stop.reserve_points_max),
                        "bars_beyond_level": state.bars_beyond_level,
                    },
                ))
        return events
