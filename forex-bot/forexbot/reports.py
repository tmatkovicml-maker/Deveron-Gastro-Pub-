"""Tjedni izvještaji na Telegram i dnevna povijest u CSV-u (data/povijest.csv).

Brojke "od početka" vrijede za cijeli život bota, preko svih gridova
(i nakon /zatvori_sve ili automatskog pomicanja raspona).
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict


def last_scheduled(now: datetime, weekday: int, hour: int) -> datetime:
    """Zadnji zakazani trenutak (dan u tjednu + sat, UTC) koji je <= now."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate -= timedelta(days=(now.weekday() - weekday) % 7)
    if candidate > now:
        candidate -= timedelta(days=7)
    return candidate


def _pct(new: float, old: float) -> float:
    return (new / old - 1) * 100 if old > 0 else 0.0


def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y.")
    except ValueError:
        return iso[:10]


def new_baseline(now: datetime, value: float, price: float) -> Dict[str, Any]:
    return {
        "start": now.isoformat(),
        "start_value": value,
        "start_price": price,
        "cycles_total": 0,
        "profit_total": 0.0,
        "week_start": now.isoformat(),
        "week_value": value,
        "week_cycles": 0,
        "week_profit": 0.0,
        "last_weekly": now.isoformat(),
        "last_daily": "",
    }


def weekly_text(
    r: Dict[str, Any], now: datetime, value: float, price: float, held: float, unreal: float,
    symbol: str, base: str, quote: str,
) -> str:
    days = (now - datetime.fromisoformat(r["start"])).total_seconds() / 86400
    w_cycles = r["cycles_total"] - r["week_cycles"]
    w_profit = r["profit_total"] - r["week_profit"]
    w_change = value - r["week_value"]
    hold_value = r["start_value"] * price / r["start_price"] if r["start_price"] > 0 else 0.0
    vs_hold = value - hold_value
    return (
        f"📊 Tjedni izvještaj {symbol} | {now:%d.%m.%Y.}\n"
        f"\n"
        f"Ovaj tjedan:\n"
        f" • krugova: {w_cycles}, zarada od krugova {w_profit:+.2f} {quote}\n"
        f" • vrijednost: {r['week_value']:.2f} → {value:.2f} {quote} ({w_change:+.2f}, {_pct(value, r['week_value']):+.1f}%)\n"
        f"\n"
        f"Od početka ({_date(r['start'])}, {days:.0f} dana):\n"
        f" • krugova: {r['cycles_total']}, zarada od krugova {r['profit_total']:+.2f} {quote}\n"
        f" • vrijednost: {r['start_value']:.2f} → {value:.2f} {quote} ({_pct(value, r['start_value']):+.1f}%)\n"
        f" • {base}: {r['start_price']:.6g} → {price:.6g} ({_pct(price, r['start_price']):+.1f}%)\n"
        f" • samo kupi i drži {base}: {_pct(hold_value, r['start_value']):+.1f}% "
        f"→ grid je {'bolji' if vs_hold >= 0 else 'lošiji'} za {abs(vs_hold):.2f} {quote}\n"
        f"\n"
        f"Trenutno držim {held:g} {base} (nerealizirano {unreal:+.2f} {quote})."
    )


def append_daily(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
