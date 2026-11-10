@echo off
REM Backtest na 3 godine pravih Binance cijena (BTC i ETH).
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python -m forexbot backtest --days 1095 --instrument BTCEUR
.venv\Scripts\python -m forexbot backtest --days 1095 --instrument ETHEUR
pause
