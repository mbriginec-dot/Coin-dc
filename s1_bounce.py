"""
Стратегія 1 — ВІДБІЙ ВІД РІВНЯ.
Формація: БСУ -> БПУ1 -> БПУ2 (bot/strategies/levels.py: detect_bsu_bpu_sequence).
Скасування: поджаття, аномальний БПУ2, пробій рівня, перша година сесії
(розділ 9 "Стратегії 1").
"""
from __future__ import annotations

from typing import List, Union

from bot.models import Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import levels as lv
from bot.strategies import patterns as pt
from bot.strategies.base import Strategy, StrategyContext


def _measure_technical_stop(bars, level_price: float, kind: str, atr_value: float) -> float:
    """Наближення 'технічного стопу за хвостом' (розділ 6.1 'Стратегії 1'): відстань
    від рівня до найглибшого хвоста серед останніх 3 барів формації, з невеликим
    буфером; якщо виміряти неможливо — резервно 15% ATR."""
    recent = bars[-3:] if len(bars) >= 3 else bars
    if not recent:
        return max(atr_value * 0.15, 0.01)
    if kind == "support":
        worst = min(b.low for b in recent)
        dist = level_price - worst
    else:
        worst = max(b.high for b in recent)
        dist = worst - level_price
    buffer = atr_value * 0.05 if atr_value else 0.0
    dist = dist + buffer
    return dist if dist > 0 else max(atr_value * 0.15, 0.01)


class BounceStrategy(Strategy):
    id = StrategyId.S1_BOUNCE
    name = "Відбій від рівня"

    def scan(self, ctx: StrategyContext) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        STRONG_LEVEL_THRESHOLD = 2  # "дуже сильний денний рівень" — Виняток 1 (розділ 2.1 "Стратегії 1")

        from bot.indicators.atr import is_atr_exhausted
        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events

        if len(ctx.working_bars) < 3:
            return events

        touch_tol = max(ctx.atr.atr_value * 0.05, ctx.instrument.point_value * 2)

        for level in ctx.levels:
            luft = touch_tol  # орієнтовний люфт для пошуку дотиків, остаточний люфт рахується в калькуляторі
            state = lv.detect_bsu_bpu_sequence(
                ctx.working_bars, level.price, level.kind, touch_tolerance=touch_tol, luft=luft
            )

            if state.stage == "none" or state.stage == "broken":
                continue

            direction = Direction.LONG if level.kind == "support" else Direction.SHORT

            # Перша година сесії — модель зазвичай не торгується (розділ 2.1 "Стратегії 1"),
            # окрім двох винятків: (1) попереду дуже сильний денний рівень, (2) у перший
            # час уже сформувався лімітний рівень із хибним пробоєм саме на цьому рівні.
            if ctx.session_open_minutes_ago is not None and ctx.session_open_minutes_ago < 60:
                strong_level_exception = level.strength >= STRONG_LEVEL_THRESHOLD
                fb_in_first_hour = pt.detect_false_breakout(ctx.working_bars, level.price, level.kind)
                false_breakout_exception = fb_in_first_hour.stage in ("reversed_scenario1", "reversed_scenario2")
                if not (strong_level_exception or false_breakout_exception):
                    continue

            # Поджаття — стоп-сигнал саме для "Відбою" (розділ 8 "Стратегії 1")
            compressing = lv.detect_compression(ctx.working_bars, level.price, level.kind, n=3)

            if state.stage in ("bsu", "bsu_bpu1"):
                if compressing:
                    continue  # поджаття — не попереджаємо про Відбій, радше очікуємо Пробій
                events.append(FormationAlert(
                    instrument=ctx.instrument, strategy=self.id, direction=direction,
                    level_price=level.price, level_kind=level.kind,
                    stage=state.detail, detail=(
                        f"Рівень {level.kind} {level.price:.5g}, сила {level.strength}. "
                        f"{state.detail}. Дотиків до рівня: {level.touches}."
                    ),
                    ts=ctx.now,
                ))
                continue

            if state.stage == "ready_bpu2":
                bpu2_bar = ctx.working_bars[state.bpu2_index]
                if compressing:
                    continue
                if lv.is_paranormal_bar(bpu2_bar, ctx.working_bars[-15:]):
                    continue  # аномальний БПУ2 — скасування (розділ 9 "Стратегії 1")

                technical_stop = _measure_technical_stop(
                    ctx.working_bars[max(0, state.bsu_index):state.bpu2_index + 1],
                    level.price, level.kind, ctx.atr.atr_value,
                )
                try:
                    pos = calc.bounce_position(level.price, technical_stop, direction, cfg, ctx.commission)
                except ValueError:
                    continue
                if not pos.rr_ok:
                    continue

                order_type = "Buy Limit" if direction == Direction.LONG else "Sell Limit"
                warns = [] if pos.rr_ok else ["Фактичне R:R нижче мінімуму"]
                if (direction == Direction.LONG and ctx.global_trend == "down") or \
                   (direction == Direction.SHORT and ctx.global_trend == "up"):
                    warns.append("Глобальний тренд (денний) суперечить напрямку угоди — розділ 3.3 алгоритму")
                events.append(TradeSignal(
                    instrument=ctx.instrument, strategy=self.id, direction=direction, scenario=None,
                    level_price=level.price, level_kind=level.kind, level_strength=level.strength,
                    order=pos.to_order(order_type),
                    delta_stop=technical_stop, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                    atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                    commission=ctx.commission, ts=ctx.now,
                    warnings=warns,
                ))
        return events
