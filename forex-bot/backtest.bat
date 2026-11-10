@echo off
REM Backtest na pravim Binance cijenama (parovi i strategija iz .env).
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python -m forexbot backtest --days 365 --balance 50
pause
