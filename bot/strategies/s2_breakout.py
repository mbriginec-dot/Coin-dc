"""
Стратегія 2 — ПРОБІЙ РІВНЯ.
Формація: акумуляція перед рівнем (розділ 3 "Стратегії 2") -> раннє попередження.
Сигнал: ціна фактично пробила рівень + 2-5 пунктів (Buy/Sell Stop спрацював).
Скасування: повернення ціни за рівень (це вже Хибний пробій, розділ 9).
"""
from __future__ import annotations

from typing import List, Union

from bot.indicators.atr import is_atr_exhausted
from bot.models import Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import levels as lv
from bot.strategies.base import Strategy, StrategyContext


class BreakoutStrategy(Strategy):
    id = StrategyId.S2_BREAKOUT
    name = "Пробій рівня"

    def scan(self, ctx: StrategyContext) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events
        if len(ctx.working_bars) < 12:
            return events

        last = ctx.working_bars[-1]
        offset_mid = (cfg.breakout_offset_points_min + cfg.breakout_offset_points_max) / 2

        for level in ctx.levels:
            direction = Direction.LONG if level.kind == "resistance" else Direction.SHORT
            accumulating = lv.detect_accumulation(ctx.working_bars, level.price, n=5)

            broke_up = last.close > level.price + offset_mid * ctx.instrument.point_value
            broke_down = last.close < level.price - offset_mid * ctx.instrument.point_value
            triggered = (direction == Direction.LONG and broke_up) or (direction == Direction.SHORT and broke_down)

            if not triggered:
                if accumulating:
                    vol_note = ""
                    if lv.is_unusual_volume(last, ctx.working_bars[-20:]):
                        vol_note = " Сплеск обсягу (Unusual Volume) — непрямий доказ присутності великого гравця (розділ 2.3 'Стратегії 2')."
                    events.append(FormationAlert(
                        instrument=ctx.instrument, strategy=self.id, direction=direction,
                        level_price=level.price, level_kind=level.kind,
                        stage="Акумуляція перед рівнем",
                        detail=(
                            f"Акумуляція (звужений діапазон, тиснення до рівня {level.price:.5g}). "
                            f"Можливий пробій у бік {direction.value}.{vol_note}"
                        ),
                        ts=ctx.now,
                    ))
                continue

            pos, methods = calc.breakout_position(
                level=level.price, direction=direction, offset_points=offset_mid,
                point_value=ctx.instrument.point_value, cfg=cfg, atr_value=ctx.atr.atr_value,
                commission=ctx.commission,
            )
            if not pos.rr_ok:
                continue

            order_type = "Buy Stop" if direction == Direction.LONG else "Sell Stop"
            events.append(TradeSignal(
                instrument=ctx.instrument, strategy=self.id, direction=direction,
                scenario=f"Метод стопу: {methods.chosen_method}",
                level_price=level.price, level_kind=level.kind, level_strength=level.strength,
                order=pos.to_order(order_type),
                delta_stop=methods.chosen, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                commission=ctx.commission, ts=ctx.now,
                extra={"stop_methods": {
                    "0.2% від ціни": methods.pct_of_price,
                    "Пункти (мін)": methods.points_min,
                    "Пункти (макс)": methods.points_max,
                    "ATR × мульт.": methods.atr_based,
                }},
            ))
        return events
