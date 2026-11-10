"""Strategija: EMA crossover u smjeru trenda, s RSI filterom i ATR stop-lossom.

Pravila (na zatvorenim svijećama):
  KUPI  - brzi EMA presiječe spori EMA prema gore, cijena je iznad trend EMA,
          RSI nije prekupljen (< rsi_buy_max).
  PRODAJ - brzi EMA presiječe spori EMA prema dolje, cijena je ispod trend EMA,
          RSI nije preprodan (> rsi_sell_min).
  Stop-loss = sl_atr * ATR, take-profit = tp_atr * ATR (zadano 1.5 / 3.0 -> omjer 1:2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .indicators import Series, atr, ema, rsi


@dataclass
class Candle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    complete: bool = True


@dataclass
class StrategyParams:
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    sl_atr: float = 1.5
    tp_atr: float = 3.0
    rsi_buy_max: float = 70.0
    rsi_sell_min: float = 30.0

    def min_candles(self) -> int:
        return max(self.ema_trend, self.ema_slow, self.rsi_period + 1, self.atr_period) + 2


@dataclass
class Signal:
    side: str  # "buy" ili "sell"
    price: float  # close svijeće na kojoj je nastao signal
    sl_distance: float
    tp_distance: float
    reason: str

    @property
    def direction(self) -> int:
        return 1 if self.side == "buy" else -1


def compute_indicators(candles: Sequence[Candle], p: StrategyParams) -> Dict[str, Series]:
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    return {
        "fast": ema(closes, p.ema_fast),
        "slow": ema(closes, p.ema_slow),
        "trend": ema(closes, p.ema_trend),
        "rsi": rsi(closes, p.rsi_period),
        "atr": atr(highs, lows, closes, p.atr_period),
    }


def signal_at(
    candles: Sequence[Candle], ind: Dict[str, Series], i: int, p: StrategyParams
) -> Optional[Signal]:
    if i < 1 or i >= len(candles):
        return None
    fast, slow, trend, r, a = ind["fast"], ind["slow"], ind["trend"], ind["rsi"], ind["atr"]
    needed = (fast[i], fast[i - 1], slow[i], slow[i - 1], trend[i], r[i], a[i])
    if any(v is None for v in needed) or a[i] <= 0:
        return None

    close = candles[i].close
    cross_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
    cross_down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
    sl = p.sl_atr * a[i]
    tp = p.tp_atr * a[i]

    if cross_up and close > trend[i] and r[i] < p.rsi_buy_max:
        return Signal("buy", close, sl, tp, f"EMA{p.ema_fast}>EMA{p.ema_slow}, iznad EMA{p.ema_trend}, RSI {r[i]:.0f}")
    if cross_down and close < trend[i] and r[i] > p.rsi_sell_min:
        return Signal("sell", close, sl, tp, f"EMA{p.ema_fast}<EMA{p.ema_slow}, ispod EMA{p.ema_trend}, RSI {r[i]:.0f}")
    return None


def generate_signal(candles: List[Candle], p: StrategyParams) -> Optional[Signal]:
    """Signal na zadnjoj (zatvorenoj) svijeći, ili None."""
    if len(candles) < p.min_candles():
        return None
    ind = compute_indicators(candles, p)
    return signal_at(candles, ind, len(candles) - 1, p)
