"""Абстрактний інтерфейс постачальника ринкових даних."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from bot.models import Bar, Instrument


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_bars(self, instrument: Instrument, interval: str, lookback: int) -> List[Bar]:
        """
        interval: "1m" | "5m" | "15m" | "1h" | "1d"
        lookback: кількість барів, які потрібно повернути (від найстарішого до найновішого)
        Повертає список Bar у хронологічному порядку (останній елемент — найновіший,
        може бути ще не закритим баром поточного періоду — це нормально й навіть
        потрібно для polling "наростаючим підсумком" high/low сьогоднішнього дня).
        """
        raise NotImplementedError

    def is_market_open(self, instrument: Instrument) -> bool:
        """За замовчуванням вважаємо ринок відкритим; конкретні провайдери можуть перевизначити."""
        return True
