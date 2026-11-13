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
    broker: str = "binance"
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
    # --- Binance spot ---
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    fee_rate: float = 0.001
    max_spread_pct: float = 0.15
    max_position_fraction: float = 0.45
    # --- strategija: signal (EMA crossover) ili grid (kupi nisko, prodaj visoko) ---
    strategy_mode: str = "signal"
    grid_lower: float = 0.0  # 0 = automatski oko trenutne cijene
    grid_upper: float = 0.0
    grid_range_pct: float = 8.0
    grid_levels: int = 8
    grid_order_quote: float = 6.0
    grid_auto_recenter: bool = True
    grid_sell_levels: int = 1  # prodaja N razina iznad kupnje
    report_weekday: int = 6  # 0=pon ... 6=ned
    report_hour_utc: int = 19  # 19 UTC = 20h zimi / 21h ljeti u Hrvatskoj
    dashboard_port: int = 0  # 0 = web aplikacija isključena
    dashboard_pin: str = ""

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
        broker = _get("BROKER", "binance").lower()
        testnet = _bool("BINANCE_TESTNET", True)
        # Testnet ima USDT parove; u EU se na pravom računu trguje s EUR (ili USDC) parovima.
        default_symbols = "BTCUSDT,ETHUSDT" if testnet else "BTCEUR,ETHEUR"
        symbols = [s.strip().upper() for s in _get("SYMBOLS", default_symbols).split(",") if s.strip()]
        strategy_mode = _get("STRATEGY", "signal").lower()
        if strategy_mode == "grid":
            symbols = [_get("GRID_SYMBOL", "ETHUSDT" if testnet else "ETHUSDC").upper()]
        default_gran = "H4" if broker == "binance" else "H1"
        instruments = [s.strip().upper() for s in _get("INSTRUMENTS", "EUR_USD,GBP_USD,USD_JPY,EUR_GBP").split(",") if s.strip()]
        cfg = cls(
            broker=broker,
            binance_api_key=_get("BINANCE_API_KEY"),
            binance_api_secret=_get("BINANCE_API_SECRET"),
            binance_testnet=testnet,
            symbols=symbols,
            fee_rate=_float("FEE_RATE", 0.001),
            max_spread_pct=_float("MAX_SPREAD_PCT", 0.15),
            max_position_fraction=_float("MAX_POSITION_FRACTION", 0.45),
            strategy_mode=strategy_mode,
            grid_lower=_float("GRID_LOWER", 0.0),
            grid_upper=_float("GRID_UPPER", 0.0),
            grid_range_pct=_float("GRID_RANGE_PCT", 8.0),
            grid_levels=_int("GRID_LEVELS", 8),
            grid_order_quote=_float("GRID_ORDER_QUOTE", 6.0),
            grid_auto_recenter=_bool("GRID_AUTO_RECENTER", True),
            grid_sell_levels=_int("GRID_SELL_LEVELS", 1),
            report_weekday=_int("REPORT_WEEKDAY", 6),
            report_hour_utc=_int("REPORT_HOUR_UTC", 19),
            dashboard_port=_int("DASHBOARD_PORT", 8080),
            dashboard_pin=_get("DASHBOARD_PIN"),
            oanda_token=_get("OANDA_TOKEN"),
            oanda_account_id=_get("OANDA_ACCOUNT_ID"),
            oanda_env=_get("OANDA_ENV", "practice").lower(),
            instruments=instruments,
            granularity=_get("GRANULARITY", default_gran).upper(),
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

    @property
    def is_live(self) -> bool:
        if self.broker == "binance":
            return not self.binance_testnet
        return self.oanda_env == "live"

    def validate(self) -> None:
        if self.broker not in ("binance", "oanda"):
            raise ConfigError("BROKER mora biti 'binance' ili 'oanda'")
        if self.is_live and _get("I_UNDERSTAND_REAL_MONEY").lower() != "da":
            raise ConfigError(
                "Postavke trguju PRAVIM novcem. Ako to stvarno želiš, "
                "dodaj I_UNDERSTAND_REAL_MONEY=da u .env"
            )
        if self.oanda_env not in ("practice", "live"):
            raise ConfigError("OANDA_ENV mora biti 'practice' (demo) ili 'live' (pravi novac)")
        if self.granularity not in GRANULARITY_SECONDS:
            raise ConfigError(f"GRANULARITY mora biti jedno od: {', '.join(GRANULARITY_SECONDS)}")
        if not 0 < self.risk_per_trade <= 0.03:
            raise ConfigError("RISK_PER_TRADE mora biti između 0 i 0.03 (najviše 3% po trejdu)")
        if not 0 < self.daily_loss_limit <= 0.2:
            raise ConfigError("DAILY_LOSS_LIMIT mora biti između 0 i 0.2")
        if self.max_open_trades < 1:
            raise ConfigError("MAX_OPEN_TRADES mora biti barem 1")
        if self.broker == "oanda":
            if not self.instruments:
                raise ConfigError("INSTRUMENTS ne smije biti prazan")
            for inst in self.instruments:
                if len(inst.split("_")) != 2:
                    raise ConfigError(f"Neispravan par '{inst}' - koristi oblik EUR_USD")
        else:
            if not self.symbols:
                raise ConfigError("SYMBOLS ne smije biti prazan")
            if self.strategy_mode not in ("signal", "grid"):
                raise ConfigError("STRATEGY mora biti 'signal' ili 'grid'")
            if self.strategy_mode == "grid":
                if not 2 <= self.grid_levels <= 50:
                    raise ConfigError("GRID_LEVELS mora biti između 2 i 50")
                if (self.grid_lower > 0) != (self.grid_upper > 0) or (self.grid_lower and self.grid_lower >= self.grid_upper):
                    raise ConfigError("Postavi oba GRID_LOWER i GRID_UPPER (donja < gornja) ili nijedan")
                if not 1 <= self.grid_sell_levels <= 5:
                    raise ConfigError("GRID_SELL_LEVELS mora biti između 1 i 5")
                if not 1 <= self.grid_range_pct <= 50:
                    raise ConfigError("GRID_RANGE_PCT mora biti između 1 i 50")
                if self.grid_order_quote <= 0:
                    raise ConfigError("GRID_ORDER_QUOTE mora biti veći od 0")
            if not 0 <= self.report_weekday <= 6 or not 0 <= self.report_hour_utc <= 23:
                raise ConfigError("REPORT_WEEKDAY mora biti 0-6, a REPORT_HOUR_UTC 0-23")
            if not 0 < self.max_position_fraction <= 1:
                raise ConfigError("MAX_POSITION_FRACTION mora biti između 0 i 1")

    def require_binance(self) -> None:
        if not self.binance_api_key or not self.binance_api_secret:
            raise ConfigError("Nedostaju BINANCE_API_KEY i/ili BINANCE_API_SECRET u .env datoteci")

    def require_oanda(self) -> None:
        if not self.oanda_token or not self.oanda_account_id:
            raise ConfigError("Nedostaju OANDA_TOKEN i/ili OANDA_ACCOUNT_ID u .env datoteci")
