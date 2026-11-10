"""Grid bot: "kupi nisko, prodaj visoko" s malim iznosima.

Kako radi:
  1. Raspon cijene (npr. ±8% oko trenutne) podijeli se na N razina (geometrijski,
     svaka razina je isti postotak iznad prethodne).
  2. Na svim razinama ISPOD trenutne cijene postavi se mali LIMIT nalog za kupnju.
  3. Kad se kupnja na razini i izvrši (cijena je pala), odmah se postavi prodaja
     na razini i+1 (malo više).
  4. Kad se ta prodaja izvrši (cijena je narasla), zarada je zaključana i ponovno
     se postavi kupnja na razini i. Krug se ponavlja dok cijena skače gore-dolje.

Bot nikad ne prodaje ono što nije sam kupio, i svaka prodaja je skuplja od kupnje.
Rizik: ako cijena padne ispod raspona i ostane dolje, držiš kupljeno u minusu.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .binance import BinanceClient, BinanceError
from .config import Config
from .risk import floor_to_step
from .state import State
from .strategy import Candle
from .telegram import Telegram

log = logging.getLogger(__name__)

GRID_HELP = (
    "Komande:\n"
    "/status - cijena, nalozi i zarada grida\n"
    "/pauza - ne postavljaj nove kupnje (prodaje se i dalje izvršavaju)\n"
    "/nastavi - nastavi\n"
    "/zatvori_sve - otkaži sve naloge, prodaj kupljeno i ugasi grid\n"
    "/pomoc - ova poruka"
)


def grid_levels(lower: float, upper: float, n: int) -> List[float]:
    """n+1 cijena od lower do upper, s jednakim postotnim razmakom."""
    ratio = (upper / lower) ** (1.0 / n)
    return [lower * ratio**i for i in range(n + 1)]


def spacing_pct(lower: float, upper: float, n: int) -> float:
    return ((upper / lower) ** (1.0 / n) - 1) * 100


def resolve_range(price: float, cfg: Config) -> Tuple[float, float]:
    if cfg.grid_lower > 0 and cfg.grid_upper > 0:
        return cfg.grid_lower, cfg.grid_upper
    r = cfg.grid_range_pct / 100
    return price * (1 - r), price * (1 + r)


def check_spacing(lower: float, upper: float, n: int, fee_rate: float) -> None:
    sp = spacing_pct(lower, upper, n)
    min_sp = fee_rate * 2 * 100 + 0.3  # provizija kupnje + prodaje + malo zarade
    if sp < min_sp:
        raise ValueError(
            f"Razmak između razina je {sp:.2f}%, a provizije su {fee_rate * 200:.2f}% po krugu. "
            f"Smanji GRID_LEVELS ili povećaj raspon (treba barem {min_sp:.2f}%)."
        )


# --------------------------------------------------------------- simulacija
@dataclass
class GridSimResult:
    symbol: str
    days: float
    start_value: float
    end_value: float
    cycles: int
    grid_profit: float
    hold_value: float  # da si sve samo kupio i držao
    lower: float
    upper: float
    spacing: float
    time_in_range: float

    def summary(self) -> str:
        ret = (self.end_value / self.start_value - 1) * 100
        hold = (self.hold_value / self.start_value - 1) * 100
        per_month = self.cycles / max(self.days / 30, 1e-9)
        return (
            f"=== Grid backtest {self.symbol} ({self.days:.0f} dana) ===\n"
            f"Raspon: {self.lower:.6g} - {self.upper:.6g}, razmak {self.spacing:.2f}%\n"
            f"Cijena u rasponu: {self.time_in_range * 100:.0f}% vremena\n"
            f"Završeni krugovi (kupi->prodaj): {self.cycles} (~{per_month:.1f} mjesečno)\n"
            f"Zarada od krugova: {self.grid_profit:+.2f}\n"
            f"Ukupno: {self.start_value:.2f} -> {self.end_value:.2f} ({ret:+.1f}%)\n"
            f"Usporedba - samo kupi i drži: {hold:+.1f}%"
        )


def simulate_grid(
    candles: List[Candle],
    lower: float,
    upper: float,
    n: int,
    order_quote: float,
    fee_rate: float,
    start_quote: float,
    symbol: str = "",
) -> GridSimResult:
    levels = grid_levels(lower, upper, n)
    price0 = candles[0].open
    cash = start_quote
    buys: set = set()
    sells: Dict[int, Tuple[float, float]] = {}  # razina -> (količina, trošak)
    cycles = 0
    profit = 0.0
    in_range = 0

    for i in sorted((i for i in range(n) if levels[i] < price0), reverse=True):
        if cash >= order_quote:
            cash -= order_quote
            buys.add(i)

    for c in candles:
        if lower <= c.close <= upper:
            in_range += 1
        new_sells: Dict[int, Tuple[float, float]] = {}
        for i in sorted(buys, reverse=True):
            if c.low <= levels[i]:
                buys.discard(i)
                qty = order_quote / levels[i] * (1 - fee_rate)
                new_sells[i + 1] = (qty, order_quote)
        for j in sorted(sells):
            if c.high >= levels[j]:
                qty, cost = sells.pop(j)
                proceeds = qty * levels[j] * (1 - fee_rate)
                profit += proceeds - cost
                cash += proceeds
                cycles += 1
                if cash >= order_quote:
                    cash -= order_quote
                    buys.add(j - 1)
        sells.update(new_sells)

    last = candles[-1].close
    held = sum(q for q, _ in sells.values())
    end_value = cash + len(buys) * order_quote + held * last
    hold_value = start_quote / price0 * (1 - fee_rate) * last
    days = len(candles) and _days_between(candles[0].time, candles[-1].time)
    return GridSimResult(
        symbol, days, start_quote, end_value, cycles, profit, hold_value,
        lower, upper, spacing_pct(lower, upper, n), in_range / len(candles),
    )


def _days_between(t0: str, t1: str) -> float:
    from .bot import parse_time

    try:
        return (parse_time(t1) - parse_time(t0)).total_seconds() / 86400
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- live bot
class GridBot:
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
        self.symbol = cfg.symbols[0]
        self.info = client.symbol_info(self.symbol)
        self.base, self.quote = self.info["base"], self.info["quote"]
        self.state_path = cfg.data_dir / "state_grid.json"
        self.state = State.load(self.state_path)
        self._running = True

    @property
    def g(self) -> Dict[str, Any]:
        return self.state.grid

    # ----------------------------------------------------------------- loop
    def run_forever(self) -> None:
        mode = "TESTNET (virtualni novac)" if self.cfg.binance_testnet else "PRAVI NOVAC"
        if self.cfg.dry_run:
            mode += ", DRY RUN"
        self.tg.send(f"🤖 Grid bot pokrenut ({mode}) za {self.symbol}.\n\n{GRID_HELP}")
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

    def handle_commands(self) -> None:
        for cmd in self.tg.poll_commands():
            if cmd in ("/status", "/start"):
                self.tg.send(self.status_text())
            elif cmd == "/pauza":
                self.state.paused = True
                self._save()
                self.tg.send("⏸ Pauzirano - neću postavljati nove kupnje. Postojeće prodaje ostaju.")
            elif cmd == "/nastavi":
                self.state.paused = False
                self._save()
                self.tg.send("▶️ Nastavljam.")
            elif cmd == "/zatvori_sve":
                self.tg.send(self.close_all())
            else:
                self.tg.send(GRID_HELP)

    # ---------------------------------------------------------------- setup
    def init_grid(self) -> None:
        price = self.client.book(self.symbol)["ask"]
        lower, upper = resolve_range(price, self.cfg)
        n = self.cfg.grid_levels
        check_spacing(lower, upper, n, self.cfg.fee_rate)
        min_order = self.info["min_notional"] * 1.05
        if self.cfg.grid_order_quote < min_order:
            raise ValueError(
                f"GRID_ORDER_QUOTE={self.cfg.grid_order_quote} je ispod Binance minimuma "
                f"({self.info['min_notional']} {self.quote}). Povećaj ga."
            )
        levels = grid_levels(lower, upper, n)
        self.state.grid = {
            "symbol": self.symbol,
            "lower": lower,
            "upper": upper,
            "n": n,
            "order_quote": self.cfg.grid_order_quote,
            "levels": levels,
            "orders": {},
            "pending": [],
            "profit": 0.0,
            "cycles": 0,
            "started": self.now().isoformat(),
            "range_note": "",
            "dust": 0.0,
        }
        free = self.client.balances().get(self.quote, {}).get("free", 0.0)
        placed = 0
        for i in sorted((i for i in range(n) if levels[i] < price * 0.999), reverse=True):
            if free < self.cfg.grid_order_quote:
                break
            if self._place("BUY", i, self.cfg.grid_order_quote / levels[i], self.cfg.grid_order_quote):
                free -= self.cfg.grid_order_quote
                placed += 1
        self._save()
        self.tg.send(
            f"🕸 Grid postavljen za {self.symbol}\n"
            f"Raspon {lower:.6g} - {upper:.6g} ({n} razina, razmak {spacing_pct(lower, upper, n):.2f}%)\n"
            f"Trenutna cijena {price:.6g}\n"
            f"Postavljeno {placed} kupnji po {self.cfg.grid_order_quote:g} {self.quote} ispod cijene.\n"
            f"Kad cijena padne do neke razine, kupit ću; kad zatim naraste za jednu razinu, prodat ću."
        )

    def _place(self, side: str, level: int, qty: float, cost: float) -> bool:
        price = self.g["levels"][level]
        qty = floor_to_step(qty, self.info["step"])
        if qty < self.info["min_qty"] or qty * price < self.info["min_notional"]:
            log.warning("Nalog %s na razini %s je premali (%s)", side, level, qty)
            return False
        if self.cfg.dry_run:
            oid = f"dry-{side}-{level}-{int(time.time() * 1000)}"
        else:
            try:
                oid = str(self.client.limit_order(self.symbol, side, qty, price)["orderId"])
            except BinanceError as exc:
                log.error("Nalog %s @ %s nije uspio: %s", side, price, exc)
                self.g["pending"].append({"side": side, "level": level, "qty": qty, "cost": cost})
                return False
        self.g["orders"][oid] = {"side": side, "level": level, "qty": qty, "cost": cost}
        return True

    # ---------------------------------------------------------------- check
    def check_once(self) -> None:
        if not self.g:
            if self.state.paused:
                return
            try:
                self.init_grid()
            except ValueError as exc:
                self.state.grid = {}
                self.state.paused = True
                self._save()
                self.tg.send(f"❌ Grid nije postavljen: {exc}\nIspravi .env, pa pošalji /nastavi.")
            return
        if self.g.get("symbol") != self.symbol:
            log.error("Spremljeni grid je za %s, a postavke za %s. Pošalji /zatvori_sve.", self.g.get("symbol"), self.symbol)
            return

        self._retry_pending()
        if not self.cfg.dry_run:
            open_ids = {str(o["orderId"]) for o in self.client.open_orders(self.symbol)}
            for oid, rec in list(self.g["orders"].items()):
                if oid in open_ids:
                    continue
                od = self.client.get_order(self.symbol, int(oid))
                if od.get("status") in ("NEW", "PARTIALLY_FILLED"):
                    continue
                del self.g["orders"][oid]
                executed = float(od.get("executedQty", 0))
                if executed <= 0:
                    self.tg.send(f"ℹ️ Nalog {rec['side']} na razini {rec['level']} je otkazan (ručno?).")
                    continue
                self._on_fill(rec, executed, float(od.get("cummulativeQuoteQty", 0)), int(oid))
        self._range_notice()
        self._save()

    def _base_commission(self, order_id: Optional[int], executed: float) -> float:
        """Koliko je provizije naplaćeno u kupljenom coinu (0 ako se plaća u BNB-u)."""
        if order_id is None:
            return executed * self.cfg.fee_rate
        try:
            trades = self.client.order_trades(self.symbol, order_id)
            return sum(float(t["commission"]) for t in trades if t.get("commissionAsset") == self.base)
        except (BinanceError, KeyError, ValueError) as exc:
            log.warning("Ne mogu dohvatiti proviziju naloga %s: %s", order_id, exc)
            return executed * self.cfg.fee_rate

    def _on_fill(self, rec: Dict[str, Any], executed: float, quote_amount: float, order_id: Optional[int] = None) -> None:
        levels = self.g["levels"]
        lvl = rec["level"]
        if rec["side"] == "BUY":
            net = executed - self._base_commission(order_id, executed)
            sell_qty = floor_to_step(net, self.info["step"])
            # ostatak manji od koraka ("prašina") ostaje u novčaniku i prodaje se na kraju
            self.g["dust"] = self.g.get("dust", 0.0) + max(0.0, net - sell_qty)
            cost = quote_amount * (sell_qty / net) if net > 0 else quote_amount
            sell_lvl = lvl + 1
            self._place("SELL", sell_lvl, sell_qty, cost)
            self.tg.send(
                f"🟢 KUPIO {executed:g} {self.base} @ {levels[lvl]:.6g} ({quote_amount:.2f} {self.quote})\n"
                f"Cijena je pala do razine {lvl}. Postavio sam prodaju @ {levels[sell_lvl]:.6g} "
                f"(+{spacing_pct(self.g['lower'], self.g['upper'], self.g['n']):.2f}%)."
            )
        else:
            proceeds = quote_amount * (1 - self.cfg.fee_rate)
            pl = proceeds - rec["cost"]
            self.g["profit"] += pl
            self.g["cycles"] += 1
            msg = (
                f"💰 PRODAO {executed:g} {self.base} @ {levels[lvl]:.6g}\n"
                f"Zarada ovog kruga: {pl:+.3f} {self.quote} (nakon provizija)\n"
                f"Ukupno: {self.g['profit']:+.2f} {self.quote} u {self.g['cycles']} krugova."
            )
            if not self.state.paused:
                buy_lvl = lvl - 1
                oq = self.g["order_quote"]
                self._place("BUY", buy_lvl, oq / levels[buy_lvl], oq)
                msg += f"\nPonovno čekam kupnju @ {levels[buy_lvl]:.6g}."
            self.tg.send(msg)

    def _retry_pending(self) -> None:
        pending, self.g["pending"] = self.g.get("pending", []), []
        for p in pending:
            if p["side"] == "BUY" and self.state.paused:
                continue
            self._place(p["side"], p["level"], p["qty"], p["cost"])

    def _range_notice(self) -> None:
        price = self.client.book(self.symbol)["bid"]
        note = "below" if price < self.g["lower"] else "above" if price > self.g["upper"] else ""
        if note and note != self.g.get("range_note"):
            if note == "below":
                self.tg.send(
                    f"⚠️ Cijena {price:.6g} je pala ispod raspona ({self.g['lower']:.6g}). "
                    "Sve kupnje su vjerojatno izvršene; čekam da se cijena vrati. "
                    "Ako želiš izaći s gubitkom: /zatvori_sve"
                )
            else:
                self.tg.send(
                    f"🚀 Cijena {price:.6g} je iznad raspona ({self.g['upper']:.6g}). Sve je prodano sa zaradom; "
                    "za novi raspon pošalji /zatvori_sve pa ponovno pokreni bota."
                )
        self.g["range_note"] = note

    # --------------------------------------------------------------- status
    def status_text(self) -> str:
        if not self.g:
            return "Grid nije aktivan." + (" (pauzirano)" if self.state.paused else "")
        price = self.client.book(self.symbol)["bid"]
        buys = sorted((r["level"] for r in self.g["orders"].values() if r["side"] == "BUY"))
        sells = [r for r in self.g["orders"].values() if r["side"] == "SELL"]
        held = sum(r["qty"] for r in sells)
        held_cost = sum(r["cost"] for r in sells)
        unreal = held * price * (1 - self.cfg.fee_rate) - held_cost
        lv = self.g["levels"]
        return (
            f"🕸 Grid {self.symbol} | cijena {price:.6g}\n"
            f"Raspon {self.g['lower']:.6g} - {self.g['upper']:.6g}\n"
            f"Čeka kupnju: {len(buys)} naloga" + (f" (najbliža @ {lv[buys[-1]]:.6g})" if buys else "") + "\n"
            f"Čeka prodaju: {len(sells)} naloga, držim {held:g} {self.base} (trenutno {unreal:+.2f} {self.quote})\n"
            f"Zarada od krugova: {self.g['profit']:+.2f} {self.quote} ({self.g['cycles']} krugova)\n"
            f"Status: {'⏸ pauzirano' if self.state.paused else '▶️ aktivan'}"
        )

    def close_all(self) -> str:
        if not self.g:
            return "Grid nije aktivan."
        held = 0.0
        for oid, rec in list(self.g["orders"].items()):
            if not self.cfg.dry_run:
                try:
                    self.client.cancel_order(self.symbol, int(oid))
                except BinanceError as exc:
                    log.warning("Otkazivanje %s: %s", oid, exc)
            if rec["side"] == "SELL":
                held += rec["qty"]
        held += sum(p["qty"] for p in self.g.get("pending", []) if p["side"] == "SELL")
        held += self.g.get("dust", 0.0)
        msg = f"Otkazani svi nalozi. Zarada od krugova: {self.g['profit']:+.2f} {self.quote}."
        held = floor_to_step(held, self.info["step"])
        if held > 0 and not self.cfg.dry_run:
            try:
                res = self.client.market_order(self.symbol, "SELL", held, self.info["step"])
                msg += f"\nProdao preostalih {held:g} {self.base} za {float(res.get('cummulativeQuoteQty', 0)):.2f} {self.quote}."
            except BinanceError as exc:
                msg += f"\n❌ Prodaja {held:g} {self.base} nije uspjela ({exc}) - prodaj ručno na Binanceu."
        self.state.grid = {}
        self.state.paused = True
        self._save()
        return msg + "\nGrid je ugašen. Za novi: /nastavi (postavlja se oko trenutne cijene)."

    def _save(self) -> None:
        self.state.save(self.state_path)
