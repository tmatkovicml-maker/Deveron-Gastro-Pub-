"""Naredbe:

  python -m forexbot check                  provjera veze s OANDA-om i Telegramom
  python -m forexbot run                    pokreni bota (radi stalno)
  python -m forexbot backtest --days 730    backtest na povijesnim podacima s OANDA-e
  python -m forexbot backtest --csv f.csv   backtest na vlastitoj CSV datoteci
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .backtest import load_csv, run_backtest, save_csv
from .bot import Bot
from .config import Config, ConfigError
from .oanda import OandaClient, OandaError
from .telegram import Telegram


def setup_logging(data_dir: Path, verbose: bool) -> None:
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    fileh = RotatingFileHandler(data_dir / "logs" / "bot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fileh.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(fileh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def make_client(cfg: Config) -> OandaClient:
    cfg.require_oanda()
    return OandaClient(cfg.oanda_token, cfg.oanda_account_id, cfg.oanda_env)


def cmd_check(cfg: Config) -> int:
    client = make_client(cfg)
    acc = client.account_summary()
    print(f"OANDA ({cfg.oanda_env}) OK - račun {acc['id']}: {float(acc['balance']):.2f} {acc['currency']}")
    for inst in cfg.instruments:
        p = client.pricing([inst]).get(inst)
        print(f"  {inst}: bid {p['bid']} / ask {p['ask']} {'(otvoreno)' if p['tradeable'] else '(tržište zatvoreno)'}")
    tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id)
    if tg.enabled:
        ok = tg.send("✅ Forex bot: test poruka - Telegram radi.")
        print("Telegram:", "OK" if ok else "GREŠKA (provjeri token i chat id)")
    else:
        print("Telegram: nije podešen (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
    return 0


def cmd_run(cfg: Config) -> int:
    bot = Bot(cfg, make_client(cfg), Telegram(cfg.telegram_token, cfg.telegram_chat_id))

    def _stop(*_):
        logging.info("Zaustavljam bota...")
        bot.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    bot.run_forever()
    return 0


def cmd_backtest(cfg: Config, args: argparse.Namespace) -> int:
    instruments = [args.instrument] if args.instrument else cfg.instruments
    total_start = total_end = 0.0
    for inst in instruments:
        if args.csv:
            candles = load_csv(Path(args.csv))
        else:
            client = make_client(cfg)
            since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"Dohvaćam {inst} {cfg.granularity} od {since[:10]}...")
            candles = client.history(inst, cfg.granularity, since)
            save_csv(candles, cfg.data_dir / "history" / f"{inst}_{cfg.granularity}.csv")
        res = run_backtest(
            candles,
            cfg.strategy,
            instrument=inst,
            start_balance=args.balance,
            risk_per_trade=cfg.risk_per_trade,
            spread_pips=args.spread,
            leverage=cfg.leverage,
            max_margin_use=cfg.max_margin_use,
        )
        print(res.summary())
        print(f"Svijeća: {len(candles)}\n")
        total_start += res.start_balance
        total_end += res.end_balance
        if args.csv:
            break
    if len(instruments) > 1 and not args.csv:
        print(f"Ukupno (svaki par zasebno s {args.balance:.0f}): {total_end - total_start:+.2f}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="forexbot", description="Forex trading bot (OANDA)")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("run")
    bt = sub.add_parser("backtest")
    bt.add_argument("--instrument")
    bt.add_argument("--days", type=int, default=730)
    bt.add_argument("--csv")
    bt.add_argument("--balance", type=float, default=500.0)
    bt.add_argument("--spread", type=float, default=1.2, help="prosječni spread u pipima")
    args = parser.parse_args(argv)

    try:
        cfg = Config.from_env(Path(args.env_file))
    except ConfigError as exc:
        print(f"Greška u postavkama: {exc}", file=sys.stderr)
        return 2
    setup_logging(cfg.data_dir, args.verbose)

    try:
        if args.command == "check":
            return cmd_check(cfg)
        if args.command == "run":
            return cmd_run(cfg)
        return cmd_backtest(cfg, args)
    except ConfigError as exc:
        print(f"Greška u postavkama: {exc}", file=sys.stderr)
        return 2
    except OandaError as exc:
        print(f"OANDA greška: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
