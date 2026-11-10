from datetime import datetime, timedelta, timezone

import pytest

from forexbot.bot import Bot, parse_time
from forexbot.config import Config, ConfigError
from forexbot.strategy import Signal


class FakeClient:
    def __init__(self, candles, nav=500.0):
        self.candles_data = candles
        self.nav = nav
        self.orders = []
        self.trades = []
        self.closed = {}

    def account_summary(self):
        return {"id": "x", "NAV": str(self.nav), "balance": "500", "currency": "EUR", "unrealizedPL": "0"}

    def open_trades(self):
        return list(self.trades)

    def candles(self, inst, gran, count=None):
        return self.candles_data

    def pricing(self, instruments):
        return {i: {"bid": 1.1000, "ask": 1.1001, "tradeable": True} for i in instruments}

    def mid_price(self, name):
        return {"EUR_USD": 1.10005}.get(name)

    def instrument_info(self, inst):
        return {"displayPrecision": 5}

    def market_order(self, inst, units, sl, tp, precision):
        self.orders.append((inst, units, sl, tp))
        tid = str(len(self.orders))
        self.trades.append({"id": tid, "instrument": inst, "currentUnits": str(units), "price": "1.1", "unrealizedPL": "0"})
        return {"tradeOpened": {"tradeID": tid}}

    def trade(self, tid):
        return {"instrument": "EUR_USD", "realizedPL": self.closed.get(tid, "0")}

    def close_trade(self, tid):
        self.trades = [t for t in self.trades if t["id"] != tid]


class FakeTelegram:
    def __init__(self, commands=None):
        self.sent = []
        self.commands = commands or []

    def send(self, text):
        self.sent.append(text)
        return True

    def poll_commands(self):
        cmds, self.commands = self.commands, []
        return cmds


def make_bot(tmp_path, client, tg=None, now=None, **cfg_kw):
    cfg = Config(oanda_token="t", oanda_account_id="a", instruments=["EUR_USD"], data_dir=tmp_path, **cfg_kw)
    return Bot(cfg, client, tg or FakeTelegram(), now=now or (lambda: datetime(2025, 3, 3, 12, 5, tzinfo=timezone.utc)))


def test_parse_time():
    assert parse_time("2025-03-03T11:00:00.000000000Z") == datetime(2025, 3, 3, 11, tzinfo=timezone.utc)


def test_execute_places_order_with_sl_tp(tmp_path):
    client = FakeClient([])
    bot = make_bot(tmp_path, client)
    ok = bot.execute("EUR_USD", Signal("buy", 1.1, 0.0020, 0.0040, "test"), 500.0, "EUR")
    assert ok
    inst, units, sl, tp = client.orders[0]
    assert units > 0
    assert sl == pytest.approx(1.1001 - 0.0020)
    assert tp == pytest.approx(1.1001 + 0.0040)
    # rizik ~1% od 500 EUR
    assert units * 0.0020 / 1.10005 == pytest.approx(5.0, rel=0.01)


def test_execute_sell_negative_units(tmp_path):
    client = FakeClient([])
    bot = make_bot(tmp_path, client)
    bot.execute("EUR_USD", Signal("sell", 1.1, 0.0020, 0.0040, "test"), 500.0, "EUR")
    _, units, sl, tp = client.orders[0]
    assert units < 0 and sl > 1.1 > tp


def test_dry_run_does_not_order(tmp_path):
    client = FakeClient([])
    tg = FakeTelegram()
    bot = make_bot(tmp_path, client, tg, dry_run=True)
    assert bot.execute("EUR_USD", Signal("buy", 1.1, 0.002, 0.004, "t"), 500, "EUR")
    assert client.orders == []
    assert "DRY RUN" in tg.sent[0]


def test_wide_spread_skipped(tmp_path):
    client = FakeClient([])
    client.pricing = lambda ins: {i: {"bid": 1.1000, "ask": 1.1010, "tradeable": True} for i in ins}
    bot = make_bot(tmp_path, client)
    assert not bot.execute("EUR_USD", Signal("buy", 1.1, 0.002, 0.004, "t"), 500, "EUR")
    assert client.orders == []


def test_daily_loss_limit_blocks_trading(tmp_path, wave_candles):
    client = FakeClient(wave_candles, nav=500.0)
    tg = FakeTelegram()
    bot = make_bot(tmp_path, client, tg)
    bot.check_once()  # postavlja početak dana
    client.nav = 480.0  # -4% > 3% limit
    bot.check_once()
    assert bot.state.daily_limit_hit
    assert any("Dnevni limit" in m for m in tg.sent)


def test_stale_candles_ignored(tmp_path, wave_candles):
    # zadnja svijeća je od prije mnogo dana -> nema trgovanja
    client = FakeClient(wave_candles)
    bot = make_bot(tmp_path, client, now=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
    bot.check_once()
    assert client.orders == []


def test_signal_on_fresh_candle_trades_once(tmp_path, wave_candles):
    from forexbot.strategy import StrategyParams, compute_indicators, signal_at

    p = StrategyParams()
    ind = compute_indicators(wave_candles, p)
    idx = next(i for i in range(len(wave_candles)) if signal_at(wave_candles, ind, i, p))
    candles = wave_candles[: idx + 1]
    last = parse_time(candles[-1].time)
    client = FakeClient(candles)
    bot = make_bot(tmp_path, client, now=lambda: last + timedelta(hours=1, minutes=1))
    bot.check_once()
    bot.check_once()  # ista svijeća -> ne smije ponovno trgovati
    assert len(client.orders) == 1


def test_closed_trade_reported(tmp_path):
    client = FakeClient([])
    tg = FakeTelegram()
    bot = make_bot(tmp_path, client, tg)
    bot.execute("EUR_USD", Signal("buy", 1.1, 0.002, 0.004, "t"), 500, "EUR")
    client.closed["1"] = "9.80"
    client.trades = []
    bot.check_once()
    assert any("+9.80" in m for m in tg.sent)


def test_telegram_commands(tmp_path):
    client = FakeClient([])
    tg = FakeTelegram(["/pauza"])
    bot = make_bot(tmp_path, client, tg)
    bot.handle_commands()
    assert bot.state.paused
    tg.commands = ["/nastavi"]
    bot.handle_commands()
    assert not bot.state.paused
    tg.commands = ["/status"]
    bot.handle_commands()
    assert "Stanje" in tg.sent[-1]


def test_live_requires_confirmation(monkeypatch):
    monkeypatch.delenv("I_UNDERSTAND_REAL_MONEY", raising=False)
    with pytest.raises(ConfigError):
        Config(oanda_env="live").validate()
    monkeypatch.setenv("I_UNDERSTAND_REAL_MONEY", "da")
    Config(oanda_env="live").validate()
