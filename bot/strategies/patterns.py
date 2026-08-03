"""
Патерни на основі кількох барів, спільні для Стратегій 3, 6, 7.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from bot.models import Bar


# ---------------------------------------------------------------------------
# Стратегія 7 — Поглинання (розділ 2 "Стратегії 7")
# ---------------------------------------------------------------------------
@dataclass
class EngulfingResult:
    detected: bool
    kind: Optional[str] = None       # "bullish" | "bearish"
    bars_engulfed: int = 0
    engulf_high: Optional[float] = None
    engulf_low: Optional[float] = None


def detect_engulfing(bars: Sequence[Bar], min_bars: int = 3, max_check: int = 8) -> EngulfingResult:
    """
    Останній бар повністю перекриває (хай і лоу) щонайменше `min_bars` попередніх
    барів, і закривається за межами їхнього діапазону (вище хая для бичачого,
    нижче лоу для ведмежого) — розділ 2.1-2.2 "Стратегії 7".
    """
    if len(bars) < min_bars + 1:
        return EngulfingResult(detected=False)

    last = bars[-1]
    engulfed = 0
    for k in range(1, max_check + 1):
        if len(bars) < k + 1:
            break
        prior = bars[-1 - k:-1]
        if not prior:
            break
        prior_high = max(b.high for b in prior)
        prior_low = min(b.low for b in prior)
        if last.high >= prior_high and last.low <= prior_low:
            engulfed = k
        else:
            break

    if engulfed < min_bars:
        return EngulfingResult(detected=False)

    prior_window = bars[-1 - engulfed:-1]
    prior_high = max(b.high for b in prior_window)
    prior_low = min(b.low for b in prior_window)

    if last.close > prior_high and last.is_bullish:
        return EngulfingResult(True, "bullish", engulfed, last.high, last.low)
    if last.close < prior_low and not last.is_bullish:
        return EngulfingResult(True, "bearish", engulfed, last.high, last.low)
    return EngulfingResult(detected=False)


# ---------------------------------------------------------------------------
# Стратегія 3 — Хибний пробій: класифікація сценарію 1/2/3 (розділ 3 "Стратегії 3")
# ---------------------------------------------------------------------------
@dataclass
class FalseBreakoutState:
    stage: str            # "none" | "pierced" | "reversed_scenario1" | "reversed_scenario2" | "watching_scenario3"
    scenario: Optional[int] = None
    bars_beyond_level: int = 0
    tail_distance: Optional[float] = None   # відстань від рівня до найглибшого хвоста формації
    detail: str = ""


def detect_false_breakout(bars: Sequence[Bar], level_price: float, kind: str) -> FalseBreakoutState:
    """
    kind="support": пробій вниз, очікуємо розворот вгору (LONG).
    kind="resistance": пробій вгору, очікуємо розворот вниз (SHORT).

    Логіка (розділ 3 "Стратегії 3"):
      Сценарій 1 (1 бар)  — пробійний бар одразу закривається назад у вихідній площині.
      Сценарій 2 (2 бари) — пробійний бар закрився ЗА рівнем, другий бар підтверджує розворот.
      Сценарій 3 (3+ барів) — щонайменше два бари поспіль залишаються за рівнем,
                                останній підтверджує розворот.
    """
    if not bars:
        return FalseBreakoutState(stage="none")

    def beyond(bar: Bar) -> bool:
        return bar.low < level_price if kind == "support" else bar.high > level_price

    def closed_beyond(bar: Bar) -> bool:
        return bar.close < level_price if kind == "support" else bar.close > level_price

    def back_inside(bar: Bar) -> bool:
        return bar.close >= level_price if kind == "support" else bar.close <= level_price

    last = bars[-1]
    if not beyond(last) and len(bars) < 2:
        return FalseBreakoutState(stage="none")

    # рахуємо, скільки останніх барів поспіль перебувають "за рівнем"
    beyond_run = 0
    for b in reversed(bars):
        if beyond(b):
            beyond_run += 1
        else:
            break

    if beyond_run == 0:
        return FalseBreakoutState(stage="none")

    tails = [
        (level_price - b.low) if kind == "support" else (b.high - level_price)
        for b in bars[-beyond_run:]
    ]
    tail_distance = max(tails) if tails else None

    # Сценарій 1: єдиний пробійний бар вже закрився НАЗАД у вихідній площині
    if beyond_run == 1 and back_inside(last):
        return FalseBreakoutState(
            stage="reversed_scenario1", scenario=1, bars_beyond_level=1,
            tail_distance=tail_distance, detail="Простий ЛП (1 бар): розворот підтверджено",
        )

    # Пробійний бар ще "у грі" (закрився за рівнем або ще не закрився) — рання формація
    if beyond_run == 1 and closed_beyond(last):
        return FalseBreakoutState(
            stage="pierced", scenario=None, bars_beyond_level=1,
            tail_distance=tail_distance, detail="Рівень пробито, бар закрився за рівнем — стежимо за 2-м баром",
        )

    if beyond_run == 2 and back_inside(last):
        return FalseBreakoutState(
            stage="reversed_scenario2", scenario=2, bars_beyond_level=2,
            tail_distance=tail_distance, detail="Складний ЛП (2 бари): розворот підтверджено",
        )

    if beyond_run == 2 and closed_beyond(last):
        return FalseBreakoutState(
            stage="watching_scenario3", scenario=None, bars_beyond_level=2,
            tail_distance=tail_distance, detail="2 бари за рівнем — можливий перехід у Сценарій 3",
        )

    if beyond_run >= 3 and back_inside(last):
        return FalseBreakoutState(
            stage="reversed_scenario2", scenario=3, bars_beyond_level=beyond_run,
            tail_distance=tail_distance, detail=f"Складний ЛП ({beyond_run} барів): розворот підтверджено",
        )

    return FalseBreakoutState(
        stage="watching_scenario3", scenario=None, bars_beyond_level=beyond_run,
        tail_distance=tail_distance, detail=f"{beyond_run} барів поспіль за рівнем — спостерігаємо (Сценарій 3)",
    )


# ---------------------------------------------------------------------------
# Стратегія 6 — Сходинки (розділ 3-4 "Стратегії 6")
# ---------------------------------------------------------------------------
@dataclass
class StaircaseState:
    stage: str                # "none" | "one_step" | "two_steps_ready" | "signal"
    direction: Optional[str] = None   # "LONG" | "SHORT"
    key_point: Optional[float] = None      # попередній локальний хай(LONG)/лоу(SHORT) — рівень входу
    prior_extreme: Optional[float] = None  # ПОПЕРЕДНІЙ з двох підтверджених екстремумів — рівень стопу
    detail: str = ""


def detect_staircase(swing_lows: Sequence[float], swing_highs: Sequence[float], last_close: float) -> StaircaseState:
    """
    swing_lows / swing_highs: хронологічно впорядковані ціни підтверджених
    локальних мінімумів/максимумів робочого таймфрейму (найновіші в кінці).

    LONG ("висхідні низи"): >= 2 послідовно зростаючих лоу; сигнал — close вище
    попереднього хая. Стоп — за ПОПЕРЕДНІМ (не останнім) з двох лоу.
    SHORT ("нисхідна база") — дзеркально.
    """
    if len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2]:
        key_point = swing_highs[-1] if swing_highs else None
        prior_extreme = swing_lows[-2]
        if key_point is not None and last_close > key_point:
            return StaircaseState("signal", "LONG", key_point, prior_extreme,
                                   "Закриття вище попереднього хая після висхідних низів")
        return StaircaseState("two_steps_ready", "LONG", key_point, prior_extreme,
                               "Висхідні низи підтверджено, очікуємо пробій попереднього хая")

    if len(swing_highs) >= 2 and swing_highs[-1] < swing_highs[-2]:
        key_point = swing_lows[-1] if swing_lows else None
        prior_extreme = swing_highs[-2]
        if key_point is not None and last_close < key_point:
            return StaircaseState("signal", "SHORT", key_point, prior_extreme,
                                   "Закриття нижче попереднього лоу після нисхідної бази")
        return StaircaseState("two_steps_ready", "SHORT", key_point, prior_extreme,
                               "Нисхідна база підтверджена, очікуємо пробій попереднього лоу")

    return StaircaseState("none")
