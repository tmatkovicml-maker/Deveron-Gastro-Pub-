"""Glavna petlja bota: prati tržište, otvara trejdove po signalu, javlja na Telegram."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .config import Config
from .oanda import OandaClient, OandaError
from .risk import conversion_rate, pip_size, position_units, split_pair
from .state import State
from .strategy import Candle, Signal, generate_signal
from .telegram import Telegram

log = logging.getLogger(__name__)

HELP = (
    "Komande:\n"
    "/status - stanje računa i otvoreni trejdovi\n"
    "/pauza - ne otvaraj nove trejdove\n"
    "/nastavi - nastavi trgovati\n"
    "/zatvori_sve - zatvori sve trejdove i pauziraj\n"
    "/pomoc - ova poruka"
)


def parse_time(value: str) -> datetime:
    # OANDA: 2024-01-02T10:00:00.000000000Z -> skrati nanosekunde
    value = value.rstrip("Z")
    if "." in value:
        head, frac = value.split(".", 1)
        value = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class Bot:
    def __init__(
        self,
        cfg: Config,
        client: OandaClient,
        telegram: Telegram,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.cfg = cfg
        self.client = client
        self.tg = telegram
        self.now = now
        self.state_path = cfg.data_dir / "state.json"
        self.state = State.load(self.state_path)
        self._running = True

    # ----------------------------------------------------------------- loop
    def run_forever(self) -> None:
        mode = "DEMO" if self.cfg.oanda_env == "practice" else "PRAVI NOVAC"
        if self.cfg.dry_run:
            mode += ", DRY RUN (bez naloga)"
        self.tg.send(f"🤖 Forex bot pokrenut ({mode}).\nParovi: {', '.join(self.cfg.instruments)}\n\n{HELP}")
        while self._running:
            try:
                self.handle_commands()
                self.check_once()
            except OandaError as exc:
                log.error("OANDA greška: %s", exc)
            except Exception:  # bot se ne smije srušiti zbog jedne greške
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
                self.tg.send("⏸ Pauzirano - neću otvarati nove trejdove. Otvoreni ostaju sa svojim SL/TP.")
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

    def status_text(self) -> str:
        acc = self.client.account_summary()
        ccy = acc.get("currency", "")
        lines = [
            f"💰 Stanje: {float(acc['balance']):.2f} {ccy}",
            f"📈 NAV: {float(acc['NAV']):.2f} {ccy} (nerealizirano {float(acc['unrealizedPL']):+.2f})",
            f"Status: {'⏸ pauzirano' if self.state.paused else '▶️ aktivan'}"
            + (" | dnevni limit gubitka dosegnut" if self.state.daily_limit_hit else ""),
        ]
        trades = self.client.open_trades()
        if trades:
            lines.append("Otvoreni trejdovi:")
            for t in trades:
                units = int(float(t["currentUnits"]))
                side = "KUPI" if units > 0 else "PRODAJ"
                lines.append(
                    f" • {t['instrument']} {side} {abs(units)} @ {t['price']} "
                    f"({float(t.get('unrealizedPL', 0)):+.2f} {ccy})"
                )
        else:
            lines.append("Nema otvorenih trejdova.")
        return "\n".join(lines)

    def close_all(self) -> str:
        trades = self.client.open_trades()
        if not trades:
            return "Nema otvorenih trejdova. Bot je pauziran (/nastavi za nastavak)."
        results = []
        for t in trades:
            try:
                self.client.close_trade(t["id"])
                results.append(f"✅ zatvoren {t['instrument']} #{t['id']}")
            except OandaError as exc:
                results.append(f"❌ {t['instrument']} #{t['id']}: {exc}")
        return "\n".join(results) + "\nBot je pauziran (/nastavi za nastavak)."

    # ---------------------------------------------------------------- check
    def check_once(self) -> None:
        acc = self.client.account_summary()
        nav = float(acc["NAV"])
        balance = float(acc["balance"])
        ccy = acc["currency"]

        self._update_day(nav)
        trades = self.client.open_trades()
        self._report_closed_trades(trades, ccy)

        if self.state.paused:
            return
        if self._daily_limit_reached(nav, ccy):
            return

        open_instruments = {t["instrument"] for t in trades}
        open_count = len(trades)
        for inst in self.cfg.instruments:
            if open_count >= self.cfg.max_open_trades:
                break
            if inst in open_instruments:
                continue
            candles = self._fresh_completed_candles(inst)
            if candles is None:
                continue
            signal = generate_signal(candles, self.cfg.strategy)
            if signal is None:
                continue
            log.info("Signal %s %s: %s", inst, signal.side, signal.reason)
            if self.execute(inst, signal, balance, ccy):
                open_count += 1
        self._save()

    def _update_day(self, nav: float) -> None:
        today = self.now().strftime("%Y-%m-%d")
        if self.state.day != today:
            self.state.day = today
            self.state.day_start_nav = nav
            self.state.daily_limit_hit = False
            self._save()

    def _daily_limit_reached(self, nav: float, ccy: str) -> bool:
        start = self.state.day_start_nav
        if start <= 0 or nav > start * (1 - self.cfg.daily_loss_limit):
            return False
        if not self.state.daily_limit_hit:
            self.state.daily_limit_hit = True
            self._save()
            self.tg.send(
                f"🛑 Dnevni limit gubitka dosegnut ({nav - start:+.2f} {ccy}). "
                "Danas više ne otvaram nove trejdove."
            )
        return True

    def _fresh_completed_candles(self, inst: str) -> Optional[List[Candle]]:
        """Zatvorene svijeće, ali samo ako je zadnja nova i još je nismo obradili."""
        count = self.cfg.strategy.min_candles() + 300  # dovoljno za stabilan EMA
        candles = [c for c in self.client.candles(inst, self.cfg.granularity, count=count) if c.complete]
        if not candles:
            return None
        last = candles[-1]
        if self.state.last_candle.get(inst) == last.time:
            return None
        self.state.last_candle[inst] = last.time
        age = (self.now() - parse_time(last.time)).total_seconds()
        # svijeća je zatvorena granularity sekundi nakon otvaranja; prihvati unutar 10 min
        if age > self.cfg.granularity_seconds + 600:
            log.debug("%s: zadnja svijeća je stara (%ss), preskačem", inst, int(age))
            return None
        return candles

    # -------------------------------------------------------------- execute
    def execute(self, inst: str, signal: Signal, balance: float, ccy: str) -> bool:
        price = self.client.pricing([inst]).get(inst)
        if not price or not price["tradeable"]:
            log.info("%s trenutno nije moguće trgovati", inst)
            return False
        spread_pips = (price["ask"] - price["bid"]) / pip_size(inst)
        if spread_pips > self.cfg.max_spread_pips:
            self.tg.send(f"⚠️ {inst}: signal {signal.side}, ali spread {spread_pips:.1f} pipa je prevelik - preskačem.")
            return False

        d = signal.direction
        entry = price["ask"] if d > 0 else price["bid"]
        stop_loss = entry - d * signal.sl_distance
        take_profit = entry + d * signal.tp_distance

        base, quote = split_pair(inst)
        cache: Dict[str, Optional[float]] = {}

        def mid(name: str) -> Optional[float]:
            if name == inst:
                return (price["bid"] + price["ask"]) / 2
            if name not in cache:
                cache[name] = self.client.mid_price(name)
            return cache[name]

        quote_to_acc = conversion_rate(quote, ccy, mid)
        base_to_acc = conversion_rate(base, ccy, mid)
        if not quote_to_acc or not base_to_acc:
            log.error("Ne mogu preračunati %s u %s", inst, ccy)
            return False

        units = position_units(
            balance,
            self.cfg.risk_per_trade,
            signal.sl_distance,
            quote_to_acc,
            base_to_acc,
            self.cfg.leverage,
            self.cfg.max_margin_use,
        )
        if units < 1:
            log.info("%s: premala pozicija za zadani rizik", inst)
            return False

        risk_amt = units * signal.sl_distance * quote_to_acc
        reward_amt = units * signal.tp_distance * quote_to_acc
        side_hr = "KUPI" if d > 0 else "PRODAJ"
        info = self.client.instrument_info(inst)
        precision = int(info.get("displayPrecision", 5))
        summary = (
            f"{inst} {side_hr} {units} jedinica @ ~{entry:.{precision}f}\n"
            f"SL {stop_loss:.{precision}f} (rizik ~{risk_amt:.2f} {ccy}) | "
            f"TP {take_profit:.{precision}f} (cilj ~{reward_amt:.2f} {ccy})\n"
            f"Razlog: {signal.reason}"
        )

        if self.cfg.dry_run:
            self.tg.send("🧪 [DRY RUN] " + summary)
            return True

        try:
            fill = self.client.market_order(inst, d * units, stop_loss, take_profit, precision)
        except OandaError as exc:
            self.tg.send(f"❌ Nalog {inst} nije uspio: {exc}")
            return False
        trade_id = (fill.get("tradeOpened") or {}).get("tradeID")
        if trade_id and trade_id not in self.state.known_trades:
            self.state.known_trades.append(trade_id)
        self.tg.send(f"✅ Otvoren trejd #{trade_id}\n{summary}")
        return True

    def _report_closed_trades(self, open_trades: List[dict], ccy: str) -> None:
        open_ids = {t["id"] for t in open_trades}
        for tid in list(self.state.known_trades):
            if tid in open_ids:
                continue
            try:
                t = self.client.trade(tid)
                pl = float(t.get("realizedPL", 0))
                icon = "🟢" if pl >= 0 else "🔴"
                self.tg.send(f"{icon} Zatvoren trejd #{tid} {t.get('instrument', '')}: {pl:+.2f} {ccy}")
            except OandaError as exc:
                log.warning("Ne mogu dohvatiti trejd %s: %s", tid, exc)
            self.state.known_trades.remove(tid)
        for tid in open_ids:
            if tid not in self.state.known_trades:
                self.state.known_trades.append(tid)
        self._save()

    def _save(self) -> None:
        self.state.save(self.state_path)
