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

from . import reports
from .binance import BinanceClient, BinanceError
from .config import Config
from .risk import ceil_to_step, floor_to_step
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
    "/izvjestaj - izvještaj od početka (stiže i sam svake nedjelje navečer)\n"
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
    recenters: int = 0

    def summary(self) -> str:
        ret = (self.end_value / self.start_value - 1) * 100
        hold = (self.hold_value / self.start_value - 1) * 100
        per_month = self.cycles / max(self.days / 30, 1e-9)
        return (
            f"=== Grid backtest {self.symbol} ({self.days:.0f} dana) ===\n"
            f"Raspon{' (zadnji)' if self.recenters else ''}: {self.lower:.6g} - {self.upper:.6g}, razmak {self.spacing:.2f}%\n"
            + (f"Automatski pomaknut prema gore: {self.recenters} puta\n" if self.recenters else "")
            + f"Cijena u rasponu: {self.time_in_range * 100:.0f}% vremena\n"
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
    recenter_pct: Optional[float] = None,
) -> GridSimResult:
    """recenter_pct: ako je zadan, raspon se pomiče prema gore (±recenter_pct oko cijene)
    kad cijena izađe iznad raspona, a nema kupljenog coina - isto kao live bot."""
    levels = grid_levels(lower, upper, n)
    price0 = candles[0].open
    cash = start_quote
    buys: set = set()
    sells: Dict[int, Tuple[float, float]] = {}  # razina -> (količina, trošak)
    cycles = 0
    profit = 0.0
    in_range = 0
    recenters = 0

    def place_buys(price: float) -> None:
        nonlocal cash
        for i in sorted((i for i in range(n) if levels[i] < price * 0.999), reverse=True):
            if cash >= order_quote:
                cash -= order_quote
                buys.add(i)

    place_buys(price0)

    for c in candles:
        if recenter_pct and not sells and c.close > upper:
            cash += len(buys) * order_quote
            buys.clear()
            r = recenter_pct / 100
            lower, upper = c.close * (1 - r), c.close * (1 + r)
            levels = grid_levels(lower, upper, n)
            place_buys(c.close)
            recenters += 1
            continue
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
        lower, upper, spacing_pct(lower, upper, n), in_range / len(candles), recenters,
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
        self._last_error = ""

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
            elif cmd in ("/izvjestaj", "/izvještaj"):
                price = self.client.book(self.symbol)["bid"]
                if not self.state.report:
                    self._reports(price)
                self.tg.send(self.report_text(price))
            else:
                self.tg.send(GRID_HELP)

    # ---------------------------------------------------------------- setup
    def init_grid(self, carry: Optional[Dict[str, Any]] = None) -> None:
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
            "recenters": 0,
        }
        if carry:
            self.state.grid.update(carry)
        free_start = self.client.balances().get(self.quote, {}).get("free", 0.0)
        free = free_start
        placed = 0
        self._last_error = ""
        log.info("Grid %s: cijena %s, slobodno %.2f %s", self.symbol, price, free, self.quote)
        for i in sorted((i for i in range(n) if levels[i] < price * 0.999), reverse=True):
            qty = ceil_to_step(self.cfg.grid_order_quote / levels[i], self.info["step"])
            cost = qty * levels[i]
            if free < cost:
                if placed == 0:
                    self._last_error = f"premalo slobodnog {self.quote} u Spotu ({free:.2f}, treba {cost:.2f} po nalogu)"
                break
            if self._place("BUY", i, qty, cost):
                free -= cost
                placed += 1
        self._save()
        title = "🔼 Raspon automatski pomaknut prema gore" if carry else "🕸 Grid postavljen"
        msg = (
            f"{title} za {self.symbol}\n"
            f"Raspon {lower:.6g} - {upper:.6g} ({n} razina, razmak {spacing_pct(lower, upper, n):.2f}%)\n"
            f"Trenutna cijena {price:.6g} | slobodno {free_start:.2f} {self.quote}\n"
            f"Postavljeno {placed} kupnji po ~{self.cfg.grid_order_quote:g} {self.quote} ispod cijene.\n"
            f"Kad cijena padne do neke razine, kupit ću; kad zatim naraste za jednu razinu, prodat ću."
        )
        if placed == 0:
            reason = self._last_error or "nepoznat razlog"
            msg += (
                f"\n\n⚠️ Nijedna kupnja nije postavljena: {reason}.\n"
                "Kad ispraviš, pošalji /zatvori_sve pa /nastavi."
            )
        self.tg.send(msg)

    def _place(self, side: str, level: int, qty: float, cost: float) -> bool:
        price = self.g["levels"][level]
        qty = floor_to_step(qty, self.info["step"])
        if qty < self.info["min_qty"] or qty * price < self.info["min_notional"]:
            self._last_error = (
                f"nalog {side} je premali ({qty:g} {self.base} = {qty * price:.2f} {self.quote}, "
                f"Binance minimum {self.info['min_notional']:g}) - povećaj GRID_ORDER_QUOTE"
            )
            log.warning(self._last_error)
            self._notify_error()
            return False
        if self.cfg.dry_run:
            oid = f"dry-{side}-{level}-{int(time.time() * 1000)}"
        else:
            try:
                oid = str(self.client.limit_order(self.symbol, side, qty, price)["orderId"])
            except BinanceError as exc:
                log.error("Nalog %s @ %s nije uspio: %s", side, price, exc)
                self.g["pending"].append({"side": side, "level": level, "qty": qty, "cost": cost})
                self._last_error = str(exc)
                self._notify_error()
                return False
        self.g["orders"][oid] = {"side": side, "level": level, "qty": qty, "cost": cost}
        log.info("Postavljen %s %s %s @ %s", side, qty, self.base, price)
        self.g["last_error"] = ""
        return True

    def _notify_error(self) -> None:
        """Javi grešku na Telegram, ali istu grešku samo jednom."""
        if self.g.get("last_error") != self._last_error:
            self.g["last_error"] = self._last_error
            self.tg.send(f"❌ Nalog nije uspio: {self._last_error}\nPokušavam ponovno svakih {self.cfg.poll_seconds} s.")

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
            if self.g:
                self._reports(self.client.book(self.symbol)["bid"])
                self._save()
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
        price = self.client.book(self.symbol)["bid"]
        self._reports(price)
        if self._maybe_recenter(price):
            self._save()
            return
        self._range_notice(price)
        self._save()

    # ------------------------------------------------------------ izvještaji
    def _account_value(self, price: float) -> float:
        bal = self.client.balances()
        q = bal.get(self.quote, {})
        b = bal.get(self.base, {})
        return q.get("free", 0.0) + q.get("locked", 0.0) + (b.get("free", 0.0) + b.get("locked", 0.0)) * price

    def _held(self, price: float) -> Tuple[float, float]:
        sells = [r for r in self.g.get("orders", {}).values() if r["side"] == "SELL"]
        held = sum(r["qty"] for r in sells)
        unreal = held * price * (1 - self.cfg.fee_rate) - sum(r["cost"] for r in sells)
        return held, unreal

    def report_text(self, price: float) -> str:
        held, unreal = self._held(price)
        return reports.weekly_text(
            self.state.report, self.now(), self._account_value(price), price, held, unreal,
            self.symbol, self.base, self.quote,
        )

    def _reports(self, price: float) -> None:
        now = self.now()
        r = self.state.report
        today = now.strftime("%Y-%m-%d")
        due = reports.last_scheduled(now, self.cfg.report_weekday, self.cfg.report_hour_utc)
        weekly_due = bool(r) and datetime.fromisoformat(r["last_weekly"]) < due
        if r and r.get("last_daily") == today and not weekly_due:
            return
        value = self._account_value(price)
        if not r:
            r = self.state.report = reports.new_baseline(now, value, price)
        if r.get("last_daily") != today:
            held, _ = self._held(price)
            reports.append_daily(self.cfg.data_dir / "povijest.csv", {
                "datum": today,
                "cijena": round(price, 2),
                "vrijednost": round(value, 2),
                "krugova_ukupno": r["cycles_total"],
                "zarada_krugova": round(r["profit_total"], 4),
                "drzim": held,
            })
            r["last_daily"] = today
        if weekly_due:
            self.tg.send(self.report_text(price))
            r.update(
                week_start=now.isoformat(), week_value=value,
                week_cycles=r["cycles_total"], week_profit=r["profit_total"], last_weekly=now.isoformat(),
            )

    def _can_recenter(self) -> bool:
        return self.cfg.grid_auto_recenter and not (self.cfg.grid_lower > 0 and self.cfg.grid_upper > 0)

    def _maybe_recenter(self, price: float) -> bool:
        """Cijena iznad raspona i ništa ne držimo -> novi raspon oko trenutne cijene."""
        if not self._can_recenter() or self.state.paused or price <= self.g["upper"]:
            return False
        if any(r["side"] == "SELL" for r in self.g["orders"].values()):
            return False
        if any(p["side"] == "SELL" for p in self.g.get("pending", [])):
            return False
        for oid, rec in list(self.g["orders"].items()):
            if not self.cfg.dry_run:
                try:
                    res = self.client.cancel_order(self.symbol, int(oid))
                except BinanceError as exc:
                    # nalog se možda upravo izvršio - obradi ga i pokušaj kasnije
                    log.warning("Otkazivanje %s nije uspjelo (%s), provjeravam nalog", oid, exc)
                    od = self.client.get_order(self.symbol, int(oid))
                    if od.get("status") == "FILLED":
                        del self.g["orders"][oid]
                        self._on_fill(rec, float(od["executedQty"]), float(od["cummulativeQuoteQty"]), int(oid))
                    return False
                executed = float((res or {}).get("executedQty", 0) or 0)
                del self.g["orders"][oid]
                if executed > 0:  # djelomično izvršen prije otkazivanja
                    self._on_fill(rec, executed, float(res.get("cummulativeQuoteQty", 0)), int(oid))
                    return False
            else:
                del self.g["orders"][oid]
        self.g["pending"] = []
        carry = {
            "profit": self.g.get("profit", 0.0),
            "cycles": self.g.get("cycles", 0),
            "dust": self.g.get("dust", 0.0),
            "recenters": self.g.get("recenters", 0) + 1,
            "started": self.g.get("started", self.now().isoformat()),
        }
        log.info("Cijena %s iznad raspona, pomičem raspon", price)
        self.state.grid = {}
        try:
            self.init_grid(carry=carry)
        except ValueError as exc:
            self.state.paused = True
            self.tg.send(f"❌ Novi raspon nije postavljen: {exc}\nIspravi .env, pa pošalji /nastavi.")
        return True

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
            if self.state.report:
                self.state.report["cycles_total"] += 1
                self.state.report["profit_total"] += pl
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
        ok = 0
        for p in pending:
            if p["side"] == "BUY" and self.state.paused:
                self.g["pending"].append(p)
                continue
            if self._place(p["side"], p["level"], p["qty"], p["cost"]):
                ok += 1
        if ok:
            self.tg.send(f"✅ Postavljeno {ok} naloga koji ranije nisu uspjeli.")

    def _range_notice(self, price: float) -> None:
        note = "below" if price < self.g["lower"] else "above" if price > self.g["upper"] else ""
        if note and note != self.g.get("range_note"):
            if note == "below":
                self.tg.send(
                    f"⚠️ Cijena {price:.6g} je pala ispod raspona ({self.g['lower']:.6g}). "
                    "Sve kupnje su vjerojatno izvršene; čekam da se cijena vrati. "
                    "Ako želiš izaći s gubitkom: /zatvori_sve"
                )
            elif not self._can_recenter():
                self.tg.send(
                    f"🚀 Cijena {price:.6g} je iznad raspona ({self.g['upper']:.6g}). "
                    "Za novi raspon pošalji /zatvori_sve pa /nastavi."
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
            f"Raspon {self.g['lower']:.6g} - {self.g['upper']:.6g}"
            + (f" (pomaknut {self.g['recenters']}x)" if self.g.get("recenters") else "")
            + "\n"
            f"Čeka kupnju: {len(buys)} naloga" + (f" (najbliža @ {lv[buys[-1]]:.6g})" if buys else "") + "\n"
            f"Čeka prodaju: {len(sells)} naloga, držim {held:g} {self.base} (trenutno {unreal:+.2f} {self.quote})\n"
            f"Zarada od krugova: {self.g['profit']:+.2f} {self.quote} ({self.g['cycles']} krugova)\n"
            + (f"Nalozi na čekanju (nisu uspjeli): {len(self.g['pending'])}\n" if self.g.get("pending") else "")
            + (f"Zadnja greška: {self.g['last_error']}\n" if self.g.get("last_error") else "")
            + f"Status: {'⏸ pauzirano' if self.state.paused else '▶️ aktivan'}"
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
