"""
Реєстр провайдерів даних. Обирає конкретний DataProvider за полем
instrument.provider з config/watchlist.yaml.

Поточна конфігурація (за проханням користувача): крипта -> Coinbase,
акції/ф'ючерси/форекс -> yfinance. Binance/Bybit заплановані на майбутнє —
досить дописати клас-провайдер (bot/data/binance_provider.py за зразком
coinbase_provider.py) і додати один рядок у PROVIDERS нижче.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from bot.data.base import DataProvider
from bot.models import Bar, Instrument

log = logging.getLogger(__name__)


class DataAggregator:
    def __init__(self):
        self._providers: Dict[str, DataProvider] = {}

    def _get_provider(self, key: str) -> DataProvider:
        if key not in self._providers:
            self._providers[key] = self._build_provider(key)
        return self._providers[key]

    @staticmethod
    def _build_provider(key: str) -> DataProvider:
        if key == "coinbase":
            from bot.data.coinbase_provider import CoinbaseProvider
            return CoinbaseProvider()
        if key == "yfinance":
            from bot.data.yfinance_provider import YFinanceProvider
            return YFinanceProvider()
        if key == "binance":
            raise NotImplementedError(
                "Провайдер 'binance' ще не реалізований у цій версії — зараз крипта "
                "йде через 'coinbase' (bot/data/coinbase_provider.py). Щоб повернутись "
                "на Binance, додайте bot/data/binance_provider.py за тим самим зразком "
                "і зареєструйте його тут."
            )
        if key == "bybit":
            raise NotImplementedError(
                "Провайдер 'bybit' ще не реалізований у цій версії. Додайте "
                "bot/data/bybit_provider.py за зразком coinbase_provider.py і "
                "зареєструйте його тут."
            )
        raise ValueError(f"Невідомий провайдер даних: {key}")

    def get_bars(self, instrument: Instrument, interval: str, lookback: int) -> List[Bar]:
        provider = self._get_provider(instrument.provider)
        try:
            return provider.get_bars(instrument, interval, lookback)
        except Exception as e:
            log.error("Помилка отримання даних (%s, %s, %s): %s", instrument.symbol, interval, provider.name, e)
            return []

    def is_market_open(self, instrument: Instrument) -> bool:
        provider = self._get_provider(instrument.provider)
        return provider.is_market_open(instrument)
