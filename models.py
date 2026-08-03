"""
Базові моделі даних для торгового бота.

Ці структури використовуються у всіх модулях: постачальники даних (bot/data),
стратегії (bot/strategies), калькулятор ризику (bot/risk) та сповіщення (bot/notify).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class AssetClass(str, Enum):
    STOCK = "stock"          # акції NYSE/NASDAQ
    FUTURES = "futures"      # ф'ючерси CME
    CRYPTO = "crypto"        # криптовалюта (спот/перпетуальні ф'ючерси)
    FOREX = "forex"          # валютні пари


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class StrategyId(str, Enum):
    S1_BOUNCE = "s1_bounce"                    # Стратегія 1. Відбій від рівня
    S2_BREAKOUT = "s2_breakout"                # Стратегія 2. Пробій рівня
    S3_FALSE_BREAKOUT = "s3_false_breakout"    # Стратегія 3. Хибний пробій
    S4_MOMENTUM = "s4_momentum"                # Стратегія 4. Різкий імпульс
    S5_CHANNEL = "s5_channel"                  # Стратегія 5. Торгівля в каналі
    S6_STAIRCASE = "s6_staircase"              # Стратегія 6. Сходинки
    S7_ENGULFING = "s7_engulfing"              # Стратегія 7. Поглинання
    S8_KEY_LEVELS = "s8_key_levels"            # Авторська стратегія. Ключові рівні дня


STRATEGY_NAMES_UA: Dict[str, str] = {
    StrategyId.S1_BOUNCE: "Відбій від рівня",
    StrategyId.S2_BREAKOUT: "Пробій рівня",
    StrategyId.S3_FALSE_BREAKOUT: "Хибний пробій",
    StrategyId.S4_MOMENTUM: "Різкий імпульс",
    StrategyId.S5_CHANNEL: "Торгівля в каналі",
    StrategyId.S6_STAIRCASE: "Сходинки",
    StrategyId.S7_ENGULFING: "Поглинання",
    StrategyId.S8_KEY_LEVELS: "Ключові рівні дня",
}


@dataclass
class Instrument:
    symbol: str                 # тикер у нотації провайдера даних, напр. "AAPL", "BTCUSDT", "EURUSD=X", "ES=F"
    display_name: str           # ім'я для повідомлень, напр. "Apple Inc. (AAPL)"
    asset_class: AssetClass
    provider: str                # ключ провайдера даних: "binance", "yfinance", "twelvedata", "alpaca"
    point_value: float = 0.01    # розмір "пункту" у $ (розділ 3.3 Стратегії 2): 0.01 для акцій, тік для ф'ючерсів, pip для форекс
    tick_size: Optional[float] = None
    enabled_strategies: Optional[List[str]] = None  # якщо None — всі стратегії застосовні


@dataclass
class Bar:
    """Один бар (свічка) OHLCV."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass
class Level:
    """
    Ціновий рівень (розділ 4 «Торгового алгоритму трейдера»).

    kind: "support" | "resistance"
    source: як рівень отримано — "swing" (автоматичний фрактал), "pdh", "pdl", "poc",
            "1h_high", "1h_low", "manual" (заданий користувачем у config/levels_override.yaml)
    strength: кількість факторів сили (розділ 4.3): збіг ТФ, побудова по екстремуму,
              дзеркальність, історія хибних пробоїв, межа каналу. 0 = базовий (щойно виявлений).
    """
    price: float
    kind: str
    source: str
    timeframe: str
    strength: int = 0
    touches: int = 1
    notes: List[str] = field(default_factory=list)


@dataclass
class FormationAlert:
    """
    Раннє попередження: формація ще не завершена, але почала складатися.
    Надсилається ОДРАЗУ, як тільки з'явились перші ознаки (БСУ+БПУ1, акумуляція,
    пробитий рівень в очікуванні розвороту, перший крок «сходинок» тощо).
    """
    instrument: Instrument
    strategy: StrategyId
    direction: Optional[Direction]
    level_price: float
    level_kind: str
    stage: str            # людський опис стадії, напр. "БСУ+БПУ1 сформовано, очікуємо БПУ2"
    detail: str
    ts: datetime
    current_price: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderPlan:
    order_type: str        # "Buy Limit" / "Sell Limit" / "Buy Stop" / "Sell Stop" / "Buy Stop-Limit" / "Sell Stop-Limit"
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    qty: float
    limit_price: Optional[float] = None   # тільки для Stop-Limit (Стратегія 4)


@dataclass
class TradeSignal:
    """Підтверджений торговий сигнал з повним розрахунком (готовий до виставлення)."""
    instrument: Instrument
    strategy: StrategyId
    direction: Direction
    scenario: Optional[str]     # напр. для Хибного пробою: "Сценарій 1 (простий, 1 бар)"
    level_price: float
    level_kind: str
    level_strength: int
    order: OrderPlan
    delta_stop: float
    risk_money: float
    rr_actual: float
    atr_value: float
    atr_used_pct_today: float
    commission: float
    ts: datetime
    current_price: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
