#!/usr/bin/env bash
# Instalacija na VPS (Ubuntu 22.04/24.04), kao root. Pokreni iz mape forex-bot:
#   bash deploy/install_vps.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

if [ ! -f .env ]; then
  echo "GREŠKA: nema datoteke .env u $DIR - kopiraj je s računala (scp) pa pokreni ponovno."
  exit 1
fi

echo "==> Sistemski paketi"
apt-get update -y
apt-get install -y python3 python3-venv ufw curl

echo "==> Python okruženje (Windows .venv s računala se briše)"
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "==> Vatrozid: dopušten samo SSH izvana"
ufw allow OpenSSH
ufw --force enable

echo "==> Tailscale (privatna mreža za aplikaciju na mobitelu)"
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
ufw allow in on tailscale0

echo "==> Servis (bot se sam pokreće i nakon restarta servera)"
sed -e "s|%USER%|$(whoami)|g" -e "s|%DIR%|$DIR|g" deploy/forexbot.service > /etc/systemd/system/forexbot.service
systemctl daemon-reload
systemctl enable forexbot

echo
echo "Gotovo. Sljedeći koraci:"
echo "  1) tailscale up                         (otvori link koji ispiše i prijavi se)"
echo "  2) curl -4 -s https://api.ipify.org     (IP servera -> upiši na Binanceu)"
echo "  3) .venv/bin/python -m forexbot check   (kad je IP upisan na Binanceu)"
echo "  4) systemctl start forexbot             (pokreni bota)"
echo "  5) journalctl -u forexbot -f            (prati log, izlaz: Ctrl+C)"
