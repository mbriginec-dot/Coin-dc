"""
Формульний рушій — точне відтворення розрахунків з усіх восьми файлів
"Калькулятор_*.xlsx". Кожна функція нижче відповідає конкретному аркушу
"Калькулятор" відповідного файлу; посилання на розділи документів наведені
в docstring.

Спільна база для ВСІХ стратегій (перевірено по кожному калькулятору):
    Ризик у грошах (R)   = Депозит × Ризик%
    Обсяг позиції        = ROUNDDOWN(R ÷ ΔStop, 0)
    Фактичний ризик      = Обсяг × ΔStop + Комісія
    Точка беззбитку      = ТВХ ± 2 × ΔStop
    Take Profit 1/2/3    = ТВХ ± (3/4/5) × ΔStop
    Прибуток на TP_i     = Обсяг × Частка_i × RR_i × ΔStop
    Фактичне R:R         = Сума прибутків ÷ Фактичний ризик
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import Dict, List, Optional

from bot.config import RiskSettings
from bot.models import Direction, OrderPlan


def _sign(direction: Direction) -> int:
    return 1 if direction == Direction.LONG else -1


@dataclass
class PositionMath:
    entry: float
    stop_loss: float
    stop_distance: float
    breakeven: float
    tp1: float
    tp2: float
    tp3: float
    qty: int
    risk_money: float
    actual_risk: float
    profit_tp1: float
    profit_tp2: float
    profit_tp3: float
    total_profit: float
    rr_actual: float
    rr_ok: bool

    def to_order(self, order_type: str, limit_price: Optional[float] = None) -> OrderPlan:
        return OrderPlan(
            order_type=order_type,
            entry=round(self.entry, 6),
            stop_loss=round(self.stop_loss, 6),
            take_profit_1=round(self.tp1, 6),
            take_profit_2=round(self.tp2, 6),
            take_profit_3=round(self.tp3, 6),
            qty=self.qty,
            limit_price=round(limit_price, 6) if limit_price is not None else None,
        )


def position_common(
    direction: Direction,
    entry: float,
    stop_distance: float,
    cfg: RiskSettings,
    commission: float = 0.0,
) -> PositionMath:
    """Спільна арифметика угоди — однакова для всіх 8 стратегій (розділ 6-8 кожної Стратегії_N)."""
    if stop_distance is None or stop_distance <= 0:
        raise ValueError("stop_distance має бути > 0 — інструмент/сетап пропускається")

    sign = _sign(direction)
    stop_loss = entry - sign * stop_distance
    risk_money = cfg.deposit * cfg.risk_per_trade_pct
    qty = floor(risk_money / stop_distance) if stop_distance > 0 else 0
    actual_risk = qty * stop_distance + commission
    breakeven = entry + sign * cfg.breakeven_at_r * stop_distance
    tp1 = entry + sign * cfg.rr_tp1 * stop_distance
    tp2 = entry + sign * cfg.rr_tp2 * stop_distance
    tp3 = entry + sign * cfg.rr_tp3 * stop_distance

    profit1 = qty * cfg.tp1_share * cfg.rr_tp1 * stop_distance
    profit2 = qty * cfg.tp2_share * cfg.rr_tp2 * stop_distance
    profit3 = qty * cfg.tp3_share * cfg.rr_tp3 * stop_distance
    total_profit = profit1 + profit2 + profit3
    rr_actual = (total_profit / actual_risk) if actual_risk > 0 else 0.0
    rr_ok = rr_actual >= cfg.rr_tp1

    return PositionMath(
        entry=entry,
        stop_loss=stop_loss,
        stop_distance=stop_distance,
        breakeven=breakeven,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        qty=qty,
        risk_money=risk_money,
        actual_risk=actual_risk,
        profit_tp1=profit1,
        profit_tp2=profit2,
        profit_tp3=profit3,
        total_profit=total_profit,
        rr_actual=rr_actual,
        rr_ok=rr_ok,
    )


# ---------------------------------------------------------------------------
# Стратегія 1 — ВІДБІЙ ВІД РІВНЯ (розділ 6 "Стратегії 1")
# ---------------------------------------------------------------------------
def bounce_position(
    level: float,
    technical_stop: float,
    direction: Direction,
    cfg: RiskSettings,
    commission: float = 0.0,
) -> PositionMath:
    """ТВХ = Рівень ± Люфт (Люфт = ΔStop × luft_pct_of_stop); ΔStop = technical_stop."""
    sign = _sign(direction)
    luft = technical_stop * cfg.luft_pct_of_stop
    entry = level + sign * luft
    return position_common(direction, entry, technical_stop, cfg, commission)


# ---------------------------------------------------------------------------
# Стратегія 2 — ПРОБІЙ РІВНЯ: чотири методи стопу (розділ 6 "Стратегії 2")
# ---------------------------------------------------------------------------
@dataclass
class BreakoutStopMethods:
    pct_of_price: Optional[float]
    points_min: float
    points_max: float
    atr_based: Optional[float]
    technical_manual: Optional[float]
    chosen: float
    chosen_method: str


def breakout_stop_methods(
    level: float,
    point_value: float,
    cfg: RiskSettings,
    atr_value: Optional[float] = None,
    technical_manual: Optional[float] = None,
    method: str = "auto",
) -> BreakoutStopMethods:
    pct_stop = level * cfg.breakout_stop_pct_of_price
    pts_min_stop = cfg.breakout_stop_points_min * point_value
    pts_max_stop = cfg.breakout_stop_points_max * point_value
    atr_stop = (atr_value * cfg.breakout_atr_multiplier) if atr_value else None

    candidates: Dict[str, float] = {
        "0,2% від ціни": pct_stop,
        "Пункти (мін)": pts_min_stop,
        "Пункти (макс)": pts_max_stop,
    }
    if atr_stop:
        candidates["ATR × мульт."] = atr_stop
    if technical_manual:
        candidates["Технічний (ручний)"] = technical_manual

    if method == "auto" or method not in candidates:
        chosen_method = min(candidates, key=candidates.get)
    else:
        chosen_method = method
    chosen = candidates[chosen_method]

    return BreakoutStopMethods(
        pct_of_price=pct_stop,
        points_min=pts_min_stop,
        points_max=pts_max_stop,
        atr_based=atr_stop,
        technical_manual=technical_manual,
        chosen=chosen,
        chosen_method=chosen_method,
    )


def breakout_position(
    level: float,
    direction: Direction,
    offset_points: float,
    point_value: float,
    cfg: RiskSettings,
    atr_value: Optional[float] = None,
    technical_manual: Optional[float] = None,
    stop_method: str = "auto",
    commission: float = 0.0,
) -> (PositionMath, BreakoutStopMethods):
    """ТВХ = Рівень ± Відступ(2-5 пунктів); ΔStop = MIN з чотирьох методів (розділ 7 "Стратегії 2")."""
    sign = _sign(direction)
    entry = level + sign * offset_points * point_value
    methods = breakout_stop_methods(level, point_value, cfg, atr_value, technical_manual, stop_method)
    pos = position_common(direction, entry, methods.chosen, cfg, commission)
    return pos, methods


# ---------------------------------------------------------------------------
# Стратегія 3 — ХИБНИЙ ПРОБІЙ: 3 сценарії, стоп за хвостом + 2 резервні методи
# (розділ 6-7 "Стратегії 3")
# ---------------------------------------------------------------------------
@dataclass
class FalseBreakoutStop:
    tail_plus_buffer: float
    reserve_pct: float
    reserve_points_min: float
    reserve_points_max: float
    chosen: float


def false_breakout_stop(
    level: float,
    tail_distance: float,
    point_value: float,
    cfg: RiskSettings,
) -> FalseBreakoutStop:
    tail_plus_buffer = tail_distance + cfg.false_breakout_buffer_points * point_value
    reserve_pct = level * cfg.breakout_stop_pct_of_price  # той самий орієнтир 0,2% від ціни
    reserve_min = cfg.breakout_stop_points_min * point_value
    reserve_max = cfg.breakout_stop_points_max * point_value
    chosen = min(tail_plus_buffer, reserve_pct, reserve_min, reserve_max)
    return FalseBreakoutStop(tail_plus_buffer, reserve_pct, reserve_min, reserve_max, chosen)


def false_breakout_position(
    level: float,
    direction: Direction,
    tail_distance: float,
    point_value: float,
    cfg: RiskSettings,
    commission: float = 0.0,
) -> (PositionMath, FalseBreakoutStop):
    """
    ТВХ = Рівень ± 1-2 пункти (відступ у бік розвороту);
    ΔStop = MIN(хвіст+буфер, 0.2%ціни, пункти мін, пункти макс) — розділ 7.1 "Стратегії 3".
    tail_distance визначається сценарієм (1: хвіст 1 бару; 2: хвіст найвищого/найнижчого
    з 2 барів; 3: хвіст найвищого/найнижчого серед усіх барів формації) — розраховується
    в bot/strategies/s3_false_breakout.py, тут лише фінальна арифметика.
    """
    sign = _sign(direction)
    entry = level + sign * cfg.false_breakout_offset_points * point_value
    stop = false_breakout_stop(level, tail_distance, point_value, cfg)
    pos = position_common(direction, entry, stop.chosen, cfg, commission)
    return pos, stop


# ---------------------------------------------------------------------------
# Стратегія 4 — РІЗКИЙ ІМПУЛЬС: Stop / Stop-Limit (розділ 6-7 "Стратегії 4")
# ---------------------------------------------------------------------------
def momentum_position(
    level: float,
    direction: Direction,
    offset_points: float,
    point_value: float,
    technical_stop: float,
    cfg: RiskSettings,
    use_stop_limit: bool = True,
    limit_buffer_points: float = 3.0,
    commission: float = 0.0,
) -> (PositionMath, Optional[float]):
    sign = _sign(direction)
    trigger = level + sign * offset_points * point_value
    pos = position_common(direction, trigger, technical_stop, cfg, commission)
    limit_price = None
    if use_stop_limit:
        limit_price = trigger + sign * limit_buffer_points * point_value
    return pos, limit_price


# ---------------------------------------------------------------------------
# Стратегія 5 — ТОРГІВЛЯ В КАНАЛІ (розділ 3-4-8 "Стратегії 5")
# ---------------------------------------------------------------------------
@dataclass
class ChannelCheck:
    width_stops: float
    room_up_stops: float
    room_down_stops: float
    width_ok: bool
    long_allowed: bool
    short_allowed: bool
    is_wide_channel: bool


def channel_check(
    upper: float,
    lower: float,
    current_price: float,
    technical_stop: float,
    cfg: RiskSettings,
) -> ChannelCheck:
    if technical_stop <= 0:
        raise ValueError("technical_stop має бути > 0")
    width_stops = (upper - lower) / technical_stop
    room_up = (upper - current_price) / technical_stop
    room_down = (current_price - lower) / technical_stop
    width_ok = width_stops >= cfg.channel_min_width_stops
    long_allowed = width_ok and room_up >= cfg.channel_min_room_stops
    short_allowed = width_ok and room_down >= cfg.channel_min_room_stops
    return ChannelCheck(
        width_stops=width_stops,
        room_up_stops=room_up,
        room_down_stops=room_down,
        width_ok=width_ok,
        long_allowed=long_allowed,
        short_allowed=short_allowed,
        is_wide_channel=width_stops >= cfg.channel_wide_threshold_stops,
    )


def channel_position(
    upper: float,
    lower: float,
    technical_stop: float,
    direction: Direction,
    cfg: RiskSettings,
    commission: float = 0.0,
) -> PositionMath:
    """LONG: ТВХ = Нижня межа + Люфт. SHORT: ТВХ = Верхня межа - Люфт (розділ 8 "Стратегії 5")."""
    luft = technical_stop * cfg.luft_pct_of_stop
    entry = (lower + luft) if direction == Direction.LONG else (upper - luft)
    return position_common(direction, entry, technical_stop, cfg, commission)


# ---------------------------------------------------------------------------
# Стратегія 6 — СХОДИНКИ: правило "двох стопів" (розділ 7 "Стратегії 6")
# ---------------------------------------------------------------------------
def staircase_position(
    trigger_price: float,
    prior_extreme_price: float,
    direction: Direction,
    cfg: RiskSettings,
    buffer_abs: float = 0.0,
    commission: float = 0.0,
) -> PositionMath:
    """
    ТВХ = trigger_price (попередній локальний хай/лоу, який зараз переписується).
    Stop = ПОПЕРЕДНІЙ (не останній) з двох підтверджених екстремумів ∓ буфер.
    """
    sign = _sign(direction)
    stop_price = prior_extreme_price - sign * buffer_abs
    stop_distance = abs(trigger_price - stop_price)
    return position_common(direction, trigger_price, stop_distance, cfg, commission)


def staircase_trailing_r(
    step_price: float,
    entry: float,
    stop_distance: float,
    direction: Direction,
) -> float:
    """Поточне значення R для нового кроку (аркуш 'Трейлінг-трекер')."""
    sign = _sign(direction)
    return sign * (step_price - entry) / stop_distance if stop_distance else 0.0


def staircase_trailing_stop(
    step_price: float,
    technical_stop: float,
    direction: Direction,
) -> float:
    """Новий рівень стопу після активації трейлінгу (>=3R) — крок мінус/плюс початковий ΔStop."""
    sign = _sign(direction)
    return step_price - sign * technical_stop


# ---------------------------------------------------------------------------
# Стратегія 7 — ПОГЛИНАННЯ (розділ 7 "Стратегії 7")
# ---------------------------------------------------------------------------
def engulfing_position(
    bar_high: float,
    bar_low: float,
    direction: Direction,
    offset_points: float,
    buffer_points: float,
    point_value: float,
    cfg: RiskSettings,
    commission: float = 0.0,
) -> PositionMath:
    offset = offset_points * point_value
    buffer = buffer_points * point_value
    if direction == Direction.LONG:
        entry = bar_high + offset
        stop_price = bar_low - buffer
    else:
        entry = bar_low - offset
        stop_price = bar_high + buffer
    stop_distance = abs(entry - stop_price)
    return position_common(direction, entry, stop_distance, cfg, commission)


def engulfing_signal_strength(bars_engulfed: int) -> str:
    if bars_engulfed < 3:
        return "Недостатньо барів"
    if bars_engulfed <= 3:
        return "Базовий (≈95%)"
    if bars_engulfed <= 5:
        return "Посилений"
    return "Дуже сильний"


# ---------------------------------------------------------------------------
# Авторська стратегія — КЛЮЧОВІ РІВНІ ДНЯ
# Формули ідентичні Стратегіям 1-3, застосовані до одного з п'яти рівнів
# (PDH/PDL/POC/1H-High/1H-Low) — розділ 10 "Авторської стратегії".
# Диспетчеризація відбувається в bot/strategies/s8_key_levels.py, який
# викликає bounce_position / breakout_position / false_breakout_position
# напряму з ціною обраного рівня.
# ---------------------------------------------------------------------------


def confluence_zones(
    levels: Dict[str, Optional[float]],
    technical_stop: float,
    threshold_stops: float,
) -> List[Dict]:
    """
    Детектор конфлюенсу (аркуш 'Карта рівнів', розділ 5.1 "Авторської стратегії").
    levels: {"PDH": 152.4, "PDL": 148.5, "POC": 150.2, "1H-High": None, "1H-Low": None}
    Повертає список пар рівнів, відстань між якими <= threshold_stops.
    """
    zones = []
    names = list(levels.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = levels[names[i]], levels[names[j]]
            if a is None or b is None or technical_stop <= 0:
                continue
            dist_stops = abs(a - b) / technical_stop
            if dist_stops <= threshold_stops:
                zones.append({
                    "pair": (names[i], names[j]),
                    "distance_abs": abs(a - b),
                    "distance_stops": dist_stops,
                })
    return zones
