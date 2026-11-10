@echo off
REM Pokrece bota. Ostavi prozor otvoren; zatvaranje prozora (ili Ctrl+C) zaustavlja bota.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
title Trading bot
.venv\Scripts\python -m forexbot run
pause
