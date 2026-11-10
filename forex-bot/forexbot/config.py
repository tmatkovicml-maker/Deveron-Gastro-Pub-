"""Postavke bota - čitaju se iz datoteke .env (ili varijabli okruženja)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .strategy import StrategyParams


class ConfigError(Exception):
    pass


def load_env_file(path: Path) -> None:
    """Jednostavan .env parser (KLJUČ=vrijednost). Postojeće varijable imaju prednost."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    raw = _get(name)
    try:
        return float(raw) if raw else default
    except ValueError as exc:
        raise ConfigError(f"{name} mora biti broj, a ne '{raw}'") from exc


def _int(name: str, default: int) -> int:
    raw = _get(name)
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise ConfigError(f"{name} mora biti cijeli broj, a ne '{raw}'") from exc


def _bool(name: str, default: bool) -> bool:
    raw = _get(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "da", "on")


GRANULARITY_SECONDS = {
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D": 86400,
}


@dataclass
class Config:
    oanda_token: str = ""
    oanda_account_id: str = ""
    oanda_env: str = "practice"
    instruments: List[str] = field(default_factory=lambda: ["EUR_USD", "GBP_USD", "USD_JPY", "EUR_GBP"])
    granularity: str = "H1"
    risk_per_trade: float = 0.01
    max_open_trades: int = 2
    daily_loss_limit: float = 0.03
    max_spread_pips: float = 2.5
    leverage: float = 30.0
    max_margin_use: float = 0.5
    dry_run: bool = False
    poll_seconds: int = 30
    telegram_token: str = ""
    telegram_chat_id: str = ""
    data_dir: Path = Path("data")
    strategy: StrategyParams = field(default_factory=StrategyParams)

    @property
    def granularity_seconds(self) -> int:
        return GRANULARITY_SECONDS[self.granularity]

    @classmethod
    def from_env(cls, env_file: Path = Path(".env")) -> "Config":
        load_env_file(env_file)
        strategy = StrategyParams(
            ema_fast=_int("EMA_FAST", 20),
            ema_slow=_int("EMA_SLOW", 50),
            ema_trend=_int("EMA_TREND", 200),
            rsi_period=_int("RSI_PERIOD", 14),
            atr_period=_int("ATR_PERIOD", 14),
            sl_atr=_float("SL_ATR", 1.5),
            tp_atr=_float("TP_ATR", 3.0),
        )
        instruments = [s.strip().upper() for s in _get("INSTRUMENTS", "EUR_USD,GBP_USD,USD_JPY,EUR_GBP").split(",") if s.strip()]
        cfg = cls(
            oanda_token=_get("OANDA_TOKEN"),
            oanda_account_id=_get("OANDA_ACCOUNT_ID"),
            oanda_env=_get("OANDA_ENV", "practice").lower(),
            instruments=instruments,
            granularity=_get("GRANULARITY", "H1").upper(),
            risk_per_trade=_float("RISK_PER_TRADE", 0.01),
            max_open_trades=_int("MAX_OPEN_TRADES", 2),
            daily_loss_limit=_float("DAILY_LOSS_LIMIT", 0.03),
            max_spread_pips=_float("MAX_SPREAD_PIPS", 2.5),
            leverage=_float("LEVERAGE", 30.0),
            max_margin_use=_float("MAX_MARGIN_USE", 0.5),
            dry_run=_bool("DRY_RUN", False),
            poll_seconds=_int("POLL_SECONDS", 30),
            telegram_token=_get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
            data_dir=Path(_get("DATA_DIR", "data")),
            strategy=strategy,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.oanda_env not in ("practice", "live"):
            raise ConfigError("OANDA_ENV mora biti 'practice' (demo) ili 'live' (pravi novac)")
        if self.oanda_env == "live" and _get("I_UNDERSTAND_REAL_MONEY").lower() != "da":
            raise ConfigError(
                "OANDA_ENV=live trguje PRAVIM novcem. Ako to stvarno želiš, "
                "dodaj I_UNDERSTAND_REAL_MONEY=da u .env"
            )
        if self.granularity not in GRANULARITY_SECONDS:
            raise ConfigError(f"GRANULARITY mora biti jedno od: {', '.join(GRANULARITY_SECONDS)}")
        if not 0 < self.risk_per_trade <= 0.03:
            raise ConfigError("RISK_PER_TRADE mora biti između 0 i 0.03 (najviše 3% po trejdu)")
        if not 0 < self.daily_loss_limit <= 0.2:
            raise ConfigError("DAILY_LOSS_LIMIT mora biti između 0 i 0.2")
        if self.max_open_trades < 1:
            raise ConfigError("MAX_OPEN_TRADES mora biti barem 1")
        if not self.instruments:
            raise ConfigError("INSTRUMENTS ne smije biti prazan")
        for inst in self.instruments:
            if len(inst.split("_")) != 2:
                raise ConfigError(f"Neispravan par '{inst}' - koristi oblik EUR_USD")

    def require_oanda(self) -> None:
        if not self.oanda_token or not self.oanda_account_id:
            raise ConfigError("Nedostaju OANDA_TOKEN i/ili OANDA_ACCOUNT_ID u .env datoteci")
