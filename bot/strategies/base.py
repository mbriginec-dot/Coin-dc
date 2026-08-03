"""Базовий інтерфейс стратегії та контекст сканування, спільний для всіх 8 стратегій."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union

from bot.config import AppConfig
from bot.indicators.atr import AtrResult
from bot.models import Bar, Instrument, Level


@dataclass
class StrategyContext:
    instrument: Instrument
    now: datetime
    daily_bars: List[Bar]         # історія денних барів (включно з учорашнім, БЕЗ поточного, що ще формується)
    today_bar: Optional[Bar]      # поточний (ще не закритий) денний бар — high/low наростаючим підсумком
    working_bars: List[Bar]       # робочий ТФ для точки входу (типово 5-хв бари)
    hourly_bars: List[Bar]        # годинний ТФ (для 1H-High/1H-Low та підтвердження рівнів)
    weekly_bars: List[Bar]        # тижневий ТФ (для оцінки сили рівня — збіг таймфреймів)
    levels: List[Level]           # рівні, побудовані на денному ТФ (bot/strategies/levels.py)
    atr: AtrResult
    cfg: AppConfig
    commission: float = 0.0
    session_open_minutes_ago: Optional[float] = None   # скільки хвилин минуло від відкриття сесії (акції/ф'ючерси)
    global_trend: str = "flat"    # "up" | "down" | "flat" — старший ТФ (розділ 3.3 алгоритму), лише м'яке попередження


class Strategy:
    """Абстрактний інтерфейс. Кожна конкретна стратегія повертає список подій:
    FormationAlert (раннє попередження) та/або TradeSignal (готовий сигнал)."""

    id: str = "base"
    name: str = "Base"

    def scan(self, ctx: StrategyContext) -> List[Union["FormationAlert", "TradeSignal"]]:
        raise NotImplementedError
