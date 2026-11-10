"""Upravljanje rizikom: veličina pozicije i pomoćne funkcije za valutne parove."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Callable, Optional, Tuple


def split_pair(instrument: str) -> Tuple[str, str]:
    base, quote = instrument.split("_")
    return base, quote


def pip_size(instrument: str) -> float:
    return 0.01 if instrument.endswith("_JPY") else 0.0001


def conversion_rate(
    currency: str, account_currency: str, mid_price: Callable[[str], Optional[float]]
) -> Optional[float]:
    """Koliko jedinica valute računa vrijedi 1 jedinica `currency`.

    `mid_price(instrument)` vraća srednju cijenu para ili None ako par ne postoji.
    """
    if currency == account_currency:
        return 1.0
    direct = mid_price(f"{currency}_{account_currency}")
    if direct:
        return direct
    inverse = mid_price(f"{account_currency}_{currency}")
    if inverse:
        return 1.0 / inverse
    return None


def position_units(
    balance: float,
    risk_fraction: float,
    sl_distance: float,
    quote_to_account: float,
    base_to_account: float,
    leverage: float,
    max_margin_use: float,
) -> int:
    """Broj jedinica (bazne valute) tako da gubitak na stop-lossu bude ~risk_fraction računa.

    Dodatno ograničeno tako da potrebna margina ne prijeđe max_margin_use * balance.
    """
    if balance <= 0 or sl_distance <= 0 or quote_to_account <= 0 or base_to_account <= 0:
        return 0
    risk_amount = balance * risk_fraction
    loss_per_unit = sl_distance * quote_to_account
    units_by_risk = math.floor(risk_amount / loss_per_unit)
    margin_per_unit = base_to_account / leverage
    units_by_margin = math.floor(balance * max_margin_use / margin_per_unit)
    return max(0, min(units_by_risk, units_by_margin))


def floor_to_step(value: float, step: float) -> float:
    """Zaokruži prema dolje na dopušteni korak (npr. LOT_SIZE stepSize na Binanceu)."""
    if step <= 0:
        return value
    d_step = Decimal(str(step))
    return float((Decimal(str(value)) // d_step) * d_step)


def spot_quantity(
    equity: float,
    risk_fraction: float,
    sl_distance: float,
    entry: float,
    fee_rate: float,
    max_cost: float,
    step: float,
) -> float:
    """Količina za spot kupnju (bez poluge).

    Gubitak na stop-lossu (uključujući proviziju kupnje i prodaje) ~ risk_fraction * equity,
    a ukupni trošak kupnje ne prelazi max_cost.
    """
    if equity <= 0 or sl_distance <= 0 or entry <= 0 or max_cost <= 0:
        return 0.0
    loss_per_unit = sl_distance + entry * fee_rate * 2
    qty = min(equity * risk_fraction / loss_per_unit, max_cost / (entry * (1 + fee_rate)))
    return max(0.0, floor_to_step(qty, step))


def ceil_to_step(value: float, step: float) -> float:
    """Zaokruži prema gore na dopušteni korak (da nalog ne padne ispod minimuma)."""
    if step <= 0:
        return value
    d_step = Decimal(str(step))
    d = Decimal(str(value))
    q = d // d_step
    if q * d_step < d:
        q += 1
    return float(q * d_step)
