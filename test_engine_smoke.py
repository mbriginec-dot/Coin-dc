"""
Інтеграційний "димовий" тест: прогонить увесь конвеєр (Engine -> Strategies ->
RiskCalculator -> Notifier) на синтетичних даних, без реальної мережі, щоб
перевірити, що всі модулі коректно стикуються між собою (типи, назви полів,
порядок аргументів), а не лише що формули самі по собі правильні.

Запуск: python tests/test_engine_smoke.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import load_config
from bot.data.aggregator import DataAggregator
from bot.engine import Engine
from bot.models import AssetClass, Bar, Instrument
from bot.notify.telegram import TelegramNotifier
from bot.state.store import StateStore


class FakeNotifier(TelegramNotifier):
    def __init__(self):
        super().__init__(bot_token="", chat_id="", enabled=False)
        self.sent_formations = []
        self.sent_signals = []

    def send_formation_alert(self, alert) -> bool:
        self.sent_formations.append(alert)
        return True

    def send_trade_signal(self, signal) -> bool:
        self.sent_signals.append(signal)
        return True


def make_daily_bars(n=40, base=100.0, support=95.0, resistance=110.0):
    bars = []
    start = datetime.now(timezone.utc) - timedelta(days=n)
    price = base
    for i in range(n):
        ts = start + timedelta(days=i)
        # тримаємо ціну в межах [support, resistance], з дотиками до support кілька разів
        if i % 7 == 0:
            low = support
            high = support + 3
            close = support + 1.5
            open_ = support + 2
        else:
            low = base - 2
            high = base + 2
            close = base
            open_ = base
        bars.append(Bar(ts=ts, open=open_, high=high, low=low, close=close, volume=100000))
    return bars


def make_bounce_working_bars(level=95.0, n_context=30):
    """Формує БСУ -> БПУ1 -> БПУ2 біля рівня підтримки 95.0, робочий ТФ 5хв.
    Ціна тримається близько до рівня протягом усього "сьогодні", щоб денний
    діапазон не перевищував ATR і не спрацював фільтр "рух вичерпано"."""
    bars = []
    start = datetime.now(timezone.utc).replace(hour=14, minute=30, second=0, microsecond=0) - timedelta(minutes=5 * (n_context + 3))
    price = 96.0
    for i in range(n_context):
        ts = start + timedelta(minutes=5 * i)
        bars.append(Bar(ts=ts, open=price, high=price + 0.3, low=price - 0.3, close=price, volume=1000))
        price -= 0.01  # дуже повільно сповзаємо до рівня

    ts = start + timedelta(minutes=5 * n_context)
    # БСУ: перший СПРАВЖНІЙ дотик рівня (low близько до 95.0), закриття НЕ монотонно
    # наближається в наступних барах, щоб коректно уникнути фільтра "поджаття"
    bars.append(Bar(ts=ts, open=95.6, high=95.7, low=95.10, close=95.45, volume=1500))
    # БПУ1: не пробиває, закриття ближче до рівня, ніж у БСУ
    ts2 = ts + timedelta(minutes=5)
    bars.append(Bar(ts=ts2, open=95.45, high=95.5, low=95.15, close=95.20, volume=1400))
    # БПУ2: не пробиває, закриття ДАЛІ від рівня, ніж у БПУ1 (не поджаття, "вирівнюючий" бар)
    ts3 = ts2 + timedelta(minutes=5)
    bars.append(Bar(ts=ts3, open=95.20, high=95.65, low=95.12, close=95.50, volume=1600))
    return bars


class FakeDataAggregator(DataAggregator):
    def __init__(self, daily_bars, working_bars):
        super().__init__()
        self._daily = daily_bars
        self._working = working_bars

    def get_bars(self, instrument, interval, lookback):
        if interval == "1d":
            return self._daily[-lookback:]
        if interval == "5m":
            return self._working[-lookback:]
        if interval == "1h":
            return []  # спрощено для смоук-тесту
        return []

    def is_market_open(self, instrument) -> bool:
        return True


def run_smoke_test():
    config = load_config()
    # Обмежуємось одним інструментом для передбачуваності тесту
    test_instrument = Instrument(
        symbol="TEST", display_name="Test Instrument", asset_class=AssetClass.CRYPTO,
        provider="coinbase", point_value=0.01,
    )
    config.instruments = [test_instrument]

    daily = make_daily_bars()
    working = make_bounce_working_bars()

    data = FakeDataAggregator(daily, working)
    notifier = FakeNotifier()
    state = StateStore(Path("/tmp/test_state.json"))
    # чистий стан для відтворюваності
    state._data = {"formations": {}, "signals": {}, "staircase_trailing": {}}

    engine = Engine(config, data, notifier, state)
    sent = engine.run_once()

    print(f"Подій надіслано: {sent}")
    print(f"Формацій: {len(notifier.sent_formations)}, Сигналів: {len(notifier.sent_signals)}")

    for f in notifier.sent_formations:
        print(f"  [FORMATION] {f.strategy.value} | {f.instrument.symbol} | {f.stage}")
    for s in notifier.sent_signals:
        print(f"  [SIGNAL] {s.strategy.value} | {s.instrument.symbol} | {s.direction.value} | "
              f"entry={s.order.entry:.4f} stop={s.order.stop_loss:.4f} tp1={s.order.take_profit_1:.4f} "
              f"qty={s.order.qty} rr={s.rr_actual:.2f}")

    assert sent >= 0  # рушій відпрацював без винятків — головна мета цього тесту
    print("\nOK: engine ran end-to-end without exceptions")


if __name__ == "__main__":
    run_smoke_test()
