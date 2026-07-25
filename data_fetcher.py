"""
Отримання свічок (OHLCV) з Coinbase через ccxt.
Публічні ринкові дані не потребують API ключів.
"""
import ccxt
import pandas as pd


def get_exchange():
    """Підключення до Coinbase (публічні дані, без ключів)."""
    return ccxt.coinbase({"enableRateLimit": True})


def fetch_ohlcv(exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Тягне свічки для символу (наприклад 'BTC/USDC') і повертає DataFrame
    з колонками: timestamp, open, high, low, close, volume.
    """
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_ticker(exchange, symbol: str) -> dict:
    """Поточна ціна та статистика за 24г для символу."""
    return exchange.fetch_ticker(symbol)
