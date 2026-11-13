"""Naredbe (broker se bira s BROKER=binance ili BROKER=oanda u .env):

  python -m forexbot check                  provjera veze s brokerom i Telegramom
  python -m forexbot run                    pokreni bota (radi stalno)
  python -m forexbot backtest --days 730    backtest na povijesnim podacima
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

from .binance import BinanceClient, BinanceError
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


def make_binance(cfg: Config) -> BinanceClient:
    cfg.require_binance()
    client = BinanceClient(cfg.binance_api_key, cfg.binance_api_secret, testnet=cfg.binance_testnet)
    client.sync_time()
    return client


def check_telegram(cfg: Config) -> None:
    tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id)
    if tg.enabled:
        ok = tg.send("✅ Trading bot: test poruka - Telegram radi.")
        print("Telegram:", "OK" if ok else "GREŠKA (provjeri token i chat id)")
    else:
        print("Telegram: nije podešen (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")


def cmd_check_binance(cfg: Config) -> int:
    client = make_binance(cfg)
    where = "TESTNET" if cfg.binance_testnet else "PRAVI RAČUN"
    balances = client.balances()
    quotes = set()
    for sym in cfg.symbols:
        info = client.symbol_info(sym)
        quotes.add(info["quote"])
        b = client.book(sym)
        print(f"  {sym}: bid {b['bid']} / ask {b['ask']}  (min. nalog {info['min_notional']} {info['quote']}, status {info['status']})")
    if len(quotes) > 1:
        print(f"UPOZORENJE: svi parovi moraju imati istu kotnu valutu, a imaju {quotes}")
        return 2
    q = quotes.pop()
    print(f"Binance ({where}) OK - slobodno {balances.get(q, {}).get('free', 0):.2f} {q}")
    check_telegram(cfg)
    return 0


def cmd_check(cfg: Config) -> int:
    if cfg.broker == "binance":
        return cmd_check_binance(cfg)
    client = make_client(cfg)
    acc = client.account_summary()
    print(f"OANDA ({cfg.oanda_env}) OK - račun {acc['id']}: {float(acc['balance']):.2f} {acc['currency']}")
    for inst in cfg.instruments:
        p = client.pricing([inst]).get(inst)
        print(f"  {inst}: bid {p['bid']} / ask {p['ask']} {'(otvoreno)' if p['tradeable'] else '(tržište zatvoreno)'}")
    check_telegram(cfg)
    return 0


def cmd_run(cfg: Config) -> int:
    tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id)
    if cfg.broker == "binance" and cfg.strategy_mode == "grid":
        from .grid import GridBot

        bot = GridBot(cfg, make_binance(cfg), tg)
    elif cfg.broker == "binance":
        from .spot_bot import SpotBot

        bot = SpotBot(cfg, make_binance(cfg), tg)
    else:
        bot = Bot(cfg, make_client(cfg), tg)

    def _stop(*_):
        logging.info("Zaustavljam bota...")
        bot.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    bot.run_forever()
    return 0


def cmd_backtest(cfg: Config, args: argparse.Namespace) -> int:
    if cfg.broker == "binance":
        return cmd_backtest_binance(cfg, args)
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


def cmd_backtest_grid(cfg: Config, args: argparse.Namespace) -> int:
    from .grid import check_spacing, resolve_range, simulate_grid

    sym = args.instrument or cfg.symbols[0]
    if args.csv:
        candles = load_csv(Path(args.csv))
    else:
        start = datetime.now(timezone.utc) - timedelta(days=args.days)
        print(f"Dohvaćam {sym} 15-minutne svijeće od {start:%Y-%m-%d}...")
        candles = BinanceClient(testnet=False).history(sym, "M15", int(start.timestamp() * 1000))
        save_csv(candles, cfg.data_dir / "history" / f"{sym}_M15.csv")
    if not candles:
        print("Nema podataka.")
        return 1
    lower, upper = resolve_range(candles[0].open, cfg)
    try:
        check_spacing(lower, upper, cfg.grid_levels, cfg.fee_rate)
    except ValueError as exc:
        print(f"Greška: {exc}")
        return 2
    manual = cfg.grid_lower > 0 and cfg.grid_upper > 0
    recenter = cfg.grid_range_pct if cfg.grid_auto_recenter and not manual else None
    res = simulate_grid(
        candles, lower, upper, cfg.grid_levels, cfg.grid_order_quote, cfg.fee_rate, args.balance, sym,
        recenter_pct=recenter, sell_levels=cfg.grid_sell_levels,
    )
    print(res.summary())
    k = cfg.grid_sell_levels
    print(f"Prodaja: {k} {'razina' if k == 1 or k >= 5 else 'razine'} iznad kupnje")
    return 0


def cmd_backtest_binance(cfg: Config, args: argparse.Namespace) -> int:
    if cfg.strategy_mode == "grid":
        return cmd_backtest_grid(cfg, args)
    # povijest se uvijek uzima s pravog tržišta (javni podaci, ključ nije potreban)
    symbols = [args.instrument] if args.instrument else cfg.symbols
    client = BinanceClient(testnet=False)
    total = 0.0
    for sym in symbols:
        if args.csv:
            candles = load_csv(Path(args.csv))
        else:
            start = datetime.now(timezone.utc) - timedelta(days=args.days)
            print(f"Dohvaćam {sym} {cfg.granularity} od {start:%Y-%m-%d}...")
            candles = client.history(sym, cfg.granularity, int(start.timestamp() * 1000))
            save_csv(candles, cfg.data_dir / "history" / f"{sym}_{cfg.granularity}.csv")
        res = run_backtest(
            candles,
            cfg.strategy,
            instrument=sym,
            start_balance=args.balance,
            risk_per_trade=cfg.risk_per_trade,
            account_currency="QUOTE",
            spot=True,
            fee_rate=cfg.fee_rate,
            max_position_fraction=cfg.max_position_fraction,
        )
        print(res.summary())
        print(f"Svijeća: {len(candles)}\n")
        total += res.end_balance - res.start_balance
        if args.csv:
            break
    if len(symbols) > 1 and not args.csv:
        print(f"Ukupno (svaki par zasebno s {args.balance:.0f}): {total:+.2f}")
    return 0


def main(argv=None) -> int:
    # Windows konzola: hrvatska slova i emoji ne smiju srušiti bota
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="forexbot", description="Trading bot (Binance spot ili OANDA forex)")
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
    bt.add_argument("--spread", type=float, default=1.2, help="OANDA: prosječni spread u pipima")
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
    except BinanceError as exc:
        print(f"Binance greška: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
