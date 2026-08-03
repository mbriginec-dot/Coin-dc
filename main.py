#!/usr/bin/env python3
"""
Точка входу. Приклади запуску:

    python main.py                  # запустити нескінченний цикл (кожні 5 хв, за замовчуванням)
    python main.py --once           # виконати ОДИН прохід сканування і вийти (зручно для cron/Task Scheduler)
    python main.py --test-telegram  # надіслати тестове повідомлення й перевірити налаштування .env
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot.config import DATA_DIR, load_config
from bot.data.aggregator import DataAggregator
from bot.engine import Engine
from bot.notify.telegram import TelegramNotifier
from bot.state.store import StateStore


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(DATA_DIR / "bot.log", encoding="utf-8"),
        ],
    )


def build_engine() -> Engine:
    config = load_config()
    data = DataAggregator()
    notifier = TelegramNotifier(config.telegram.bot_token, config.telegram.chat_id, config.telegram.enabled)
    state = StateStore(DATA_DIR / "state.json")
    return Engine(config, data, notifier, state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Торговий сигнальний бот (рівнева торгівля)")
    parser.add_argument("--once", action="store_true", help="Виконати один прохід сканування і вийти")
    parser.add_argument("--test-telegram", action="store_true", help="Надіслати тестове повідомлення в Telegram")
    parser.add_argument("--interval", type=int, default=None, help="Перевизначити інтервал сканування (хв)")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()
    log = logging.getLogger("main")

    engine = build_engine()

    if args.test_telegram:
        ok = engine.notifier.send_text("✅ Тестове повідомлення: бот налаштовано правильно.")
        log.info("Тестове повідомлення %s", "надіслано" if ok else "НЕ надіслано — перевірте .env (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return

    if args.once:
        sent = engine.run_once()
        log.info("Готово. Надіслано повідомлень: %s", sent)
        return

    from bot.scheduler import run_forever
    interval = args.interval or engine.config.scan.poll_interval_minutes
    run_forever(engine, interval_minutes=interval)


if __name__ == "__main__":
    main()
