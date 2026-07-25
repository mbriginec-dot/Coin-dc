"""
Головний скрипт бота. Для кожної пари з pairs.json:
1. Тягне денні свічки -> шукає рівні (levels.py).
2. Тягне 15m свічки -> перевіряє радар (наближення) та 3 патерни (strategy.py).
3. Шле відповідні сповіщення в Telegram, з урахуванням стану (ретести) з state.json.

Запуск разово (для GitHub Actions): python main.py
Запуск циклом (для локального тесту): python main.py --loop
"""
import sys
import time
import traceback

import config
import data_fetcher
import indicators
import levels as levels_module
import strategy
import state as state_module
import telegram_notifier


def process_pair(exchange, symbol: str, bot_state: dict):
    print(f"\n--- {symbol} ---")

    df_level = data_fetcher.fetch_ohlcv(exchange, symbol, config.LEVEL_TIMEFRAME, config.LEVEL_CANDLES_LIMIT)
    found_levels = levels_module.find_levels(df_level)
    print(f"Знайдено рівнів: {len(found_levels)}")

    if not found_levels:
        return

    df_signal = data_fetcher.fetch_ohlcv(exchange, symbol, config.SIGNAL_TIMEFRAME, config.SIGNAL_CANDLES_LIMIT)
    df_signal = indicators.add_rsi(df_signal)
    ticker = data_fetcher.fetch_ticker(exchange, symbol)

    current_price = df_signal["close"].iloc[-1]
    rsi = df_signal["rsi"].iloc[-1]
    price_change_24h = indicators.price_change_24h_pct(ticker)
    volume_change_pct = indicators.volume_vs_average_pct(df_signal)

    # --- Оновлюємо стан "відійшла/не відійшла" для всіх рівнів ---
    for level in found_levels:
        state_module.update_state_for_level(bot_state, symbol, level["price"], current_price)

    # --- 1. Перевірка підтверджених сигналів (3 патерни) по кожному сильному рівню ---
    for level in found_levels:
        signal = strategy.check_all_patterns(df_signal, level)
        if signal:
            print(f"СИГНАЛ: {signal['pattern']} / {signal['direction']} на рівні {level['price']}")
            msg = telegram_notifier.format_signal_message(symbol, signal, rsi, volume_change_pct)
            telegram_notifier.send_telegram_message(msg)

    # --- 2. Радар: наближення до сильних рівнів ---
    radar_candidates = strategy.find_radar_candidates(current_price, found_levels)
    for candidate in radar_candidates:
        level = candidate["level"]
        if state_module.should_send_radar_alert(bot_state, symbol, level["price"]):
            print(f"РАДАР: наближення до рівня {level['price']} ({candidate['distance_pct']:.2f}%)")
            msg = telegram_notifier.format_radar_message(
                symbol, current_price, level, candidate["side"],
                candidate["distance_pct"], rsi, price_change_24h
            )
            sent = telegram_notifier.send_telegram_message(msg)
            if sent:
                state_module.mark_radar_alert_sent(bot_state, symbol, level["price"])


def run_scan():
    exchange = data_fetcher.get_exchange()
    pairs = config.load_pairs()
    bot_state = state_module.load_state()

    print(f"Сканування {len(pairs)} пар...")

    for symbol in pairs:
        try:
            process_pair(exchange, symbol, bot_state)
        except Exception as e:
            print(f"[{symbol}] Помилка: {e}")
            traceback.print_exc()

    state_module.save_state(bot_state)
    print("\nСканування завершено. Стан збережено.")


def main():
    if "--loop" in sys.argv:
        print("Запуск у циклі (Ctrl+C для зупинки)...")
        while True:
            run_scan()
            print(f"Очікування {config.CHECK_INTERVAL_SECONDS} сек...\n")
            time.sleep(config.CHECK_INTERVAL_SECONDS)
    else:
        run_scan()


if __name__ == "__main__":
    main()
