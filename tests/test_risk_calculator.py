"""
Юніт-тести: перевіряють bot/risk/calculator.py проти ЧИСЛОВИХ ПРИКЛАДІВ,
наведених безпосередньо в документах Стратегія_1..7.docx (розділи "Приклад
розрахунку"). Якщо ці тести проходять — формули бота ідентичні формулам
у ваших Excel-калькуляторах.

Запуск:  python -m pytest tests/test_risk_calculator.py -v
     або: python tests/test_risk_calculator.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import RiskSettings
from bot.models import Direction
from bot.risk import calculator as calc


def make_cfg(**overrides) -> RiskSettings:
    cfg = RiskSettings(deposit=10000.0, risk_per_trade_pct=0.005)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def approx(a, b, tol=0.011):
    return abs(a - b) <= tol


def test_bounce_strategy1_long_example():
    """Стратегія 1, розділ 6.4: Рівень=50.00, стоп=0.35, люфт=20% -> ТВХ=50.07 ..."""
    cfg = make_cfg(luft_pct_of_stop=0.20)
    pos = calc.bounce_position(level=50.00, technical_stop=0.35, direction=Direction.LONG, cfg=cfg)
    assert approx(pos.entry, 50.07), pos.entry
    assert approx(pos.stop_loss, 49.72), pos.stop_loss
    assert pos.qty == 142, pos.qty
    assert approx(pos.tp1, 51.12), pos.tp1
    assert approx(pos.tp2, 51.47), pos.tp2
    assert approx(pos.tp3, 51.82), pos.tp3
    assert approx(pos.breakeven, 50.77), pos.breakeven
    print("OK: test_bounce_strategy1_long_example")


def test_breakout_strategy2_long_example():
    """Стратегія 2, розділ 7.3: Рівень=50.00, відступ=3п, ATR->0.12 (atr_value=0.4*0.3=0.12) -> обрано 0.10 (0.2%)."""
    cfg = make_cfg(
        breakout_stop_pct_of_price=0.002,
        breakout_stop_points_min=15,
        breakout_stop_points_max=25,
        breakout_atr_multiplier=0.3,
    )
    pos, methods = calc.breakout_position(
        level=50.00,
        direction=Direction.LONG,
        offset_points=3,
        point_value=0.01,
        cfg=cfg,
        atr_value=0.4,  # -> atr_stop = 0.4*0.3 = 0.12
    )
    assert approx(methods.pct_of_price, 0.10)
    assert approx(methods.points_min, 0.15)
    assert approx(methods.atr_based, 0.12)
    assert approx(methods.chosen, 0.10), methods.chosen  # мінімум з чотирьох
    assert approx(pos.entry, 50.03), pos.entry
    assert approx(pos.stop_loss, 49.93), pos.stop_loss
    assert pos.qty == 500, pos.qty
    assert approx(pos.tp1, 50.33), pos.tp1
    assert approx(pos.tp2, 50.43), pos.tp2
    assert approx(pos.tp3, 50.53), pos.tp3
    assert approx(pos.breakeven, 50.23), pos.breakeven
    print("OK: test_breakout_strategy2_long_example")


def test_false_breakout_strategy3_matches_excel_min_formula():
    """
    Стратегія 3, розділ 7.3: текстовий приклад у Word-документі (ΔStop=0.47, 106 акцій)
    НЕ узгоджується з формулою в самому Excel-файлі (яка бере MIN() по чотирьох
    кандидатах і в цьому прикладі обрала б 0.10, а не 0.47). Бот реалізує САМЕ
    формулу з Excel (джерело істини), тому цей тест звіряється з нею, а не з
    текстовим прикладом. Деталі — README, розділ "Відомі розбіжності".
    """
    cfg = make_cfg(
        false_breakout_offset_points=2,
        false_breakout_buffer_points=2,
        breakout_stop_pct_of_price=0.002,
        breakout_stop_points_min=15,
        breakout_stop_points_max=25,
    )
    pos, stop = calc.false_breakout_position(
        level=50.00,
        direction=Direction.LONG,
        tail_distance=0.45,   # відстань від рівня до хвоста (50.00 - 49.55)
        point_value=0.01,
        cfg=cfg,
    )
    assert approx(stop.tail_plus_buffer, 0.47), stop.tail_plus_buffer
    assert approx(stop.reserve_pct, 0.10), stop.reserve_pct
    assert approx(stop.chosen, 0.10), stop.chosen  # MIN(0.47, 0.10, 0.15, 0.25) = 0.10 за формулою Excel
    assert approx(pos.entry, 50.02), pos.entry
    print("OK: test_false_breakout_strategy3_matches_excel_min_formula")


def test_momentum_strategy4_long_example():
    """Стратегія 4, розділ 7.3: Рівень=35.00, відступ=0.03, стоп=0.18, ліміт-буфер=0.03."""
    cfg = make_cfg()
    pos, limit_price = calc.momentum_position(
        level=35.00,
        direction=Direction.LONG,
        offset_points=3,
        point_value=0.01,
        technical_stop=0.18,
        cfg=cfg,
        use_stop_limit=True,
        limit_buffer_points=3,
    )
    assert approx(pos.entry, 35.03), pos.entry
    assert approx(limit_price, 35.06), limit_price
    assert approx(pos.stop_loss, 34.85), pos.stop_loss
    assert pos.qty == 277, pos.qty
    assert approx(pos.tp1, 35.57), pos.tp1
    assert approx(pos.breakeven, 35.39), pos.breakeven
    print("OK: test_momentum_strategy4_long_example")


def test_channel_strategy5_long_example():
    """Стратегія 5, розділ 8.3: межі 50-55, стоп=0.40, ціна=50.15 (біля нижньої межі)."""
    cfg = make_cfg(luft_pct_of_stop=0.20, channel_min_width_stops=6.0, channel_min_room_stops=4.0)
    check = calc.channel_check(upper=55.00, lower=50.00, current_price=50.15, technical_stop=0.40, cfg=cfg)
    assert approx(check.width_stops, 12.5), check.width_stops
    assert approx(check.room_up_stops, 12.125, tol=0.02), check.room_up_stops
    assert check.long_allowed is True
    pos = calc.channel_position(upper=55.00, lower=50.00, technical_stop=0.40, direction=Direction.LONG, cfg=cfg)
    assert approx(pos.entry, 50.08), pos.entry
    assert approx(pos.stop_loss, 49.68), pos.stop_loss
    assert pos.qty == 125, pos.qty
    assert approx(pos.tp1, 51.28), pos.tp1
    print("OK: test_channel_strategy5_long_example")


def test_engulfing_strategy7_long_example():
    """Стратегія 7, розділ 7.3: хай=42.80, лоу=41.20, відступ=буфер=3п."""
    cfg = make_cfg()
    pos = calc.engulfing_position(
        bar_high=42.80,
        bar_low=41.20,
        direction=Direction.LONG,
        offset_points=3,
        buffer_points=3,
        point_value=0.01,
        cfg=cfg,
    )
    assert approx(pos.entry, 42.83), pos.entry
    assert approx(pos.stop_loss, 41.17), pos.stop_loss
    assert approx(pos.stop_distance, 1.66), pos.stop_distance
    assert pos.qty == 30, pos.qty
    assert approx(pos.tp1, 47.81), pos.tp1
    assert approx(pos.breakeven, 46.15), pos.breakeven
    print("OK: test_engulfing_strategy7_long_example")


def test_short_direction_is_mirror_of_long():
    """Формули для SHORT — дзеркальна копія LONG (усі документи наголошують на цьому явно)."""
    cfg = make_cfg()
    long_pos = calc.bounce_position(level=50.00, technical_stop=0.35, direction=Direction.LONG, cfg=cfg)
    short_pos = calc.bounce_position(level=50.00, technical_stop=0.35, direction=Direction.SHORT, cfg=cfg)
    assert approx(long_pos.entry - 50.00, 50.00 - short_pos.entry)
    assert approx(long_pos.stop_distance, short_pos.stop_distance)
    assert long_pos.qty == short_pos.qty
    print("OK: test_short_direction_is_mirror_of_long")


def test_confluence_detector():
    """Ключові рівні дня, розділ 5.1: поріг конфлюенсу 1 стоп."""
    levels = {"PDH": 152.4, "PDL": 148.5, "POC": 150.2, "1H-High": None, "1H-Low": None}
    zones = calc.confluence_zones(levels, technical_stop=0.35, threshold_stops=1.0)
    # PDH-PDL: |152.4-148.5|/0.35 = 11.1 -> ні;  PDH-POC: |152.4-150.2|/0.35=6.3 -> ні; PDL-POC: |148.5-150.2|/0.35=4.86 -> ні
    assert zones == [], zones

    levels2 = {"PDH": 152.40, "PDL": 148.5, "POC": 152.10, "1H-High": None, "1H-Low": None}
    zones2 = calc.confluence_zones(levels2, technical_stop=0.35, threshold_stops=1.0)
    assert len(zones2) == 1 and zones2[0]["pair"] == ("PDH", "POC")
    print("OK: test_confluence_detector")


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
