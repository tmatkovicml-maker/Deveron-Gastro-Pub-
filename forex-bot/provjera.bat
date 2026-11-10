@echo off
REM Provjera veze s Binanceom i Telegramom.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python -m forexbot check
pause
