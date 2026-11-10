@echo off
REM Prva instalacija na Windowsima - dvoklik na ovu datoteku.
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python nije pronaden. Instaliraj ga s python.org ili iz Microsoft Storea pa pokreni ponovno.
  pause
  exit /b 1
)
echo Koristim: %PY%
%PY% --version
if not exist .venv\Scripts\python.exe %PY% -m venv .venv
if not exist .venv\Scripts\python.exe (
  echo Nije uspjelo napraviti okruzenje. Instaliraj Python iz Microsoft Storea ^(potrazi "Python 3.13"^) pa pokreni ponovno.
  pause
  exit /b 1
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo Napravljena je datoteka .env - otvaram je, upisi Binance i Telegram podatke i spremi.
  notepad .env
)
echo.
echo Gotovo. Sada pokreni provjera.bat, zatim backtest.bat
pause
