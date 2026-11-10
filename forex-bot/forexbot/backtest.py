"""Backtest strategije na povijesnim svijećama.

Pojednostavljenja (namjerno konzervativna):
  * ulaz na otvaranju sljedeće svijeće nakon signala,
  * ako su u istoj svijeći dodirnuti i SL i TP, računa se SL (gubitak),
  * spread se naplaćuje kao trošak na svakom trejdu,
  * proklizavanje (slippage) i swap (noćna kamata) se ne računaju.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .risk import pip_size, position_units, spot_quantity, split_pair
from .strategy import Candle, StrategyParams, compute_indicators, signal_at


@dataclass
class Trade:
    side: str
    entry_time: str
    entry: float
    stop_loss: float
    take_profit: float
    units: float
    exit_time: str = ""
    exit: float = 0.0
    pnl: float = 0.0
    result: str = ""


@dataclass
class BacktestResult:
    instrument: str
    start_balance: float
    end_balance: float
    trades: List[Trade] = field(default_factory=list)
    max_drawdown: float = 0.0  # udio, npr. 0.12 = 12%

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def win_rate(self) -> float:
        return self.wins / len(self.trades) if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    def summary(self) -> str:
        ret = (self.end_balance / self.start_balance - 1) * 100
        return (
            f"=== Backtest {self.instrument} ===\n"
            f"Početni kapital: {self.start_balance:.2f}\n"
            f"Završni kapital: {self.end_balance:.2f} ({ret:+.1f}%)\n"
            f"Broj trejdova:   {len(self.trades)}\n"
            f"Uspješnost:      {self.win_rate * 100:.1f}%\n"
            f"Profit factor:   {self.profit_factor:.2f} (>1.3 je dobro, <1 gubi)\n"
            f"Najveći pad:     {self.max_drawdown * 100:.1f}%"
        )


def _to_account(amount_in_quote: float, instrument: str, price: float, account_currency: str) -> float:
    base, quote = split_pair(instrument)
    if quote == account_currency:
        return amount_in_quote
    if base == account_currency:
        return amount_in_quote / price
    return amount_in_quote  # aproksimacija za križne parove


def run_backtest(
    candles: List[Candle],
    params: StrategyParams,
    instrument: str = "EUR_USD",
    start_balance: float = 500.0,
    risk_per_trade: float = 0.01,
    spread_pips: float = 1.2,
    account_currency: str = "EUR",
    leverage: float = 30.0,
    max_margin_use: float = 0.5,
    spot: bool = False,
    fee_rate: float = 0.0,
    max_position_fraction: float = 0.45,
    qty_step: float = 0.000001,
) -> BacktestResult:
    """spot=True: samo kupnja (bez short-a i poluge), provizija fee_rate po strani (Binance)."""
    ind = compute_indicators(candles, params)
    spread = spread_pips * pip_size(instrument)
    balance = start_balance
    peak = start_balance
    max_dd = 0.0
    trades: List[Trade] = []
    pos: Optional[Trade] = None
    base, quote = split_pair(instrument) if "_" in instrument else (instrument, account_currency)

    for i in range(len(candles)):
        c = candles[i]
        if pos is not None:  # pozicija je otvorena na otvaranju ove ili ranije svijeće
            d = 1 if pos.side == "buy" else -1
            hit_sl = c.low <= pos.stop_loss if d > 0 else c.high >= pos.stop_loss
            hit_tp = c.high >= pos.take_profit if d > 0 else c.low <= pos.take_profit
            exit_price = None
            if hit_sl:
                exit_price, pos.result = pos.stop_loss, "SL"
            elif hit_tp:
                exit_price, pos.result = pos.take_profit, "TP"
            if exit_price is not None:
                if spot:
                    pos.pnl = pos.units * exit_price * (1 - fee_rate) - pos.units * pos.entry * (1 + fee_rate)
                else:
                    move = (exit_price - pos.entry) * d
                    pnl_quote = (move - spread) * pos.units
                    pos.pnl = _to_account(pnl_quote, instrument, exit_price, account_currency)
                pos.exit, pos.exit_time = exit_price, c.time
                balance += pos.pnl
                trades.append(pos)
                pos = None
                peak = max(peak, balance)
                max_dd = max(max_dd, (peak - balance) / peak if peak > 0 else 0)

        if pos is None and balance > 0 and i + 1 < len(candles):
            sig = signal_at(candles, ind, i, params)
            if sig is not None and spot and sig.side != "buy":
                sig = None
            if sig is not None:
                nxt = candles[i + 1]
                entry = nxt.open
                d = sig.direction
                price = entry
                q2a = 1.0 if quote == account_currency else (1.0 / price if base == account_currency else 1.0)
                b2a = 1.0 if base == account_currency else (price if quote == account_currency else 1.0)
                if spot:
                    units = spot_quantity(
                        balance, risk_per_trade, sig.sl_distance, entry, fee_rate,
                        balance * max_position_fraction, qty_step,
                    )
                else:
                    units = position_units(balance, risk_per_trade, sig.sl_distance, q2a, b2a, leverage, max_margin_use)
                if units > 0:
                    pos = Trade(
                        side=sig.side,
                        entry_time=nxt.time,
                        entry=entry,
                        stop_loss=entry - d * sig.sl_distance,
                        take_profit=entry + d * sig.tp_distance,
                        units=units,
                    )

    return BacktestResult(instrument, start_balance, balance, trades, max_dd)


def load_csv(path: Path) -> List[Candle]:
    """CSV sa stupcima: time,open,high,low,close[,volume]"""
    out: List[Candle] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(
                Candle(
                    time=row["time"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row.get("volume") or 0)),
                )
            )
    return out


def save_csv(candles: List[Candle], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.time, c.open, c.high, c.low, c.close, c.volume])
