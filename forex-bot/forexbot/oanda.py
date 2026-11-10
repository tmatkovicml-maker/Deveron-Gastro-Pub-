"""Minimalni klijent za OANDA v20 REST API (samo `requests`)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, List, Optional

import requests

from .strategy import Candle

log = logging.getLogger(__name__)

HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


class OandaError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class OandaClient:
    def __init__(
        self,
        token: str,
        account_id: str,
        env: str = "practice",
        timeout: float = 15.0,
        retries: int = 3,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = HOSTS[env]
        self.account_id = account_id
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "RFC3339",
            }
        )
        self._instrument_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, params=None, json=None) -> Dict[str, Any]:
        url = self.base_url + path
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.request(method, url, params=params, json=json, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Mrežna greška (%s %s): %s", method, path, exc)
            else:
                if resp.status_code < 400:
                    return resp.json() if resp.content else {}
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = OandaError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
                    log.warning("OANDA privremena greška %s, pokušavam ponovno", resp.status_code)
                else:
                    try:
                        msg = resp.json().get("errorMessage", resp.text)
                    except ValueError:
                        msg = resp.text
                    raise OandaError(f"HTTP {resp.status_code}: {msg}", resp.status_code)
            if attempt < self.retries:
                time.sleep(2 ** (attempt + 1))
        raise OandaError(f"Zahtjev nije uspio nakon {self.retries + 1} pokušaja: {last_exc}")

    @property
    def _acct(self) -> str:
        return f"/v3/accounts/{self.account_id}"

    # --------------------------------------------------------------- account
    def account_summary(self) -> Dict[str, Any]:
        return self._request("GET", f"{self._acct}/summary")["account"]

    def instrument_info(self, instrument: str) -> Dict[str, Any]:
        if instrument not in self._instrument_cache:
            data = self._request("GET", f"{self._acct}/instruments", params={"instruments": instrument})
            items = data.get("instruments", [])
            if not items:
                raise OandaError(f"Instrument {instrument} nije dostupan na ovom računu")
            self._instrument_cache[instrument] = items[0]
        return self._instrument_cache[instrument]

    # ---------------------------------------------------------------- prices
    def candles(
        self,
        instrument: str,
        granularity: str = "H1",
        count: Optional[int] = None,
        from_time: Optional[str] = None,
    ) -> List[Candle]:
        params: Dict[str, Any] = {"granularity": granularity, "price": "M"}
        if count is not None:
            params["count"] = min(count, 5000)
        if from_time is not None:
            params["from"] = from_time
        data = self._request("GET", f"/v3/instruments/{instrument}/candles", params=params)
        out = []
        for c in data.get("candles", []):
            mid = c["mid"]
            out.append(
                Candle(
                    time=c["time"],
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=int(c.get("volume", 0)),
                    complete=bool(c.get("complete", True)),
                )
            )
        return out

    def history(self, instrument: str, granularity: str, from_time: str) -> List[Candle]:
        """Svi zatvoreni candlei od `from_time` do sada (straničenje po 5000)."""
        result: List[Candle] = []
        cursor = from_time
        while True:
            batch = self.candles(instrument, granularity, count=5000, from_time=cursor)
            batch = [c for c in batch if c.complete and (not result or c.time > result[-1].time)]
            if not batch:
                break
            result.extend(batch)
            if len(batch) < 2:
                break
            cursor = batch[-1].time
        return result

    def pricing(self, instruments: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        names = ",".join(instruments)
        data = self._request("GET", f"{self._acct}/pricing", params={"instruments": names})
        out = {}
        for p in data.get("prices", []):
            bid = float(p["bids"][0]["price"]) if p.get("bids") else float(p["closeoutBid"])
            ask = float(p["asks"][0]["price"]) if p.get("asks") else float(p["closeoutAsk"])
            out[p["instrument"]] = {"bid": bid, "ask": ask, "tradeable": bool(p.get("tradeable", True))}
        return out

    def mid_price(self, instrument: str) -> Optional[float]:
        try:
            p = self.pricing([instrument]).get(instrument)
        except OandaError as exc:
            if exc.status in (400, 404):
                return None
            raise
        return (p["bid"] + p["ask"]) / 2 if p else None

    # ---------------------------------------------------------------- trades
    def open_trades(self) -> List[Dict[str, Any]]:
        return self._request("GET", f"{self._acct}/openTrades").get("trades", [])

    def trade(self, trade_id: str) -> Dict[str, Any]:
        return self._request("GET", f"{self._acct}/trades/{trade_id}")["trade"]

    def market_order(
        self, instrument: str, units: int, stop_loss: float, take_profit: float, precision: int
    ) -> Dict[str, Any]:
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units)),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{stop_loss:.{precision}f}", "timeInForce": "GTC"},
                "takeProfitOnFill": {"price": f"{take_profit:.{precision}f}", "timeInForce": "GTC"},
            }
        }
        data = self._request("POST", f"{self._acct}/orders", json=body)
        if "orderFillTransaction" not in data:
            reason = data.get("orderCancelTransaction", {}).get("reason", "nepoznat razlog")
            raise OandaError(f"Nalog nije izvršen: {reason}")
        return data["orderFillTransaction"]

    def close_trade(self, trade_id: str) -> Dict[str, Any]:
        return self._request("PUT", f"{self._acct}/trades/{trade_id}/close")
