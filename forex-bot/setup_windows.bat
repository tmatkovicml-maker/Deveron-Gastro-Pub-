@echo off
REM Prva instalacija na Windowsima - dvoklik na ovu datoteku.
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python nije instaliran. Instaliraj ga s python.org ^(oznaci "Add python.exe to PATH"^) pa pokreni ponovno.
  pause
  exit /b 1
)
if not exist .venv py -3 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo Napravljena je datoteka .env - otvaram je, upisi Binance i Telegram podatke i spremi.
  notepad .env
)
echo.
echo Gotovo. Sada pokreni provjera.bat, zatim pokreni_bota.bat
pause
