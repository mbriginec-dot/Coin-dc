"""
Простий планувальник без зайвих залежностей: виконує Engine.run_once() кожні
N хвилин (за замовчуванням 5 — config/settings.yaml: scan.poll_interval_minutes),
намагаючись вирівнюватись по межі хвилини для передбачуваності логів.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone

from bot.engine import Engine

log = logging.getLogger(__name__)

_stop_requested = False


def _handle_stop(signum, frame):
    global _stop_requested
    log.info("Отримано сигнал зупинки (%s) — завершуємо після поточного циклу...", signum)
    _stop_requested = True


def run_forever(engine: Engine, interval_minutes: int = 5) -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    log.info("Планувальник запущено: сканування кожні %s хв. Ctrl+C для зупинки.", interval_minutes)
    interval_sec = interval_minutes * 60

    while not _stop_requested:
        cycle_start = time.monotonic()
        started_at = datetime.now(timezone.utc)
        try:
            sent = engine.run_once()
            log.info("Цикл сканування завершено (%s), надіслано повідомлень: %s", started_at.isoformat(), sent)
        except Exception:
            log.exception("Неочікувана помилка під час циклу сканування")

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(1.0, interval_sec - elapsed)
        # спимо короткими інтервалами, щоб швидко реагувати на Ctrl+C
        slept = 0.0
        while slept < sleep_for and not _stop_requested:
            step = min(1.0, sleep_for - slept)
            time.sleep(step)
            slept += step

    log.info("Бот зупинено.")
