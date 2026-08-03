"""
Провайдер даних для акцій, ф'ючерсів та форекс — yfinance (Yahoo Finance).

ЧЕСНЕ ЗАСТЕРЕЖЕННЯ (детальніше — README, розділ "Обмеження реального часу"):
yfinance — неофіційна, безкоштовна бібліотека без потреби в ключі. Дані по
акціях зазвичай надходять з невеликою затримкою (секунди-хвилини, не
гарантовано tick-level), а сам сервіс іноді змінює поведінку без попередження.
Для реальної торгівлі грошима розгляньте платний апгрейд (Alpaca, Polygon.io,
Interactive Brokers TWS API для акцій/ф'ючерсів; OANDA чи Twelve Data для
форекс) — просто реалізуйте новий клас DataProvider і підключіть його в
aggregator.py, решта бота не зміниться.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from bot.data.base import DataProvider
from bot.models import Bar, Instrument

log = logging.getLogger(__name__)

_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "1d": "1d",
}


def _period_for(interval: str, lookback: int) -> str:
    """Yahoo обмежує глибину історії залежно від інтервалу — беремо безпечний запас."""
    if interval == "1m":
        return "7d"
    if interval in ("5m", "15m", "1h"):
        return "60d"
    if interval == "1d":
        days_needed = max(lookback * 3, 90)
        if days_needed <= 90:
            return "3mo"
        if days_needed <= 180:
            return "6mo"
        if days_needed <= 365:
            return "1y"
        return "2y"
    return "1mo"


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def __init__(self):
        try:
            import yfinance  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "yfinance не встановлено. Виконайте: pip install yfinance"
            ) from e

    def get_bars(self, instrument: Instrument, interval: str, lookback: int) -> List[Bar]:
        import yfinance as yf

        yf_interval = _INTERVAL_MAP.get(interval)
        if yf_interval is None:
            raise ValueError(f"Невідомий інтервал: {interval}")
        period = _period_for(interval, lookback)

        try:
            ticker = yf.Ticker(instrument.symbol)
            df = ticker.history(period=period, interval=yf_interval, auto_adjust=False)
        except Exception as e:  # yfinance кидає різні типи винятків залежно від версії
            log.warning("yfinance помилка для %s: %s", instrument.symbol, e)
            return []

        if df is None or df.empty:
            return []

        bars: List[Bar] = []
        for ts, row in df.iterrows():
            if ts.tzinfo is None:
                ts = ts.tz_localize(timezone.utc)
            bars.append(Bar(
                ts=ts.to_pydatetime(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0) or 0.0),
            ))
        bars.sort(key=lambda b: b.ts)
        return bars[-lookback:]

    def is_market_open(self, instrument: Instrument) -> bool:
        from bot.session import is_open_now
        return is_open_now(instrument.asset_class)
