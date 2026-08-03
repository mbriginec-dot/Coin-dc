"""
Побудова рівнів і оцінка їхньої сили (розділ 4 "Торгового алгоритму трейдера").

Ручне проведення рівнів трейдером тут наближено алгоритмічно: фрактальні
локальні екстремуми на денному/тижневому графіку (swing highs/lows) —
це стандартний, об'єктивний спосіб знайти "БСУ" (перший дотик, що потенційно
формує рівень) без суб'єктивного втручання людини. Підтвердження (БПУ1/БПУ2)
шукаються вже на робочому таймфреймі під час сканування.

Для вищої точності передбачено config/levels_override.yaml — ручні рівні,
які трейдер вважає найсильнішими (розділ 4.3), отримують пріоритет.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import List, Optional, Sequence

from bot.models import Bar, Level


# ---------------------------------------------------------------------------
# Фрактальні swing-точки та побудова рівнів
# ---------------------------------------------------------------------------
@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" | "low"


def find_swing_points(bars: Sequence[Bar], lookback: int = 3) -> List[SwingPoint]:
    """Бар є swing-high/low, якщо його High/Low екстремальніший за `lookback` барів з обох боків."""
    points: List[SwingPoint] = []
    n = len(bars)
    for i in range(lookback, n - lookback):
        window = bars[i - lookback:i + lookback + 1]
        if bars[i].high == max(b.high for b in window):
            points.append(SwingPoint(index=i, price=bars[i].high, kind="high"))
        if bars[i].low == min(b.low for b in window):
            points.append(SwingPoint(index=i, price=bars[i].low, kind="low"))
    return points


def build_levels(
    bars: Sequence[Bar],
    timeframe: str,
    lookback: int = 3,
    merge_tolerance_pct: float = 0.001,
    max_levels: int = 12,
) -> List[Level]:
    """
    Групує swing-точки в рівні (розділ 4.2, п.1: "Рівні завжди проводимо зліва
    направо... права частина графіка повинна підтвердити наявність рівня").
    Рівні з кількома дотиками (touches >= 2) вважаються підтвердженими.
    """
    swings = find_swing_points(bars, lookback)
    levels: List[Level] = []

    for sp in swings:
        kind = "resistance" if sp.kind == "high" else "support"
        merged = False
        for lvl in levels:
            if lvl.kind != kind:
                continue
            if abs(lvl.price - sp.price) / max(lvl.price, 1e-9) <= merge_tolerance_pct:
                # зливаємо: усереднюємо ціну, збільшуємо кількість дотиків
                lvl.price = (lvl.price * lvl.touches + sp.price) / (lvl.touches + 1)
                lvl.touches += 1
                merged = True
                break
        if not merged:
            levels.append(Level(price=sp.price, kind=kind, source="swing", timeframe=timeframe, touches=1))

    # дзеркальність: рівень, що зустрічається і як підтримка, і як опір близько до тієї ж ціни
    for a in levels:
        for b in levels:
            if a is b or a.kind == b.kind:
                continue
            if abs(a.price - b.price) / max(a.price, 1e-9) <= merge_tolerance_pct * 3:
                if "дзеркальний" not in a.notes:
                    a.notes.append("дзеркальний")

    levels.sort(key=lambda l: l.touches, reverse=True)
    return levels[:max_levels]


def score_strength(
    level: Level,
    higher_tf_levels: Optional[Sequence[Level]] = None,
    channel_bounds: Optional[Sequence[float]] = None,
    false_breakout_count: int = 0,
    is_extremum: bool = False,
    merge_tolerance_pct: float = 0.003,
) -> int:
    """
    Рахує кількість "плюсів" до сили рівня (розділ 4.3 алгоритму, розділ 2.3 Стратегії 1):
      +1 — збіг таймфреймів (старший ТФ підтверджує той самий рівень)
      +1 — рівень побудований точно по екстремуму
      +1 — рівень дзеркальний (вже "notes" містить позначку з build_levels)
      +1 — на рівні раніше вже фіксувались хибні пробої
      +1 — рівень збігається з межею каналу

    Знайдені фактори додатково записуються в level.notes людською мовою — це
    саме те, що бачить трейдер у Telegram-повідомленні як "чому цей рівень
    сильний", а не просто число.
    """
    score = 0
    if higher_tf_levels:
        for hl in higher_tf_levels:
            if abs(hl.price - level.price) / max(level.price, 1e-9) <= merge_tolerance_pct:
                score += 1
                if "збіг ТФ" not in level.notes:
                    level.notes.append(f"збіг ТФ ({hl.timeframe})")
                break
    if is_extremum:
        score += 1
        if "екстремум" not in level.notes:
            level.notes.append("побудований по екстремуму")
    if "дзеркальний" in level.notes:
        score += 1
    if false_breakout_count > 0:
        score += 1
        note = f"історія хибних пробоїв ({false_breakout_count})"
        if note not in level.notes:
            level.notes.append(note)
    if channel_bounds:
        for cb in channel_bounds:
            if abs(cb - level.price) / max(level.price, 1e-9) <= merge_tolerance_pct:
                score += 1
                if "межа каналу" not in level.notes:
                    level.notes.append("межа каналу")
                break
    return score


# ---------------------------------------------------------------------------
# Допоміжні функції для повноцінного розрахунку сили рівня (розділ 4.3) —
# раніше викликались без жодного реального аргументу, тому сила рівня завжди
# виходила 0. Тепер engine.py викликає їх і передає результат у score_strength().
# ---------------------------------------------------------------------------
def aggregate_to_weekly(daily_bars: Sequence[Bar]) -> List[Bar]:
    """Тижневі бари для перевірки 'збігу таймфреймів' (розділ 4.3) — без окремого
    провайдера даних: групуємо денні бари за ISO-тижнем."""
    if not daily_bars:
        return []
    weeks: dict = {}
    order: List[tuple] = []
    for b in daily_bars:
        key = b.ts.isocalendar()[:2]  # (рік, номер тижня)
        if key not in weeks:
            weeks[key] = []
            order.append(key)
        weeks[key].append(b)
    result = []
    for key in order:
        bucket = weeks[key]
        result.append(Bar(
            ts=bucket[0].ts,
            open=bucket[0].open,
            high=max(b.high for b in bucket),
            low=min(b.low for b in bucket),
            close=bucket[-1].close,
            volume=sum(b.volume for b in bucket),
        ))
    return result


def is_built_on_extremum(level: Level, daily_bars: Sequence[Bar], window: int = 60, tolerance_pct: float = 0.002) -> bool:
    """Рівень 'побудований точно по екстремуму' (розділ 4.3), якщо він збігається
    з мінімумом/максимумом останніх `window` денних барів."""
    if not daily_bars:
        return False
    recent = daily_bars[-window:]
    extreme = max(b.high for b in recent) if level.kind == "resistance" else min(b.low for b in recent)
    return abs(level.price - extreme) / max(level.price, 1e-9) <= tolerance_pct


def count_false_breakout_history(daily_bars: Sequence[Bar], level: Level, tolerance_pct: float = 0.0015) -> int:
    """Скільки разів у минулому денний бар пробив рівень хвостом, але ЗАКРИВСЯ
    назад у вихідній площині — це і є 'історія хибних пробоїв на цьому рівні'
    (розділ 4.3 алгоритму, розділ 2.3 Стратегії 1)."""
    if not daily_bars:
        return 0
    tol = level.price * tolerance_pct
    count = 0
    for b in daily_bars:
        if level.kind == "support":
            pierced = b.low < level.price - tol
            closed_back = b.close >= level.price
        else:
            pierced = b.high > level.price + tol
            closed_back = b.close <= level.price
        if pierced and closed_back:
            count += 1
    return count


def is_unusual_volume(bar: Bar, recent_bars: Sequence[Bar], multiplier: float = 2.0) -> bool:
    """"Unusual Volume" (розділ 4.5 алгоритму): сплеск обсягу у 2+ рази вище
    середнього — непряма ознака великого гравця. Волюм — допоміжний фактор
    (~5% ваги рішення), не замінює аналіз рівнів, але вартий згадки в сигналі."""
    others = [b.volume for b in recent_bars if b is not bar and b.volume]
    if len(others) < 5:
        return False
    avg = sum(others) / len(others)
    return avg > 0 and bar.volume >= avg * multiplier


def trend_direction(bars: Sequence[Bar], lookback: int = 10) -> str:
    """Дуже спрощений глобальний тренд (розділ 3.3 алгоритму): порівняння
    поточного закриття із закриттям `lookback` барів тому. Використовується
    лише як М'ЯКЕ попередження (не блокує угоду) при розбіжності з локальним
    напрямком, як і зазначено в документі ('в ідеалі — не суперечать')."""
    if len(bars) < lookback + 1:
        return "flat"
    change = bars[-1].close - bars[-1 - lookback].close
    threshold = bars[-1].close * 0.003
    if change > threshold:
        return "up"
    if change < -threshold:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# Аномальні ("паранормальні") бари
# ---------------------------------------------------------------------------
def is_paranormal_bar(bar: Bar, recent_bars: Sequence[Bar], multiplier: float = 2.5) -> bool:
    """Бар вважається аномальним, якщо його range суттєво перевищує медіану останніх барів."""
    ranges = [b.range for b in recent_bars if b is not bar]
    if len(ranges) < 5:
        return False
    m = median(ranges)
    return m > 0 and bar.range > m * multiplier


# ---------------------------------------------------------------------------
# Поджаття (компресія перед рівнем) — розділ 4.4 алгоритму / розділ 8 Стратегії 1
# ---------------------------------------------------------------------------
def detect_compression(bars: Sequence[Bar], level_price: float, kind: str, n: int = 3) -> bool:
    """
    kind="resistance": послідовне зростання close, що наближається до рівня знизу.
    kind="support": послідовне спадання close, що наближається до рівня зверху.
    Використовуються САМЕ ціни закриття (не хаї/лоу) — розділ 4.4.
    """
    if len(bars) < n:
        return False
    last_n = bars[-n:]
    distances = [abs(level_price - b.close) for b in last_n]
    return all(distances[i] > distances[i + 1] for i in range(len(distances) - 1))


def detect_leveling_bar(bars: Sequence[Bar], level_price: float) -> bool:
    """"Вирівнюючий" бар — закривається ДАЛІ від рівня, ніж попередній (кінець поджаття)."""
    if len(bars) < 2:
        return False
    prev, last = bars[-2], bars[-1]
    return abs(level_price - last.close) > abs(level_price - prev.close)


# ---------------------------------------------------------------------------
# Акумуляція перед пробоєм — розділ 3 Стратегії 2
# ---------------------------------------------------------------------------
def detect_accumulation(bars: Sequence[Bar], level_price: float, n: int = 5, max_range_ratio: float = 0.6) -> bool:
    """
    Серія малих барів (тіло+тіні) у вузькому діапазоні, що тиснуться до рівня.
    max_range_ratio: середній range останніх n барів має бути <= max_range_ratio
    від середнього range попередніх n барів (звуження діапазону).
    """
    if len(bars) < n * 2:
        return False
    recent = bars[-n:]
    prior = bars[-2 * n:-n]
    recent_avg_range = sum(b.range for b in recent) / n
    prior_avg_range = sum(b.range for b in prior) / n
    if prior_avg_range <= 0:
        return False
    narrowing = recent_avg_range <= prior_avg_range * max_range_ratio
    pressing = detect_compression(bars, level_price, kind="any", n=min(n, len(bars)))
    return narrowing or pressing


# ---------------------------------------------------------------------------
# БСУ → БПУ1 → БПУ2 — розділ 3 Стратегії 1
# ---------------------------------------------------------------------------
@dataclass
class BounceFormationState:
    stage: str          # "none" | "bsu" | "bsu_bpu1" | "ready_bpu2" | "broken"
    bsu_index: Optional[int] = None
    bpu1_index: Optional[int] = None
    bpu2_index: Optional[int] = None
    detail: str = ""


def detect_bsu_bpu_sequence(
    bars: Sequence[Bar],
    level_price: float,
    kind: str,               # "support" | "resistance"
    touch_tolerance: float,  # абсолютна $ відстань, у межах якої дотик рахується "до рівня"
    luft: float,
) -> BounceFormationState:
    """
    Шукає БСУ (перший дотик рівня) -> БПУ1 (підтвердження) -> БПУ2 (друге
    підтвердження одразу за БПУ1, без проколу рівня за межі люфту) — розділ 3
    "Стратегії 1". Для автоматичного сканування трактуємо це як вікно з останніх
    up-to-3 барів (документ допускає проміжні бари саме між БСУ і БПУ1, але не
    між БПУ1 і БПУ2 — спрощення тут навмисне: беремо НАЙСВІЖІШУ можливу
    трибарну послідовність, що не суперечить методиці для сигналів у реальному часі).

    Повертає стан ФОРМАЦІЇ: "bsu" -> щойно з'явився перший дотик (раннє попередження),
    "bsu_bpu1" -> два бари підтвердили рівень, чекаємо БПУ2 (попередження),
    "ready_bpu2" -> послідовність завершена без проколу (сигнал на вхід),
    "broken" -> рівень пробитий за межі люфту (це вже інша модель).
    """
    if len(bars) < 2:
        return BounceFormationState(stage="none")

    def pierce_amount(bar: Bar) -> float:
        """>0 — бар зайшов ЗА рівень (для support: low нижче рівня; для resistance: high вище рівня)."""
        return (level_price - bar.low) if kind == "support" else (bar.high - level_price)

    def near_level(bar: Bar) -> bool:
        return abs(pierce_amount(bar)) <= touch_tolerance or 0 < pierce_amount(bar) <= touch_tolerance

    def pierced_beyond_luft(bar: Bar) -> bool:
        return pierce_amount(bar) > luft

    last = bars[-1]
    prev = bars[-2]
    prev2 = bars[-3] if len(bars) >= 3 else None

    if pierced_beyond_luft(last):
        return BounceFormationState(stage="broken", detail="Останній бар пробив рівень за межі люфту")

    # БСУ(prev2) -> БПУ1(prev) -> БПУ2(last): повна послідовність, сигнал готовий
    if prev2 is not None and near_level(prev2) and not pierced_beyond_luft(prev):
        return BounceFormationState(
            stage="ready_bpu2", bsu_index=len(bars) - 3, bpu1_index=len(bars) - 2, bpu2_index=len(bars) - 1,
            detail="БСУ+БПУ1+БПУ2 підтверджено без проколу рівня — сигнал на вхід",
        )

    # БСУ(prev) -> БПУ1(last): формація в процесі, БПУ2 ще не з'явився
    if near_level(prev):
        return BounceFormationState(
            stage="bsu_bpu1", bsu_index=len(bars) - 2, bpu1_index=len(bars) - 1,
            detail="БСУ+БПУ1 сформовано, очікуємо БПУ2 без проколу рівня",
        )

    # Лише БСУ(last) щойно з'явився
    if near_level(last):
        return BounceFormationState(stage="bsu", bsu_index=len(bars) - 1, detail="БСУ щойно сформовано, очікуємо БПУ1")

    return BounceFormationState(stage="none")
