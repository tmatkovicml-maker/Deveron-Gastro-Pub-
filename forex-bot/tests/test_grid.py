from datetime import datetime, timezone

import pytest

from forexbot.config import Config, ConfigError
from forexbot.grid import GridBot, check_spacing, grid_levels, simulate_grid, spacing_pct
from tests.conftest import make_candles


def test_levels_geometric():
    lv = grid_levels(100, 121, 2)
    assert lv == pytest.approx([100, 110, 121])
    assert spacing_pct(100, 121, 2) == pytest.approx(10)


def test_spacing_must_beat_fees():
    with pytest.raises(ValueError):
        check_spacing(100, 101, 10, 0.001)  # 0.1% razmak < 0.2% provizija
    check_spacing(92, 108, 8, 0.001)


def test_simulation_profits_from_oscillation():
    closes = [100, 97, 100, 97, 100, 97, 100] * 20
    candles = make_candles(closes, wiggle=0.0)
    res = simulate_grid(candles, 90, 110, 10, 6, 0.001, 50)
    assert res.cycles > 10
    assert res.grid_profit > 0
    assert res.end_value > res.start_value


def test_simulation_trending_down_holds_loss():
    closes = [100 - i * 0.5 for i in range(40)]
    res = simulate_grid(make_candles(closes, wiggle=0.0), 90, 110, 10, 6, 0.001, 50)
    assert res.cycles == 0
    assert res.end_value < res.start_value


INFO = {"symbol": "ETHUSDC", "base": "ETH", "quote": "USDC", "status": "TRADING", "tick": 0.01,
        "step": 0.0001, "min_qty": 0.0001, "min_notional": 5.0, "order_types": ["LIMIT", "MARKET"]}


class FakeEx:
    def __init__(self, price=2000.0, usdc=50.0):
        self.price = price
        self.usdc = usdc
        self.orders = {}
        self.next_id = 1
        self.market = []
        self.fail_next = False
        self.fee_asset = "ETH"

    def order_trades(self, s, oid):
        o = self.orders[oid]
        fee = o["qty"] * 0.001 if self.fee_asset == "ETH" else 0.00001
        return [{"commission": str(fee), "commissionAsset": self.fee_asset}]

    def symbol_info(self, s):
        return INFO

    def book(self, s):
        return {"bid": self.price * 0.9999, "ask": self.price}

    def balances(self):
        return {"USDC": {"free": self.usdc, "locked": 0.0}}

    def limit_order(self, s, side, qty, price):
        if self.fail_next:
            self.fail_next = False
            from forexbot.binance import BinanceError
            raise BinanceError("temporary")
        oid = self.next_id
        self.next_id += 1
        self.orders[oid] = {"orderId": oid, "side": side, "qty": qty, "price": price, "status": "NEW"}
        return {"orderId": oid}

    def open_orders(self, s):
        return [o for o in self.orders.values() if o["status"] == "NEW"]

    def get_order(self, s, oid):
        o = self.orders[oid]
        filled = o["status"] == "FILLED"
        return {"status": o["status"], "executedQty": str(o["qty"] if filled else 0),
                "cummulativeQuoteQty": str(o["qty"] * o["price"] if filled else 0)}

    def cancel_order(self, s, oid):
        self.orders[oid]["status"] = "CANCELED"

    def market_order(self, s, side, qty, step):
        self.market.append((side, qty))
        return {"cummulativeQuoteQty": str(qty * self.price)}

    def fill(self, side, price_cmp):
        for o in self.orders.values():
            if o["status"] == "NEW" and o["side"] == side and price_cmp(o["price"]):
                o["status"] = "FILLED"
                return o


class TG:
    def __init__(self):
        self.sent = []

    def send(self, t):
        self.sent.append(t)

    def poll_commands(self):
        return []


def make_grid(tmp_path, ex, **kw):
    cfg = Config(broker="binance", strategy_mode="grid", symbols=["ETHUSDC"], data_dir=tmp_path,
                 grid_range_pct=8, grid_levels=8, grid_order_quote=6, **kw)
    return GridBot(cfg, ex, TG(), now=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc))


def test_init_places_buys_below_price_within_budget(tmp_path):
    ex = FakeEx(usdc=20)
    bot = make_grid(tmp_path, ex)
    bot.check_once()
    buys = [o for o in ex.orders.values() if o["side"] == "BUY"]
    assert len(buys) == 3  # 20 USDC / 6 = 3 naloga
    assert all(o["price"] < 2000 for o in buys)
    # najbliže razine cijeni prve
    below = [lv for lv in bot.g["levels"] if lv < 2000 * 0.999]
    assert sorted(o["price"] for o in buys) == pytest.approx(below[-3:])


@pytest.mark.parametrize("fee_asset", ["ETH", "BNB"])
def test_full_cycle_buy_then_sell_then_rebuy(tmp_path, fee_asset):
    ex = FakeEx()
    ex.fee_asset = fee_asset
    bot = make_grid(tmp_path, ex)
    bot.check_once()
    lv = bot.g["levels"]
    bought = ex.fill("BUY", lambda p: p == pytest.approx(lv[3]))
    ex.price = lv[3]
    bot.check_once()
    sells = [o for o in ex.orders.values() if o["side"] == "SELL" and o["status"] == "NEW"]
    assert len(sells) == 1 and sells[0]["price"] == pytest.approx(lv[4])
    if fee_asset == "BNB":
        assert sells[0]["qty"] == pytest.approx(bought["qty"])  # provizija u BNB -> prodaje sve
    else:
        assert sells[0]["qty"] < bought["qty"]  # provizija u ETH -> ostatak je "prašina"
        assert bot.g["dust"] > 0
    assert "KUPIO" in bot.tg.sent[-1]

    ex.fill("SELL", lambda p: True)
    ex.price = lv[4]
    bot.check_once()
    assert bot.g["cycles"] == 1 and bot.g["profit"] > 0
    assert "PRODAO" in bot.tg.sent[-1]
    rebuys = [o for o in ex.orders.values() if o["side"] == "BUY" and o["status"] == "NEW" and o["price"] == pytest.approx(lv[3])]
    assert len(rebuys) == 1


def test_failed_order_retried(tmp_path):
    ex = FakeEx()
    bot = make_grid(tmp_path, ex)
    bot.check_once()
    lv = bot.g["levels"]
    ex.fill("BUY", lambda p: p == pytest.approx(lv[3]))
    ex.fail_next = True
    bot.check_once()
    assert len(bot.g["pending"]) == 1
    bot.check_once()
    assert bot.g["pending"] == []
    assert any(o["side"] == "SELL" and o["status"] == "NEW" for o in ex.orders.values())


def test_close_all_sells_holdings_and_pauses(tmp_path):
    ex = FakeEx()
    bot = make_grid(tmp_path, ex)
    bot.check_once()
    lv = bot.g["levels"]
    ex.fill("BUY", lambda p: p == pytest.approx(lv[3]))
    bot.check_once()
    msg = bot.close_all()
    assert ex.market and ex.market[0][0] == "SELL"
    assert all(o["status"] != "NEW" for o in ex.orders.values())
    assert bot.state.paused and bot.g == {}
    assert "ugašen" in msg


def test_bad_grid_config_reported_not_crash(tmp_path):
    ex = FakeEx()
    bot = make_grid(tmp_path, ex)
    bot.cfg.grid_levels = 50
    bot.cfg.grid_range_pct = 2  # razmak premalen za provizije
    bot.check_once()
    assert bot.state.paused
    assert "nije postavljen" in bot.tg.sent[-1]


def test_grid_config_validation():
    with pytest.raises(ConfigError):
        Config(broker="binance", strategy_mode="grid", grid_lower=100).validate()
    Config(broker="binance", strategy_mode="grid", grid_lower=100, grid_upper=120).validate()
