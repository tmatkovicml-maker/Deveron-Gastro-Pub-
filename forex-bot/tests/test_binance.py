import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest

from forexbot.backtest import run_backtest
from forexbot.binance import BinanceClient, BinanceError, fmt_decimal
from forexbot.bot import parse_time
from forexbot.config import Config
from forexbot.risk import floor_to_step, spot_quantity
from forexbot.spot_bot import SpotBot
from forexbot.strategy import Signal, StrategyParams, compute_indicators, signal_at


# ------------------------------------------------------------ helpers
def test_fmt_decimal_and_floor():
    assert fmt_decimal(0.123456789, 0.00001) == "0.12345"
    assert fmt_decimal(42000.567, 0.01) == "42000.56"
    assert fmt_decimal(3.0, 1.0) == "3"
    assert floor_to_step(0.0019999, 0.0001) == pytest.approx(0.0019)


def test_spot_quantity_risk_and_cap():
    # 500 EUR, 1% = 5 EUR rizika, BTC 50000, SL 1000 -> ~0.0048 BTC (uz proviziju)
    q = spot_quantity(500, 0.01, 1000, 50000, 0.001, 225, 0.00001)
    assert q == pytest.approx(0.0045, abs=0.00001)  # ograničeno na 225 EUR troška
    q2 = spot_quantity(500, 0.01, 1000, 50000, 0.001, 10_000, 0.00001)
    assert q2 * (1000 + 50000 * 0.002) == pytest.approx(5.0, rel=0.01)
    assert spot_quantity(500, 0.01, 0, 50000, 0.001, 225, 0.00001) == 0


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.content = b"x"
        self.text = str(body)

    def json(self):
        return self._body


class RecordingSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, timeout=None):
        self.calls.append((method, url))
        return self.responses.pop(0)


def test_signed_request_signature():
    sess = RecordingSession([FakeResp(200, {"balances": [{"asset": "USDT", "free": "10", "locked": "0"}]})])
    c = BinanceClient("key", "secret", testnet=True, session=sess, retries=0)
    assert c.balances() == {"USDT": {"free": 10.0, "locked": 0.0}}
    method, url = sess.calls[0]
    assert url.startswith("https://testnet.binance.vision/api/v3/account?")
    query = urlsplit(url).query
    unsigned, sig = query.rsplit("&signature=", 1)
    assert sig == hmac.new(b"secret", unsigned.encode(), hashlib.sha256).hexdigest()
    assert "timestamp" in dict(parse_qsl(unsigned))
    assert sess.headers["X-MBX-APIKEY"] == "key"


def test_api_error_raised():
    sess = RecordingSession([FakeResp(400, {"code": -2010, "msg": "Account has insufficient balance"})])
    c = BinanceClient("k", "s", session=sess, retries=0)
    with pytest.raises(BinanceError) as e:
        c.market_order("BTCUSDT", "BUY", 1, 0.001)
    assert e.value.code == -2010


# --------------------------------------------------------------- bot
SYMBOL_INFO = {
    "symbol": "BTCUSDT", "base": "BTC", "quote": "USDT", "status": "TRADING",
    "tick": 0.01, "step": 0.00001, "min_qty": 0.00001, "min_notional": 5.0,
    "order_types": ["LIMIT", "MARKET", "STOP_LOSS", "LIMIT_MAKER"],
}


class FakeBinance:
    def __init__(self, candles=None):
        self.candles_data = candles or []
        self.usdt = 500.0
        self.orders = []
        self.oco = []
        self.fail_oco = False
        self.lists = {}
        self.order_info = {}
        self.price = 50000.0

    def symbol_info(self, s):
        return dict(SYMBOL_INFO, symbol=s)

    def candles(self, s, g, limit=500):
        return self.candles_data

    def book(self, s):
        return {"bid": self.price * 0.9999, "ask": self.price}

    def balances(self):
        return {"USDT": {"free": self.usdt, "locked": 0.0}}

    def market_order(self, s, side, qty, step):
        self.orders.append((side, qty))
        cost = qty * self.price
        if side == "BUY":
            self.usdt -= cost
        return {
            "executedQty": str(qty), "cummulativeQuoteQty": str(cost),
            "fills": [{"commission": str(qty * 0.001), "commissionAsset": "BTC"}],
        }

    def oco_sell(self, s, qty, tp, sl):
        if self.fail_oco:
            raise BinanceError("PERCENT_PRICE filter")
        self.oco.append((qty, tp, sl))
        lid = len(self.oco)
        self.lists[lid] = {"listOrderStatus": "EXECUTING", "orders": [{"orderId": 10 * lid}, {"orderId": 10 * lid + 1}]}
        return {"orderListId": lid}

    def order_list(self, lid):
        return self.lists[lid]

    def get_order(self, s, oid):
        return self.order_info.get(oid, {"status": "EXPIRED"})

    def cancel_order_list(self, s, lid):
        self.lists[lid]["listOrderStatus"] = "ALL_DONE"


class FakeTG:
    def __init__(self):
        self.sent = []

    def send(self, t):
        self.sent.append(t)

    def poll_commands(self):
        return []


def make_spot(tmp_path, client, now=None, **kw):
    cfg = Config(broker="binance", symbols=["BTCUSDT"], data_dir=tmp_path, granularity="H4", **kw)
    return SpotBot(cfg, client, FakeTG(), now=now or (lambda: datetime(2025, 3, 3, 12, tzinfo=timezone.utc)))


def test_spot_buy_places_oco(tmp_path):
    client = FakeBinance()
    bot = make_spot(tmp_path, client)
    assert bot.execute("BTCUSDT", Signal("buy", 50000, 1000, 2000, "t"), 500, 500)
    side, qty = client.orders[0]
    assert side == "BUY" and 0 < qty * 50000 <= 500 * 0.45 + 1e-6
    oco_qty, tp, sl = client.oco[0]
    assert oco_qty < qty  # umanjeno za proviziju u BTC
    assert tp == pytest.approx(52000) and sl == pytest.approx(49000)
    assert "BTCUSDT" in bot.state.positions


def test_oco_failure_sells_immediately(tmp_path):
    client = FakeBinance()
    client.fail_oco = True
    bot = make_spot(tmp_path, client)
    assert not bot.execute("BTCUSDT", Signal("buy", 50000, 1000, 2000, "t"), 500, 500)
    assert [o[0] for o in client.orders] == ["BUY", "SELL"]
    assert not bot.state.positions
    assert "odmah prodana" in bot.tg.sent[-1]


def test_too_small_position_skipped(tmp_path):
    client = FakeBinance()
    bot = make_spot(tmp_path, client)
    assert not bot.execute("BTCUSDT", Signal("buy", 50000, 1000, 2000, "t"), 500, 4.0)
    assert client.orders == []


def test_dry_run_spot(tmp_path):
    client = FakeBinance()
    bot = make_spot(tmp_path, client, dry_run=True)
    assert bot.execute("BTCUSDT", Signal("buy", 50000, 1000, 2000, "t"), 500, 500)
    assert client.orders == []


def test_closed_position_reported(tmp_path):
    client = FakeBinance()
    bot = make_spot(tmp_path, client)
    bot.execute("BTCUSDT", Signal("buy", 50000, 1000, 2000, "t"), 500, 500)
    qty = client.oco[0][0]
    client.lists[1]["listOrderStatus"] = "ALL_DONE"
    client.order_info[10] = {"status": "FILLED", "type": "LIMIT_MAKER", "cummulativeQuoteQty": str(qty * 52000)}
    bot._sync_positions()
    assert not bot.state.positions
    assert "take-profit" in bot.tg.sent[-1] and "+" in bot.tg.sent[-1]


def test_sell_signals_ignored_on_spot(tmp_path, wave_candles):
    p = StrategyParams()
    ind = compute_indicators(wave_candles, p)
    idx = next(i for i in range(len(wave_candles)) if (s := signal_at(wave_candles, ind, i, p)) and s.side == "sell")
    candles = wave_candles[: idx + 1]
    last = parse_time(candles[-1].time)
    client = FakeBinance(candles)
    bot = make_spot(tmp_path, client, now=lambda: last + timedelta(hours=1, minutes=1))
    bot.cfg.granularity = "H1"
    bot.check_once()
    assert client.orders == []


def test_buy_signal_trades_on_spot(tmp_path, wave_candles):
    p = StrategyParams()
    ind = compute_indicators(wave_candles, p)
    idx = next(i for i in range(len(wave_candles)) if (s := signal_at(wave_candles, ind, i, p)) and s.side == "buy")
    candles = wave_candles[: idx + 1]
    last = parse_time(candles[-1].time)
    client = FakeBinance(candles)
    client.price = candles[-1].close
    bot = make_spot(tmp_path, client, now=lambda: last + timedelta(hours=1, minutes=1))
    bot.cfg.granularity = "H1"
    bot.check_once()
    bot.check_once()
    assert [o[0] for o in client.orders] == ["BUY"]


def test_spot_backtest_long_only_with_fees(wave_candles):
    res = run_backtest(wave_candles, StrategyParams(), instrument="BTCUSDT", account_currency="USDT",
                       spot=True, fee_rate=0.001)
    assert res.trades and all(t.side == "buy" for t in res.trades)
    assert abs(res.start_balance + sum(t.pnl for t in res.trades) - res.end_balance) < 1e-6
    no_fee = run_backtest(wave_candles, StrategyParams(), instrument="BTCUSDT", account_currency="USDT",
                          spot=True, fee_rate=0.0)
    assert no_fee.end_balance > res.end_balance
