#!/usr/bin/env bash
# Mac / Linux:  bash start.sh setup | check | backtest | run
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-run}" in
  setup)
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    [ -f .env ] || { cp .env.example .env; echo "Napravljen .env - upiši Binance i Telegram podatke (npr. nano .env)"; }
    ;;
  check)    .venv/bin/python -m forexbot check ;;
  backtest)
    .venv/bin/python -m forexbot backtest --days 365 --balance 50
    ;;
  run)      .venv/bin/python -m forexbot run ;;
  *) echo "Koristi: bash start.sh setup|check|backtest|run"; exit 1 ;;
esac
