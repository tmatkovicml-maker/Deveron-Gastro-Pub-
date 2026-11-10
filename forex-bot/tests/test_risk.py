import pytest

from forexbot.risk import conversion_rate, pip_size, position_units, split_pair


def test_pip_size():
    assert pip_size("EUR_USD") == 0.0001
    assert pip_size("USD_JPY") == 0.01


def test_split_pair():
    assert split_pair("GBP_USD") == ("GBP", "USD")


def test_conversion_rate():
    prices = {"EUR_USD": 1.10, "EUR_JPY": 160.0}
    mid = prices.get
    assert conversion_rate("EUR", "EUR", mid) == 1.0
    assert conversion_rate("USD", "EUR", mid) == pytest.approx(1 / 1.10)
    assert conversion_rate("JPY", "EUR", mid) == pytest.approx(1 / 160.0)
    assert conversion_rate("XYZ", "EUR", mid) is None


def test_position_units_risk_based():
    # 500 EUR, 1% = 5 EUR rizika, SL 20 pipa na EUR_USD, 1 USD = 0.909 EUR
    units = position_units(500, 0.01, 0.0020, 1 / 1.10, 1.0, 30, 0.5)
    assert units == 2750
    loss = units * 0.0020 / 1.10
    assert loss == pytest.approx(5.0, rel=0.01)


def test_position_units_margin_cap():
    # mali SL bi tražio ogromnu poziciju -> margina je ograničava
    units = position_units(500, 0.01, 0.00001, 1.0, 1.0, 30, 0.5)
    assert units == 7500  # 500 * 0.5 * 30


def test_position_units_invalid():
    assert position_units(0, 0.01, 0.002, 1, 1, 30, 0.5) == 0
    assert position_units(500, 0.01, 0, 1, 1, 30, 0.5) == 0
