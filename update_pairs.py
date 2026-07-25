"""
Оновлює pairs.json списком топ-N пар з Coinbase за обсягом торгів (24h volume),
відфільтрованих за валютою котирування (за замовчуванням USDC).

Запуск вручну, коли захочеш освіжити список:
    python update_pairs.py

Це НЕ запускається автоматично при кожному скані — pairs.json є "джерелом правди",
яке ти контролюєш сам. Скрипт лише допомагає швидко його перегенерувати.
"""
import json
import ccxt
import config


def get_top_pairs_by_volume(quote: str = None, top_n: int = 20) -> list[str]:
    quote = quote or config.QUOTE_CURRENCY
    exchange = ccxt.coinbase({"enableRateLimit": True})

    markets = exchange.load_markets()
    tickers = exchange.fetch_tickers()

    candidates = []
    for symbol, market in markets.items():
        if not market.get("active", True):
            continue
        if market.get("quote") != quote:
            continue
        if market.get("type") != "spot":
            continue
        ticker = tickers.get(symbol)
        if not ticker or ticker.get("quoteVolume") is None:
            continue
        candidates.append((symbol, ticker["quoteVolume"]))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [symbol for symbol, _ in candidates[:top_n]]


def main():
    top_pairs = get_top_pairs_by_volume()

    if not top_pairs:
        print("Не вдалося отримати пари. Перевір з'єднання або налаштування ccxt.")
        return

    data = {
        "_comment": "Список пар для сканування. Формат: 'BASE/QUOTE', наприклад 'BTC/USDC'. "
                    "Можеш вручну додавати/видаляти пари. Щоб перегенерувати список топ-N за "
                    "обсягом торгів з Coinbase, запусти: python update_pairs.py",
        "pairs": top_pairs,
    }

    with open("pairs.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"pairs.json оновлено. Знайдено {len(top_pairs)} пар:")
    for p in top_pairs:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
