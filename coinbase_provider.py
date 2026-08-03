"""
Провайдер даних для криптовалюти — Coinbase Exchange (публічний REST API,
без ключа для ринкових даних).

Примітка: раніше тут планувався Binance; за проханням користувача замінено на
Coinbase. Архітектура провайдерів (bot/data/base.py + aggregator.py) навмисно
розв'язана так, щоб пізніше додати bot/data/binance_provider.py чи
bot/data/bybit_provider.py як альтернативу чи доповнення — досить реалізувати
DataProvider і зареєструвати рядок "binance"/"bybit" в watchlist.yaml та
aggregator.py, решта коду (стратегії, калькулятор, сповіщення) не зміниться.

Документація: https://docs.cloud.coinbase.com/exchange/reference/exchangerestapi_getproductcandles
Ліміти: публічні ендпоінти — до 10 запитів/сек (з запасом достатньо для
опитування списку інструментів раз на 5 хв).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

import requests

from bot.data.base import DataProvider
from bot.models import Bar, Instrument

log = logging.getLogger(__name__)

BASE_URL = "https://api.exchange.coinbase.com"

_GRANULARITY_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}

# Coinbase Exchange повертає максимум 300 свічок за один запит.
_MAX_CANDLES_PER_REQUEST = 300


class CoinbaseProvider(DataProvider):
    name = "coinbase"

    def __init__(self, timeout_sec: float = 10.0, session: requests.Session = None):
        self.timeout_sec = timeout_sec
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "trading-signal-bot/1.0"})

    def get_bars(self, instrument: Instrument, interval: str, lookback: int) -> List[Bar]:
        granularity = _GRANULARITY_SECONDS.get(interval)
        if granularity is None:
            raise ValueError(f"Невідомий інтервал: {interval}")

        product_id = instrument.symbol  # напр. "BTC-USD"
        remaining = min(lookback, _MAX_CANDLES_PER_REQUEST * 5)  # запобіжник від надмірних запитів
        bars: List[Bar] = []
        end_time = None

        while remaining > 0:
            batch_size = min(remaining, _MAX_CANDLES_PER_REQUEST)
            params = {"granularity": granularity}
            if end_time is not None:
                # йдемо назад у часі: end = початок попереднього вже отриманого вікна
                params["end"] = end_time.isoformat()
                params["start"] = _shift(end_time, -batch_size * granularity).isoformat()

            url = f"{BASE_URL}/products/{product_id}/candles"
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout_sec)
                resp.raise_for_status()
                raw = resp.json()
            except requests.RequestException as e:
                log.warning("Coinbase API помилка для %s: %s", product_id, e)
                break
            except ValueError as e:
                log.warning("Coinbase API повернув невалідний JSON для %s: %s", product_id, e)
                break

            if not raw:
                break

            # Кожен рядок: [time, low, high, open, close, volume]; Coinbase повертає
            # у порядку спадання часу (найновіші перші) — приводимо до хронологічного.
            batch = [
                Bar(
                    ts=datetime.fromtimestamp(row[0], tz=timezone.utc),
                    open=float(row[3]),
                    high=float(row[2]),
                    low=float(row[1]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in raw
            ]
            batch.sort(key=lambda b: b.ts)
            bars = batch + bars
            remaining -= len(batch)
            if len(batch) < batch_size:
                break  # більше даних немає (напр. молодий лістинг монети)
            end_time = batch[0].ts

        # дедуплікація на випадок перекриття вікон запитів
        seen = set()
        unique_bars: List[Bar] = []
        for b in bars:
            if b.ts not in seen:
                seen.add(b.ts)
                unique_bars.append(b)
        unique_bars.sort(key=lambda b: b.ts)
        return unique_bars[-lookback:]

    def is_market_open(self, instrument: Instrument) -> bool:
        return True  # крипторинок торгується 24/7/365


def _shift(dt: datetime, seconds: float) -> datetime:
    from datetime import timedelta
    return dt + timedelta(seconds=seconds)
