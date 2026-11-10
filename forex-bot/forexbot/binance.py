"""Minimalni klijent za Binance Spot REST API (samo `requests`).

Testnet (virtualni novac): https://testnet.binance.vision
Pravi račun:               https://api.binance.com
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from .strategy import Candle

log = logging.getLogger(__name__)

HOSTS = {"testnet": "https://testnet.binance.vision", "live": "https://api.binance.com"}
# Povijesni podaci za backtest uvijek s pravog tržišta (javni endpoint, ne treba ključ).
PUBLIC_DATA_HOST = "https://data-api.binance.vision"

INTERVALS = {"M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "D": "1d"}


class BinanceError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, code: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.code = code


def fmt_decimal(value: float, step: float) -> str:
    """Broj zaokružen (prema dolje) na korak, kao string bez znanstvenog zapisa."""
    d_step = Decimal(str(step))
    d = (Decimal(str(value)) // d_step) * d_step
    return format(d.normalize(), "f") if d != 0 else "0"


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


class BinanceClient:
    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        timeout: float = 15.0,
        retries: int = 3,
        session: Optional[requests.Session] = None,
        base_url: Optional[str] = None,
    ):
        self.base_url = base_url or HOSTS["testnet" if testnet else "live"]
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        if api_key:
            self.session.headers.update({"X-MBX-APIKEY": api_key})
        self._time_offset_ms = 0
        self._symbol_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False, base_url: Optional[str] = None) -> Any:
        url = (base_url or self.base_url) + path
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            p = dict(params or {})
            if signed:
                if not self.api_secret:
                    raise BinanceError("Nedostaje BINANCE_API_SECRET")
                p["timestamp"] = int(time.time() * 1000) + self._time_offset_ms
                p["recvWindow"] = 10000
                query = urlencode(p)
                sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
                full_url = f"{url}?{query}&signature={sig}"
            else:
                full_url = f"{url}?{urlencode(p)}" if p else url
            try:
                resp = self.session.request(method, full_url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Mrežna greška (%s %s): %s", method, path, exc)
            else:
                if resp.status_code < 400:
                    return resp.json() if resp.content else {}
                try:
                    body = resp.json()
                except ValueError:
                    body = {"msg": resp.text[:200]}
                code, msg = body.get("code"), body.get("msg", "")
                if code == -1021 and attempt < self.retries:  # sat izvan sinkronizacije
                    self.sync_time()
                    continue
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = BinanceError(f"HTTP {resp.status_code}: {msg}", resp.status_code, code)
                    log.warning("Binance privremena greška %s, pokušavam ponovno", resp.status_code)
                else:
                    raise BinanceError(f"HTTP {resp.status_code} ({code}): {msg}", resp.status_code, code)
            if attempt < self.retries:
                time.sleep(2 ** (attempt + 1))
        raise BinanceError(f"Zahtjev nije uspio nakon {self.retries + 1} pokušaja: {last_exc}")

    def sync_time(self) -> None:
        server = self._request("GET", "/api/v3/time")["serverTime"]
        self._time_offset_ms = int(server - time.time() * 1000)

    # ----------------------------------------------------------- market data
    def symbol_info(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self._symbol_cache:
            data = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
            s = data["symbols"][0]
            filters = {f["filterType"]: f for f in s.get("filters", [])}
            notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
            self._symbol_cache[symbol] = {
                "symbol": symbol,
                "base": s["baseAsset"],
                "quote": s["quoteAsset"],
                "status": s.get("status", "TRADING"),
                "tick": float(filters["PRICE_FILTER"]["tickSize"]),
                "step": float(filters["LOT_SIZE"]["stepSize"]),
                "min_qty": float(filters["LOT_SIZE"]["minQty"]),
                "min_notional": float(notional.get("minNotional", 0) or 0),
                "order_types": s.get("orderTypes", []),
            }
        return self._symbol_cache[symbol]

    def candles(self, symbol: str, granularity: str = "H1", limit: int = 500, start_ms: Optional[int] = None, base_url: Optional[str] = None) -> List[Candle]:
        params: Dict[str, Any] = {"symbol": symbol, "interval": INTERVALS[granularity], "limit": min(limit, 1000)}
        if start_ms is not None:
            params["startTime"] = start_ms
        rows = self._request("GET", "/api/v3/klines", params, base_url=base_url)
        now_ms = int(time.time() * 1000)
        return [
            Candle(
                time=ms_to_iso(r[0]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=int(float(r[5])),
                complete=int(r[6]) < now_ms,
            )
            for r in rows
        ]

    def history(self, symbol: str, granularity: str, start_ms: int) -> List[Candle]:
        """Zatvorene svijeće s pravog tržišta od start_ms do sada (za backtest)."""
        out: List[Candle] = []
        cursor = start_ms
        while True:
            rows = self._request(
                "GET",
                "/api/v3/klines",
                {"symbol": symbol, "interval": INTERVALS[granularity], "limit": 1000, "startTime": cursor},
                base_url=PUBLIC_DATA_HOST,
            )
            if not rows:
                break
            now_ms = int(time.time() * 1000)
            for r in rows:
                if int(r[6]) < now_ms:
                    out.append(Candle(ms_to_iso(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(float(r[5]))))
            if len(rows) < 1000:
                break
            cursor = int(rows[-1][0]) + 1
        return out

    def book(self, symbol: str) -> Dict[str, float]:
        d = self._request("GET", "/api/v3/ticker/bookTicker", {"symbol": symbol})
        return {"bid": float(d["bidPrice"]), "ask": float(d["askPrice"])}

    # --------------------------------------------------------------- account
    def balances(self) -> Dict[str, Dict[str, float]]:
        data = self._request("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
        return {
            b["asset"]: {"free": float(b["free"]), "locked": float(b["locked"])}
            for b in data.get("balances", [])
        }

    # ---------------------------------------------------------------- orders
    def market_order(self, symbol: str, side: str, quantity: float, step: float) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": fmt_decimal(quantity, step),
                "newOrderRespType": "FULL",
            },
            signed=True,
        )

    def oco_sell(self, symbol: str, quantity: float, take_profit: float, stop_loss: float) -> Dict[str, Any]:
        """OCO prodaja: take-profit (LIMIT_MAKER iznad) + stop-loss (ispod). Izvrši se samo jedan."""
        info = self.symbol_info(symbol)
        tick, step = info["tick"], info["step"]
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": "SELL",
            "quantity": fmt_decimal(quantity, step),
            "aboveType": "LIMIT_MAKER",
            "abovePrice": fmt_decimal(take_profit, tick),
            "belowStopPrice": fmt_decimal(stop_loss, tick),
            "newOrderRespType": "FULL",
        }
        if "STOP_LOSS" in info["order_types"]:
            params["belowType"] = "STOP_LOSS"  # tržišni nalog nakon okidanja - sigurno izlazi
        else:
            params["belowType"] = "STOP_LOSS_LIMIT"
            params["belowPrice"] = fmt_decimal(stop_loss * 0.995, tick)
            params["belowTimeInForce"] = "GTC"
        return self._request("POST", "/api/v3/orderList/oco", params, signed=True)

    def order_list(self, order_list_id: int) -> Dict[str, Any]:
        return self._request("GET", "/api/v3/orderList", {"orderListId": order_list_id}, signed=True)

    def get_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        return self._request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def cancel_order_list(self, symbol: str, order_list_id: int) -> Dict[str, Any]:
        return self._request("DELETE", "/api/v3/orderList", {"symbol": symbol, "orderListId": order_list_id}, signed=True)
