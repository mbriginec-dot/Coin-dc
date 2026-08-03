"""
Тести саме на ті прогалини, які були знайдені й виправлені під час аудиту:
  - сила рівня (score_strength) раніше завжди повертала 0, бо жоден з
    бонус-факторів ніколи не передавався з engine.py;
  - Value Area (VAH/VAL) для Стратегії 8 не рахувалась взагалі.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.models import Bar, Level
from bot.strategies import levels as lv
from bot.strategies.s8_key_levels import compute_poc_and_value_area


def _daily(n, high_low_pairs):
    start = datetime.now(timezone.utc) - timedelta(days=n)
    bars = []
    for i, (h, l) in enumerate(high_low_pairs):
        ts = start + timedelta(days=i)
        bars.append(Bar(ts=ts, open=(h + l) / 2, high=h, low=l, close=(h + l) / 2, volume=1000))
    return bars


def test_score_strength_extremum_and_timeframe_confluence():
    daily = _daily(20, [(105, 100)] * 15 + [(101, 95)] * 5)  # мінімум 95 наприкінці — екстремум
    level = Level(price=95.0, kind="support", source="swing", timeframe="1d")

    is_ext = lv.is_built_on_extremum(level, daily, window=20)
    assert is_ext is True, "рівень = мінімум вибірки має розпізнаватись як екстремум"

    weekly_level = Level(price=95.05, kind="support", source="swing", timeframe="1w")
    score = lv.score_strength(level, higher_tf_levels=[weekly_level], is_extremum=is_ext, merge_tolerance_pct=0.01)
    assert score == 2, f"очікували +1 за збіг ТФ і +1 за екстремум, отримали {score}"
    assert any("екстремум" in n for n in level.notes)
    assert any("збіг ТФ" in n for n in level.notes)
    print("OK: test_score_strength_extremum_and_timeframe_confluence")


def test_false_breakout_history_count():
    # 3 дні, коли low пробив 100 (рівень підтримки), але close повернувся вище
    daily = _daily(10, [
        (105, 100.5), (104, 99.0), (103, 100.2),  # день 2 (idx1): пробій+повернення
        (106, 99.5), (105, 100.3),                 # день 4 (idx3): пробій+повернення
        (107, 101), (108, 102), (109, 103),
        (110, 99.2), (111, 100.5),                  # день 9 (idx8): пробій+повернення
    ])
    level = Level(price=100.0, kind="support", source="swing", timeframe="1d")
    count = lv.count_false_breakout_history(daily, level)
    assert count == 3, f"очікували 3 хибні пробої в історії, отримали {count}"
    print("OK: test_false_breakout_history_count")


def test_weekly_aggregation():
    daily = _daily(14, [(100 + i, 95 + i) for i in range(14)])
    weekly = lv.aggregate_to_weekly(daily)
    assert len(weekly) <= 3 and len(weekly) >= 1
    total_daily_volume = sum(b.volume for b in daily)
    total_weekly_volume = sum(b.volume for b in weekly)
    assert abs(total_daily_volume - total_weekly_volume) < 1e-6
    print("OK: test_weekly_aggregation")


def test_unusual_volume():
    start = datetime.now(timezone.utc)
    bars = [Bar(ts=start + timedelta(minutes=5 * i), open=100, high=101, low=99, close=100, volume=1000) for i in range(10)]
    spike = Bar(ts=start + timedelta(minutes=50), open=100, high=101, low=99, close=100, volume=3000)
    assert lv.is_unusual_volume(spike, bars, multiplier=2.0) is True
    normal = Bar(ts=start + timedelta(minutes=50), open=100, high=101, low=99, close=100, volume=1100)
    assert lv.is_unusual_volume(normal, bars, multiplier=2.0) is False
    print("OK: test_unusual_volume")


def test_value_area_contains_poc_and_is_within_range():
    start = datetime.now(timezone.utc)
    bars = []
    # більшість обсягу зосереджена навколо 100, менше на краях 95 і 105
    for i, price in enumerate([100] * 20 + [98] * 5 + [102] * 5 + [95] * 2 + [105] * 2):
        bars.append(Bar(ts=start + timedelta(minutes=5 * i), open=price, high=price + 0.1, low=price - 0.1, close=price, volume=500))
    poc, vah, val = compute_poc_and_value_area(bars, value_area_pct=0.70)
    assert poc is not None and vah is not None and val is not None
    assert val <= poc <= vah, f"POC має бути всередині [VAL, VAH]: val={val}, poc={poc}, vah={vah}"
    assert vah <= 105.5 and val >= 94.5, "VAH/VAL не повинні виходити за межі реального діапазону цін"
    print("OK: test_value_area_contains_poc_and_is_within_range")


def test_trend_direction():
    start = datetime.now(timezone.utc)
    up_bars = [Bar(ts=start + timedelta(days=i), open=100 + i, high=101 + i, low=99 + i, close=100 + i, volume=100) for i in range(15)]
    assert lv.trend_direction(up_bars, lookback=10) == "up"

    down_bars = [Bar(ts=start + timedelta(days=i), open=100 - i, high=101 - i, low=99 - i, close=100 - i, volume=100) for i in range(15)]
    assert lv.trend_direction(down_bars, lookback=10) == "down"
    print("OK: test_trend_direction")


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {t.__name__} -> {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR: {t.__name__} -> {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_all()
