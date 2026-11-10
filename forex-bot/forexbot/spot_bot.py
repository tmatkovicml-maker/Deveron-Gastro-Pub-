"""Binance Spot bot: samo kupuje po signalu, a izlazi preko OCO naloga (stop-loss + take-profit).

Na spotu nema poluge ni prodaje na kratko (short), pa se "prodaj" signali ignoriraju.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .binance import BinanceClient, BinanceError
from .bot import HELP, parse_time
from .config import Config
from .risk import floor_to_step, spot_quantity
from .state import State
from .strategy import Candle, Signal, generate_signal
from .telegram import Telegram

log = logging.getLogger(__name__)


class SpotBot:
    def __init__(
        self,
        cfg: Config,
        client: BinanceClient,
        telegram: Telegram,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.cfg = cfg
        self.client = client
        self.tg = telegram
        self.now = now
        self.state_path = cfg.data_dir / "state_binance.json"
        self.state = State.load(self.state_path)
        self._running = True
        self.quote = client.symbol_info(cfg.symbols[0])["quote"]

    # ----------------------------------------------------------------- loop
    def run_forever(self) -> None:
        mode = "TESTNET (virtualni novac)" if self.cfg.binance_testnet else "PRAVI NOVAC"
        if self.cfg.dry_run:
            mode += ", DRY RUN (bez naloga)"
        self.tg.send(f"🤖 Binance bot pokrenut ({mode}).\nParovi: {', '.join(self.cfg.symbols)}\n\n{HELP}")
        while self._running:
            try:
                self.handle_commands()
                self.check_once()
            except BinanceError as exc:
                log.error("Binance greška: %s", exc)
            except Exception:
                log.exception("Neočekivana greška u petlji")
            time.sleep(self.cfg.poll_seconds)

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------- commands
    def handle_commands(self) -> None:
        for cmd in self.tg.poll_commands():
            log.info("Telegram komanda: %s", cmd)
            if cmd in ("/status", "/start"):
                self.tg.send(self.status_text())
            elif cmd == "/pauza":
                self.state.paused = True
                self._save()
                self.tg.send("⏸ Pauzirano - neću otvarati nove pozicije. Otvorene ostaju sa svojim SL/TP.")
            elif cmd == "/nastavi":
                self.state.paused = False
                self._save()
                self.tg.send("▶️ Nastavljam s trgovanjem.")
            elif cmd == "/zatvori_sve":
                self.state.paused = True
                self._save()
                self.tg.send(self.close_all())
            else:
                self.tg.send(HELP)

    def _equity(self, balances: Dict[str, Dict[str, float]]) -> float:
        q = balances.get(self.quote, {"free": 0.0, "locked": 0.0})
        total = q["free"] + q["locked"]
        for sym, pos in self.state.positions.items():
            total += pos["qty"] * self.client.book(sym)["bid"]
        return total

    def status_text(self) -> str:
        balances = self.client.balances()
        equity = self._equity(balances)
        free = balances.get(self.quote, {}).get("free", 0.0)
        lines = [
            f"💰 Ukupno (bot): {equity:.2f} {self.quote}",
            f"💵 Slobodno: {free:.2f} {self.quote}",
            f"Status: {'⏸ pauzirano' if self.state.paused else '▶️ aktivan'}"
            + (" | dnevni limit gubitka dosegnut" if self.state.daily_limit_hit else ""),
        ]
        if self.state.positions:
            lines.append("Otvorene pozicije:")
            for sym, pos in self.state.positions.items():
                bid = self.client.book(sym)["bid"]
                pl = pos["qty"] * bid * (1 - self.cfg.fee_rate) - pos["cost"]
                lines.append(f" • {sym} {pos['qty']} @ {pos['entry']:.6g} → {bid:.6g} ({pl:+.2f} {self.quote})")
        else:
            lines.append("Nema otvorenih pozicija.")
        return "\n".join(lines)

    def close_all(self) -> str:
        if not self.state.positions:
            return "Nema otvorenih pozicija. Bot je pauziran (/nastavi za nastavak)."
        results = []
        for sym, pos in list(self.state.positions.items()):
            try:
                try:
                    self.client.cancel_order_list(sym, pos["list_id"])
                except BinanceError as exc:
                    log.warning("Otkazivanje OCO %s: %s", sym, exc)
                step = self.client.symbol_info(sym)["step"]
                res = self.client.market_order(sym, "SELL", pos["qty"], step)
                proceeds = float(res.get("cummulativeQuoteQty", 0)) * (1 - self.cfg.fee_rate)
                results.append(f"✅ prodan {sym}: {proceeds - pos['cost']:+.2f} {self.quote}")
                del self.state.positions[sym]
            except BinanceError as exc:
                results.append(f"❌ {sym}: {exc}")
        self._save()
        return "\n".join(results) + "\nBot je pauziran (/nastavi za nastavak)."

    # ---------------------------------------------------------------- check
    def check_once(self) -> None:
        self._sync_positions()
        balances = self.client.balances()
        equity = self._equity(balances)
        self._update_day(equity)

        if self.state.paused or self._daily_limit_reached(equity):
            self._save()
            return

        for sym in self.cfg.symbols:
            if len(self.state.positions) >= self.cfg.max_open_trades:
                break
            if sym in self.state.positions:
                continue
            candles = self._fresh_completed_candles(sym)
            if candles is None:
                continue
            signal = generate_signal(candles, self.cfg.strategy)
            if signal is None or signal.side != "buy":
                continue
            log.info("Signal %s: %s", sym, signal.reason)
            free = self.client.balances().get(self.quote, {}).get("free", 0.0)
            self.execute(sym, signal, equity, free)
        self._save()

    def _update_day(self, equity: float) -> None:
        today = self.now().strftime("%Y-%m-%d")
        if self.state.day != today:
            self.state.day = today
            self.state.day_start_nav = equity
            self.state.daily_limit_hit = False

    def _daily_limit_reached(self, equity: float) -> bool:
        start = self.state.day_start_nav
        if start <= 0 or equity > start * (1 - self.cfg.daily_loss_limit):
            return False
        if not self.state.daily_limit_hit:
            self.state.daily_limit_hit = True
            self.tg.send(
                f"🛑 Dnevni limit gubitka dosegnut ({equity - start:+.2f} {self.quote}). "
                "Danas više ne otvaram nove pozicije."
            )
        return True

    def _fresh_completed_candles(self, sym: str) -> Optional[List[Candle]]:
        limit = min(1000, self.cfg.strategy.min_candles() + 300)
        candles = [c for c in self.client.candles(sym, self.cfg.granularity, limit=limit) if c.complete]
        if not candles:
            return None
        last = candles[-1]
        if self.state.last_candle.get(sym) == last.time:
            return None
        self.state.last_candle[sym] = last.time
        age = (self.now() - parse_time(last.time)).total_seconds()
        if age > self.cfg.granularity_seconds + 600:
            return None
        return candles

    # -------------------------------------------------------------- execute
    def execute(self, sym: str, signal: Signal, equity: float, free_quote: float) -> bool:
        info = self.client.symbol_info(sym)
        if info["status"] != "TRADING":
            return False
        book = self.client.book(sym)
        bid, ask = book["bid"], book["ask"]
        spread_pct = (ask - bid) / ask * 100
        if spread_pct > self.cfg.max_spread_pct:
            self.tg.send(f"⚠️ {sym}: signal, ali spread {spread_pct:.2f}% je prevelik - preskačem.")
            return False

        entry = ask
        if entry - signal.sl_distance <= 0:
            return False
        max_cost = min(free_quote * 0.98, equity * self.cfg.max_position_fraction)
        qty = spot_quantity(
            equity, self.cfg.risk_per_trade, signal.sl_distance, entry, self.cfg.fee_rate, max_cost, info["step"]
        )
        if qty < info["min_qty"] or qty * entry < info["min_notional"]:
            self.tg.send(
                f"ℹ️ {sym}: signal, ali pozicija je premala (min. {info['min_notional']:.2f} {self.quote}) - preskačem."
            )
            return False

        sl, tp = entry - signal.sl_distance, entry + signal.tp_distance
        risk_amt = qty * (signal.sl_distance + entry * self.cfg.fee_rate * 2)
        summary = (
            f"{sym} KUPI {qty} @ ~{entry:.6g} (≈{qty * entry:.2f} {self.quote})\n"
            f"SL {sl:.6g} (rizik ~{risk_amt:.2f} {self.quote}) | TP {tp:.6g}\n"
            f"Razlog: {signal.reason}"
        )
        if self.cfg.dry_run:
            self.tg.send("🧪 [DRY RUN] " + summary)
            return True

        try:
            buy = self.client.market_order(sym, "BUY", qty, info["step"])
        except BinanceError as exc:
            self.tg.send(f"❌ Kupnja {sym} nije uspjela: {exc}")
            return False

        filled = float(buy.get("executedQty", 0))
        cost = float(buy.get("cummulativeQuoteQty", 0))
        if filled <= 0:
            self.tg.send(f"❌ Kupnja {sym} nije izvršena.")
            return False
        avg = cost / filled
        fee_base = sum(float(f["commission"]) for f in buy.get("fills", []) if f.get("commissionAsset") == info["base"])
        fee_quote = sum(float(f["commission"]) for f in buy.get("fills", []) if f.get("commissionAsset") == self.quote)
        sell_qty = floor_to_step(filled - fee_base, info["step"])
        sl, tp = avg - signal.sl_distance, avg + signal.tp_distance

        try:
            oco = self.client.oco_sell(sym, sell_qty, tp, sl)
        except BinanceError as exc:
            # nikad ne ostavljaj poziciju bez stop-lossa
            log.error("OCO nije uspio, prodajem odmah: %s", exc)
            try:
                self.client.market_order(sym, "SELL", sell_qty, info["step"])
                self.tg.send(f"⚠️ {sym}: stop-loss nije postavljen ({exc}), pozicija je odmah prodana.")
            except BinanceError as exc2:
                self.tg.send(f"🚨 {sym}: stop-loss NIJE postavljen i prodaja nije uspjela: {exc2}. Provjeri Binance ručno!")
            return False

        self.state.positions[sym] = {
            "qty": sell_qty,
            "entry": avg,
            "cost": cost + fee_quote,
            "sl": sl,
            "tp": tp,
            "list_id": oco["orderListId"],
            "opened": self.now().isoformat(),
        }
        self._save()
        self.tg.send(f"✅ Kupljeno\n{sym} {sell_qty} @ {avg:.6g}\nSL {sl:.6g} | TP {tp:.6g}\nRazlog: {signal.reason}")
        return True

    def _sync_positions(self) -> None:
        """Provjeri jesu li OCO nalozi izvršeni (pogođen SL ili TP) i javi rezultat."""
        for sym, pos in list(self.state.positions.items()):
            try:
                ol = self.client.order_list(pos["list_id"])
            except BinanceError as exc:
                log.warning("Ne mogu provjeriti OCO %s: %s", sym, exc)
                continue
            if ol.get("listOrderStatus") != "ALL_DONE":
                continue
            filled: Optional[Dict[str, Any]] = None
            for o in ol.get("orders", []):
                od = self.client.get_order(sym, o["orderId"])
                if od.get("status") == "FILLED":
                    filled = od
            if filled:
                proceeds = float(filled["cummulativeQuoteQty"]) * (1 - self.cfg.fee_rate)
                pl = proceeds - pos["cost"]
                kind = "take-profit" if filled.get("type") == "LIMIT_MAKER" else "stop-loss"
                icon = "🟢" if pl >= 0 else "🔴"
                self.tg.send(f"{icon} Zatvoreno {sym} ({kind}): {pl:+.2f} {self.quote}")
            else:
                self.tg.send(f"ℹ️ {sym}: OCO nalog je otkazan (ručno?). Prestajem pratiti poziciju.")
            del self.state.positions[sym]
        self._save()

    def _save(self) -> None:
        self.state.save(self.state_path)
