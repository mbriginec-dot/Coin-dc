"""
Стратегія 5 — ТОРГІВЛЯ В КАНАЛІ.
Дозвільний фільтр (ширина каналу >= 6 стопів, запас ходу >= 4 стопи, розділ 3-4
"Стратегії 5") + сигнал типу "Відбій" від меж каналу (розділ 5-7).
Канал визначається як діапазон хай/лоу за останні N денних барів.
"""
from __future__ import annotations

from typing import List, Union

from bot.indicators.atr import is_atr_exhausted
from bot.models import Direction, FormationAlert, StrategyId, TradeSignal
from bot.risk import calculator as calc
from bot.strategies import levels as lv
from bot.strategies.base import Strategy, StrategyContext

CHANNEL_LOOKBACK_DAYS = 30


class ChannelStrategy(Strategy):
    id = StrategyId.S5_CHANNEL
    name = "Торгівля в каналі"

    def scan(self, ctx: StrategyContext) -> List[Union[FormationAlert, TradeSignal]]:
        events: List[Union[FormationAlert, TradeSignal]] = []
        cfg = ctx.cfg.risk

        if is_atr_exhausted(ctx.atr.pct_used_today, cfg.atr_exhausted_pct):
            return events
        if len(ctx.daily_bars) < 5 or not ctx.working_bars:
            return events

        window = ctx.daily_bars[-CHANNEL_LOOKBACK_DAYS:]
        upper = max(b.high for b in window)
        lower = min(b.low for b in window)
        current_price = ctx.working_bars[-1].close
        technical_stop = ctx.atr.atr_value * 0.5 if ctx.atr.atr_value else (upper - lower) * 0.05
        if technical_stop <= 0:
            return events

        check = calc.channel_check(upper, lower, current_price, technical_stop, cfg)
        if not check.width_ok:
            return events  # канал занадто вузький — стратегія тут не розглядається взагалі

        near_lower = (current_price - lower) <= technical_stop * 1.5
        near_upper = (upper - current_price) <= technical_stop * 1.5

        if near_lower and check.long_allowed:
            state = lv.detect_bsu_bpu_sequence(
                ctx.working_bars, lower, "support",
                touch_tolerance=technical_stop * 0.3, luft=technical_stop * cfg.luft_pct_of_stop,
            )
            if state.stage in ("bsu", "bsu_bpu1"):
                events.append(FormationAlert(
                    instrument=ctx.instrument, strategy=self.id, direction=Direction.LONG,
                    level_price=lower, level_kind="support",
                    stage=state.detail,
                    detail=(
                        f"Ціна біля нижньої межі каналу [{lower:.5g}; {upper:.5g}], "
                        f"ширина {check.width_stops:.1f} стопів, запас ходу вгору {check.room_up_stops:.1f} стопів. {state.detail}"
                    ),
                    ts=ctx.now,
                ))
            elif state.stage == "ready_bpu2":
                pos = calc.channel_position(upper, lower, technical_stop, Direction.LONG, cfg, ctx.commission)
                if pos.rr_ok:
                    events.append(TradeSignal(
                        instrument=ctx.instrument, strategy=self.id, direction=Direction.LONG,
                        scenario=f"Ширина каналу {check.width_stops:.1f} стопів" + (" (широкий)" if check.is_wide_channel else ""),
                        level_price=lower, level_kind="support", level_strength=0,
                        order=pos.to_order("Buy Limit"),
                        delta_stop=technical_stop, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                        atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                        commission=ctx.commission, ts=ctx.now,
                        extra={"upper": upper, "lower": lower, "width_stops": check.width_stops, "room_stops": check.room_up_stops},
                    ))

        if near_upper and check.short_allowed:
            state = lv.detect_bsu_bpu_sequence(
                ctx.working_bars, upper, "resistance",
                touch_tolerance=technical_stop * 0.3, luft=technical_stop * cfg.luft_pct_of_stop,
            )
            if state.stage in ("bsu", "bsu_bpu1"):
                events.append(FormationAlert(
                    instrument=ctx.instrument, strategy=self.id, direction=Direction.SHORT,
                    level_price=upper, level_kind="resistance",
                    stage=state.detail,
                    detail=(
                        f"Ціна біля верхньої межі каналу [{lower:.5g}; {upper:.5g}], "
                        f"ширина {check.width_stops:.1f} стопів, запас ходу вниз {check.room_down_stops:.1f} стопів. {state.detail}"
                    ),
                    ts=ctx.now,
                ))
            elif state.stage == "ready_bpu2":
                pos = calc.channel_position(upper, lower, technical_stop, Direction.SHORT, cfg, ctx.commission)
                if pos.rr_ok:
                    events.append(TradeSignal(
                        instrument=ctx.instrument, strategy=self.id, direction=Direction.SHORT,
                        scenario=f"Ширина каналу {check.width_stops:.1f} стопів" + (" (широкий)" if check.is_wide_channel else ""),
                        level_price=upper, level_kind="resistance", level_strength=0,
                        order=pos.to_order("Sell Limit"),
                        delta_stop=technical_stop, risk_money=pos.risk_money, rr_actual=pos.rr_actual,
                        atr_value=ctx.atr.atr_value, atr_used_pct_today=ctx.atr.pct_used_today or 0.0,
                        commission=ctx.commission, ts=ctx.now,
                        extra={"upper": upper, "lower": lower, "width_stops": check.width_stops, "room_stops": check.room_down_stops},
                    ))
        return events
