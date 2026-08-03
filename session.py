"""
Торгові сесії (розділ 10 "Торгового алгоритму трейдера" — акції/ф'ючерси;
розділ 3 "Торгового алгоритму: Форекс" — сесії форекс).

ОБМЕЖЕННЯ: враховано лише регулярні години сесії за днями тижня, БЕЗ
календаря біржових свят США — у святкові дні бот вважатиме сесію відкритою.
Для продакшн-використання додайте перевірку свят (напр. пакет `pandas_market_calendars`).
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from bot.models import AssetClass

NY_TZ = ZoneInfo("America/New_York")

US_MARKET_OPEN = time(9, 30)
US_MARKET_CLOSE = time(16, 0)


def is_open_now(asset_class: AssetClass, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)

    if asset_class == AssetClass.CRYPTO:
        return True  # 24/7/365 (розділ 2.1 "Торгового алгоритму: Криптовалюти")

    if asset_class == AssetClass.FOREX:
        now_utc = now.astimezone(timezone.utc)
        weekday = now_utc.weekday()  # Mon=0 ... Sun=6
        # Форекс закритий приблизно з 22:00 UTC п'ятниці до 22:00 UTC неділі (розділ 11.2 "Торгового алгоритму: Форекс")
        if weekday == 5:  # субота
            return False
        if weekday == 4 and now_utc.time() >= time(22, 0):  # п'ятниця після 22:00
            return False
        if weekday == 6 and now_utc.time() < time(22, 0):  # неділя до 22:00
            return False
        return True

    # STOCK / FUTURES: використовуємо регулярну сесію NYSE/NASDAQ як орієнтир навіть
    # для ф'ючерсів (котрі формально торгуються майже 24 год — але формації цього
    # алгоритму (перша година, ATR дня) прив'язані саме до регулярної сесії акцій).
    now_ny = now.astimezone(NY_TZ)
    if now_ny.weekday() >= 5:
        return False
    return US_MARKET_OPEN <= now_ny.time() <= US_MARKET_CLOSE


def is_forex_dead_zone(now: Optional[datetime] = None) -> bool:
    """"Мертва зона" 21:00-22:00 UTC — мінімальна ліквідність (розділ 3.3 "Торгового алгоритму: Форекс")."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return time(21, 0) <= now_utc.time() < time(22, 0)


def minutes_since_session_open(asset_class: AssetClass, now: Optional[datetime] = None) -> Optional[float]:
    """Повертає хвилини від відкриття поточної сесії; None, якщо ринок закритий або клас активу не має "відкриття" (крипто)."""
    now = now or datetime.now(timezone.utc)

    if asset_class == AssetClass.CRYPTO:
        return None  # немає поняття "відкриття сесії" — розділ 11 "Торгового алгоритму: Криптовалюти"

    if asset_class == AssetClass.FOREX:
        if not is_open_now(asset_class, now):
            return None
        # для форекс орієнтуємось на відкриття Лондона (08:00 UTC) як умовний "початок активного дня"
        now_utc = now.astimezone(timezone.utc)
        london_open = now_utc.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_utc < london_open:
            return None
        return (now_utc - london_open).total_seconds() / 60.0

    if not is_open_now(asset_class, now):
        return None
    now_ny = now.astimezone(NY_TZ)
    open_dt = now_ny.replace(hour=US_MARKET_OPEN.hour, minute=US_MARKET_OPEN.minute, second=0, microsecond=0)
    return (now_ny - open_dt).total_seconds() / 60.0
