import pytest

from forexbot.indicators import atr, ema, rsi


def test_ema_constant_series():
    out = ema([2.0] * 10, 3)
    assert out[:2] == [None, None]
    assert all(v == pytest.approx(2.0) for v in out[2:])


def test_ema_known_values():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_too_short():
    assert ema([1, 2], 3) == [None, None]


def test_rsi_extremes():
    up = rsi(list(range(30)), 14)
    assert up[13] is None and up[14] == 100.0
    down = rsi(list(range(30, 0, -1)), 14)
    assert down[-1] == pytest.approx(0.0)
    flat = rsi([5.0] * 30, 14)
    assert flat[-1] == 50.0


def test_atr_constant_range():
    highs = [1.1] * 20
    lows = [1.0] * 20
    closes = [1.05] * 20
    out = atr(highs, lows, closes, 14)
    assert out[12] is None
    assert out[13] == pytest.approx(0.1)
    assert out[-1] == pytest.approx(0.1)
