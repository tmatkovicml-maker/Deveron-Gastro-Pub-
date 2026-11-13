import json
import queue
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from forexbot import dashboard
from forexbot.dashboard import Dashboard, load_or_create_pin, make_handler
from forexbot.strategy import Candle


class Pub:
    calls = 0

    def candles(self, sym, gran, limit=500):
        Pub.calls += 1
        return [Candle("2026-11-13T10:00:00.000000000Z", 1, 2, 0.5, 1.5)]


class Cfg:
    def __init__(self, d):
        self.data_dir = d


class Bot:
    def __init__(self, d):
        self.symbol = "ETHUSDC"
        self.cfg = Cfg(d)
        self.commands = queue.Queue()
        self.snapshot = {"symbol": "ETHUSDC", "price": 2000.0}


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard.time, "sleep", lambda s: None)  # bez čekanja na pogrešan PIN
    (tmp_path / "trades.csv").write_text("vrijeme,strana,cijena\n2026-11-13T10:00:00,BUY,2000\n", encoding="utf-8")
    bot = Bot(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Dashboard(bot, "424242", Pub())))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield bot, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def req(url, pin=None, data=None):
    r = urllib.request.Request(url, data=data, headers={"X-Pin": pin} if pin else {})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_page_and_icon_public(server):
    _, base = server
    code, body = req(base + "/")
    assert code == 200 and b"Grid Bot" in body
    assert req(base + "/manifest.json")[0] == 200
    assert req(base + "/icon.svg")[0] == 200


def test_api_requires_pin(server):
    _, base = server
    assert req(base + "/api/state")[0] == 401
    assert req(base + "/api/state", pin="000000")[0] == 401
    code, body = req(base + "/api/state", pin="424242")
    assert code == 200 and json.loads(body)["price"] == 2000.0


def test_candles_cached_and_history(server):
    _, base = server
    Pub.calls = 0
    for _ in range(3):
        code, body = req(base + "/api/candles?tf=7d", pin="424242")
    assert code == 200 and json.loads(body)[0]["c"] == 1.5 and Pub.calls == 1
    hist = json.loads(req(base + "/api/history", pin="424242")[1])
    assert hist["trades"][0]["strana"] == "BUY" and hist["daily"] == []


def test_commands_only_whitelisted(server):
    bot, base = server
    assert req(base + "/api/command", pin="424242", data=b'{"cmd":"pauza"}')[0] == 200
    assert bot.commands.get_nowait() == "/pauza"
    assert req(base + "/api/command", pin="424242", data=b'{"cmd":"zatvori_sve"}')[0] == 400
    assert req(base + "/api/command", data=b'{"cmd":"pauza"}')[0] == 401
    assert bot.commands.empty()


def test_pin_generated_once(tmp_path):
    pin = load_or_create_pin(tmp_path, "")
    assert len(pin) == 6 and pin.isdigit()
    assert load_or_create_pin(tmp_path, "") == pin
    assert load_or_create_pin(tmp_path, "9999") == "9999"
