"""
Розрахунок ATR — точно за методикою файлів "Калькулятор_*.xlsx" та розділу 3.4
"Торгового алгоритму трейдера":

    Розрахунковий ATR = середній розмір денного бару (High - Low) за останні
    5-14 днів, БЕЗ урахування аномальних ("паранормальних") барів.

    % пройденого денного ATR = (Хай дня - Лоу дня, наростаючим підсумком) / Розрахунковий ATR

    Висновок (як у стовпці "Висновок" калькулятора):
        >= 80%  -> "Рух вичерпано — обережно"
        >= 60%  -> "Більше половини ATR — уважно"
        інакше  -> "Запас ходу є"

В Excel виключення аномальних днів робиться вручну (стовпець "Врахувати? Так/Ні").
У боті це автоматизовано: день вважається аномальним, якщо його range суттєво
(за замовчуванням > 2.5x) перевищує медіану вибірки — це прибирає одноразові
гепи/новинні викиди зі середнього, як і задумано в методиці.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import List, Optional, Sequence

from bot.models import Bar


@dataclass
class AtrResult:
    atr_value: float
    days_used: int
    days_excluded: int
    pct_used_today: Optional[float]
    today_range: Optional[float]
    conclusion: str


def _day_ranges(daily_bars: Sequence[Bar]) -> List[float]:
    return [b.high - b.low for b in daily_bars if b.high is not None and b.low is not None]


def filter_anomalous_days(daily_bars: Sequence[Bar], multiplier: float = 2.5) -> List[Bar]:
    """Автоматичний аналог ручного перемикача 'Врахувати? Так/Ні' в Excel."""
    ranges = _day_ranges(daily_bars)
    if len(ranges) < 3:
        return list(daily_bars)
    m = median(ranges)
    if m <= 0:
        return list(daily_bars)
    return [b for b in daily_bars if (b.high - b.low) <= m * multiplier]


def calculated_atr(
    daily_bars: Sequence[Bar],
    lookback_days: int = 14,
    min_days: int = 5,
    anomaly_multiplier: float = 2.5,
) -> AtrResult:
    """
    daily_bars: денні бари в хронологічному порядку, ОСТАННІЙ елемент може бути
    поточним (ще не закритим) днем — його треба передавати ОКРЕМО через today_high/today_low
    у pct_used_today, а не включати в саму вибірку ATR.
    """
    history = list(daily_bars)[-lookback_days:]
    filtered = filter_anomalous_days(history, anomaly_multiplier)
    ranges = _day_ranges(filtered)

    if len(ranges) < min(min_days, len(history)) or not ranges:
        atr_value = 0.0
    else:
        atr_value = sum(ranges) / len(ranges)

    return AtrResult(
        atr_value=round(atr_value, 6),
        days_used=len(ranges),
        days_excluded=len(history) - len(ranges),
        pct_used_today=None,
        today_range=None,
        conclusion="—",
    )


def pct_of_atr_used_today(today_high: float, today_low: float, atr_value: float) -> AtrResult:
    today_range = None
    pct = None
    conclusion = "—"
    if today_high is not None and today_low is not None:
        today_range = max(0.0, today_high - today_low)
        if atr_value and atr_value > 0:
            pct = today_range / atr_value
            if pct >= 0.8:
                conclusion = "Рух вичерпано — обережно"
            elif pct >= 0.6:
                conclusion = "Більше половини ATR — уважно"
            else:
                conclusion = "Запас ходу є"
    return AtrResult(
        atr_value=atr_value,
        days_used=0,
        days_excluded=0,
        pct_used_today=pct,
        today_range=today_range,
        conclusion=conclusion,
    )


def full_atr_report(
    daily_bars_history: Sequence[Bar],
    today_high: float,
    today_low: float,
    lookback_days: int = 14,
    min_days: int = 5,
    anomaly_multiplier: float = 2.5,
) -> AtrResult:
    """Комбінований звіт: розрахунковий ATR + % пройденого сьогодні + висновок."""
    base = calculated_atr(daily_bars_history, lookback_days, min_days, anomaly_multiplier)
    today = pct_of_atr_used_today(today_high, today_low, base.atr_value)
    return AtrResult(
        atr_value=base.atr_value,
        days_used=base.days_used,
        days_excluded=base.days_excluded,
        pct_used_today=today.pct_used_today,
        today_range=today.today_range,
        conclusion=today.conclusion,
    )


def is_atr_exhausted(pct_used_today: Optional[float], threshold: float = 0.75) -> bool:
    """Загальне правило алгоритму (розділ 3.4): 75-80% ATR = рух статистично вичерпано."""
    if pct_used_today is None:
        return False
    return pct_used_today >= threshold
