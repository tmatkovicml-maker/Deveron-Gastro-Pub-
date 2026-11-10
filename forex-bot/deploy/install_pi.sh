#!/usr/bin/env bash
# Instalacija na Raspberry Pi (Raspberry Pi OS). Pokreni iz mape forex-bot:
#   bash deploy/install_pi.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"
cd "$DIR"

echo "==> Instaliram Python alate"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

echo "==> Virtualno okruženje"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Napravljen .env - upiši OANDA i Telegram podatke: nano $DIR/.env"
fi

echo "==> Sistemski servis (automatski start nakon paljenja)"
sed -e "s|%USER%|$USER_NAME|g" -e "s|%DIR%|$DIR|g" deploy/forexbot.service | sudo tee /etc/systemd/system/forexbot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable forexbot

echo
echo "Gotovo. Sljedeći koraci:"
echo "  1) nano $DIR/.env                       (upiši podatke)"
echo "  2) .venv/bin/python -m forexbot check   (provjera veze)"
echo "  3) sudo systemctl start forexbot        (pokreni bota)"
echo "  4) journalctl -u forexbot -f            (prati log)"
