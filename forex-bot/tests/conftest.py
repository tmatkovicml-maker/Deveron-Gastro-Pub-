import random
from datetime import datetime, timedelta, timezone

import pytest

from forexbot.strategy import Candle


def make_candles(closes, start=datetime(2025, 1, 6, tzinfo=timezone.utc), step=3600, wiggle=0.0005):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        t = (start + timedelta(seconds=step * i)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
        o = prev
        out.append(Candle(t, o, max(o, c) + wiggle, min(o, c) - wiggle, c))
        prev = c
    return out


@pytest.fixture
def wave_candles():
    # determinističko nasumično kretanje cijene (random walk) -> realni crossoveri
    rng = random.Random(42)
    closes, price = [], 1.10
    for _ in range(3000):
        price += rng.gauss(0, 0.0012)
        closes.append(price)
    return make_candles(closes)
