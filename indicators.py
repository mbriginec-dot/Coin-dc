"""
Допоміжні індикатори, які додають контекст до сповіщень (не є основою стратегії —
основа стратегії це рівні, див. levels.py та strategy.py).
"""
import pandas as pd
from ta.momentum import RSIIndicator
import config


def add_rsi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = RSIIndicator(close=df["close"], window=config.RSI_PERIOD).rsi()
    return df


def avg_volume(df: pd.DataFrame, lookback: int = 20) -> float:
    """Середній обсяг за останні lookback свічок (без останньої, щоб порівняти з нею)."""
    return df["volume"].iloc[-(lookback + 1):-1].mean()


def volume_vs_average_pct(df: pd.DataFrame, lookback: int = 20) -> float:
    """На скільки % обсяг останньої свічки відхиляється від середнього."""
    avg = avg_volume(df, lookback)
    if not avg or pd.isna(avg):
        return 0.0
    last = df["volume"].iloc[-1]
    return ((last - avg) / avg) * 100


def price_change_24h_pct(ticker: dict) -> float:
    """Зміна ціни за 24г з тікера біржі."""
    return ticker.get("percentage") or 0.0
