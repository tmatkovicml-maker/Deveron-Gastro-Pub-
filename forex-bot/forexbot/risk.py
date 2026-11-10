"""Upravljanje rizikom: veličina pozicije i pomoćne funkcije za valutne parove."""

from __future__ import annotations

import math
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
