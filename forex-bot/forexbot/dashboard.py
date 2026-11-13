"""Web aplikacija bota: mala stranica na kućnoj mreži, zaštićena PIN-om.

Pokreće je grid bot (DASHBOARD_PORT, zadano 8080). Otvori na mobitelu
http://<IP računala>:8080 i dodaj na početni zaslon.

Rute:
  GET  /                  aplikacija (static/index.html)
  GET  /manifest.json     za "dodaj na početni zaslon"
  GET  /icon.svg
  GET  /api/state         stanje bota            (traži PIN)
  GET  /api/candles?tf=   svijeće s Binancea      (traži PIN)
  GET  /api/history       dnevna povijest + potezi (traži PIN)
  POST /api/command       {"cmd": "pauza"|"nastavi"} (traži PIN)
"""

from __future__ import annotations

import csv
import hmac
import json
import logging
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

from .binance import BinanceClient, BinanceError

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"

# vremenski okvir -> (granularnost, broj svijeća)
TIMEFRAMES = {"24h": ("M15", 96), "7d": ("H1", 168), "30d": ("H4", 180)}
CANDLE_CACHE_SECONDS = 30
ALLOWED_COMMANDS = {"pauza": "/pauza", "nastavi": "/nastavi"}

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#0b0f17"/>
<g stroke="#2a3446" stroke-width="10">
<line x1="96" y1="150" x2="416" y2="150"/><line x1="96" y1="230" x2="416" y2="230"/>
<line x1="96" y1="310" x2="416" y2="310"/><line x1="96" y1="390" x2="416" y2="390"/></g>
<polyline points="96,360 170,300 230,340 300,210 360,250 416,140" fill="none" stroke="#f0b90b"
 stroke-width="26" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="170" cy="300" r="20" fill="#2ebd85"/><circle cx="300" cy="210" r="20" fill="#f6465d"/>
</svg>"""


def lan_ip() -> str:
    """IP adresa računala u kućnoj mreži (UDP 'connect' ne šalje ništa)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def load_or_create_pin(data_dir: Path, configured: str) -> str:
    if configured:
        return configured
    path = data_dir / "dashboard_pin.txt"
    try:
        pin = path.read_text(encoding="utf-8").strip()
        if pin:
            return pin
    except OSError:
        pass
    pin = f"{secrets.randbelow(1_000_000):06d}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pin, encoding="utf-8")
    return pin


def read_csv(path: Path, limit: int = 0) -> List[Dict[str, str]]:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return []
    return rows[-limit:] if limit else rows


class Dashboard:
    def __init__(self, bot: Any, pin: str, public_client: BinanceClient):
        self.bot = bot
        self.pin = pin
        self.public = public_client
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def check_pin(self, given: str) -> bool:
        return bool(given) and hmac.compare_digest(given.encode(), self.pin.encode())

    def candles(self, tf: str) -> List[Dict[str, Any]]:
        gran, limit = TIMEFRAMES.get(tf, TIMEFRAMES["24h"])
        with self._lock:
            cached = self._cache.get(tf)
            if cached and time.time() - cached[0] < CANDLE_CACHE_SECONDS:
                return cached[1]
            rows = self.public.candles(self.bot.symbol, gran, limit=limit)
            data = [{"t": c.time, "o": c.open, "h": c.high, "l": c.low, "c": c.close} for c in rows]
            self._cache[tf] = (time.time(), data)
            return data

    def history(self) -> Dict[str, Any]:
        data_dir = self.bot.cfg.data_dir
        return {
            "daily": read_csv(data_dir / "povijest.csv"),
            "trades": read_csv(data_dir / "trades.csv", limit=300),
        }

    def command(self, name: str) -> bool:
        cmd = ALLOWED_COMMANDS.get(name)
        if not cmd:
            return False
        self.bot.commands.put(cmd)
        return True


def make_handler(app: Dashboard):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TradingBot/1.0"

        def log_message(self, fmt, *args):  # tiši log
            log.debug("web: " + fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _authorized(self) -> bool:
            if app.check_pin(self.headers.get("X-Pin", "")):
                return True
            time.sleep(1.0)  # uspori pogađanje PIN-a
            self._json(401, {"error": "Pogrešan PIN"})
            return False

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            path = url.path
            if path in ("/", "/index.html"):
                try:
                    body = (STATIC / "index.html").read_bytes()
                except OSError:
                    self._send(500, b"index.html nedostaje", "text/plain; charset=utf-8")
                    return
                self._send(200, body, "text/html; charset=utf-8")
            elif path == "/manifest.json":
                manifest = {
                    "name": "Trading bot", "short_name": "Bot", "start_url": "/", "display": "standalone",
                    "background_color": "#0b0f17", "theme_color": "#0b0f17",
                    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
                }
                self._send(200, json.dumps(manifest).encode(), "application/manifest+json", cache=True)
            elif path == "/icon.svg":
                self._send(200, ICON_SVG.encode(), "image/svg+xml", cache=True)
            elif path == "/api/state":
                if self._authorized():
                    self._json(200, app.bot.snapshot)
            elif path == "/api/candles":
                if self._authorized():
                    tf = parse_qs(url.query).get("tf", ["24h"])[0]
                    try:
                        self._json(200, app.candles(tf))
                    except BinanceError as exc:
                        self._json(502, {"error": str(exc)})
            elif path == "/api/history":
                if self._authorized():
                    self._json(200, app.history())
            else:
                self._send(404, b"Nema", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/command":
                self._send(404, b"Nema", "text/plain; charset=utf-8")
                return
            if not self._authorized():
                return
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 1000)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "Neispravan zahtjev"})
                return
            if app.command(str(body.get("cmd", ""))):
                self._json(200, {"ok": True})
            else:
                self._json(400, {"error": "Nepoznata komanda"})

    return Handler


def start_dashboard(bot: Any, port: int, host: str = "0.0.0.0") -> Tuple[str, str]:
    """Pokreće web aplikaciju u pozadinskom threadu. Vraća (url, pin)."""
    pin = load_or_create_pin(bot.cfg.data_dir, bot.cfg.dashboard_pin)
    public = BinanceClient(testnet=bot.cfg.binance_testnet, retries=1)
    app = Dashboard(bot, pin, public)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="dashboard", daemon=True).start()
    url = f"http://{lan_ip()}:{server.server_address[1]}"
    log.info("Aplikacija radi na %s", url)
    return url, pin
