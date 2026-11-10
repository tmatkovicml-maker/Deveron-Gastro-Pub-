# Trading bot (Binance + Raspberry Pi)

Automatski bot koji trguje po signalima, radi stalno na Raspberry Pi-ju, a s
mobitela ga pratiš i kontroliraš preko Telegrama.

- **Binance (zadano):** kriptovalute na spotu, npr. BTC/EUR i ETH/EUR.
  Nema poluge ni prodaje na kratko: bot kupuje, a prodaje na stop-lossu ili take-profitu.
- **OANDA (opcija):** pravi forex (EUR/USD...), s polugom. Uključuje se s `BROKER=oanda`.

> ⚠️ **Upozorenje:** bot ne garantira zaradu. Kriptovalute znaju pasti 10–20% u jednom danu.
> Najmanje mjesec dana koristi samo **Binance Testnet** (virtualni novac), a kasnije
> ulaži samo novac koji si možeš priuštiti izgubiti.

## Kako radi

| | |
|---|---|
| **Parovi** | BTC i ETH (testnet: `BTCUSDT`, `ETHUSDT`; pravi račun u EU: `BTCEUR`, `ETHEUR`) |
| **Svijeće** | 4 sata (H4), odluka tek kad se svijeća zatvori |
| **Signal KUPI** | EMA20 presiječe EMA50 prema gore + cijena iznad EMA200 + RSI < 70 |
| **Izlaz** | OCO nalog na Binanceu: stop-loss 1,5 × ATR **ili** take-profit 3 × ATR (omjer 1:2) |

### Zaštita novca (ugrađena)
- **1% rizika po trejdu** (oko 5 € na 500 €), uključujući Binance proviziju.
- **Najviše 45% kapitala u jednoj poziciji** i **najviše 2 pozicije** odjednom.
- **Dnevni limit gubitka od 3%.** Nakon toga bot taj dan ne kupuje.
- **Stop-loss i take-profit su kod Binancea (OCO nalog).** Ako Pi ostane bez struje ili interneta, pozicija je i dalje zaštićena.
- **Nikad ne ostaje bez zaštite.** Ako se stop-loss ne uspije postaviti, bot odmah prodaje kupljeno.
- **Preskače kupnju ako je spread prevelik**, ili ako bi nalog bio ispod Binanceovog minimuma.
- **Za pravi novac treba svjesna potvrda** (`I_UNDERSTAND_REAL_MONEY=da`).

### Telegram komande
`/status` · `/pauza` · `/nastavi` · `/zatvori_sve` · `/pomoc`

Bot ti javlja svaku kupnju, svako zatvaranje (s rezultatom u €) i dosegnut dnevni limit.

---

## Postavljanje korak po korak

### 1. Binance Testnet (virtualni novac)
1. Otvori **testnet.binance.vision** i prijavi se preko GitHub računa.
2. Klikni **Generate HMAC_SHA256 Key** i zapiši **API Key** i **Secret Key**.
   Testnet račun automatski dobiva virtualne USDT, BTC i ETH.

### 2. Telegram bot (za obavijesti na mobitel)
1. U Telegramu otvori **@BotFather**, pošalji `/newbot` i dobit ćeš **token**.
2. Pošalji bilo koju poruku svom novom botu.
3. Otvori `https://api.telegram.org/bot<TOKEN>/getUpdates`, nađi `"chat":{"id":...}` i to je **chat id**.

### 3. Raspberry Pi
Dovoljan je **Raspberry Pi 4 (2 GB)** ili **Pi 5**, s microSD karticom od 16 GB ili više
i originalnim punjačem. **Tablet ne treba.**

1. Pomoću *Raspberry Pi Imager* instaliraj **Raspberry Pi OS Lite (64-bit)**,
   a u postavkama Imagera upiši WiFi i uključi SSH.
2. Spoji se s računala: `ssh korisnik@raspberrypi.local`
3. Instaliraj bota:
   ```bash
   sudo apt-get install -y git
   git clone https://github.com/tmatkovicml-maker/Deveron-Gastro-Pub-.git
   cd Deveron-Gastro-Pub-/forex-bot
   bash deploy/install_pi.sh
   nano .env                              # upiši Binance testnet ključeve i Telegram
   .venv/bin/python -m forexbot check     # provjera veze; stiže test poruka na Telegram
   ```

### 4. Backtest (prije pokretanja, ključ nije potreban)
```bash
.venv/bin/python -m forexbot backtest --days 1095 --instrument BTCEUR
.venv/bin/python -m forexbot backtest --days 1095 --instrument ETHEUR
```
Uzima 3 godine pravih Binance cijena i pokazuje kako bi strategija prošla, s provizijama.
Gledaj **profit factor**: ispod 1 znači da bi strategija gubila. Ako je loš, ne prelazi na pravi novac.
Možeš usporediti i druge postavke, npr. `GRANULARITY=H1` ili `D` u `.env`.

### 5. Pokretanje
```bash
sudo systemctl start forexbot      # pokreni
journalctl -u forexbot -f          # prati što radi
sudo systemctl stop forexbot       # zaustavi
```
Bot se sam pokreće nakon paljenja Pi-ja ili nestanka struje.

### 6. Prijelaz na pravi Binance račun (tek nakon barem 4 tjedna na testnetu)
1. Na binance.com otvori **Account → API Management → Create API**.
   - Uključi **samo "Enable Spot & Margin Trading"**.
   - **Nikad ne uključuj "Enable Withdrawals"** (isplate). Tako ni ukradeni ključ ne može iznijeti novac.
   - Uključi **"Restrict access to trusted IPs"** i upiši javnu IP adresu svoje kućne mreže.
2. U `.env` postavi:
   ```
   BINANCE_TESTNET=false
   BINANCE_API_KEY=...       # pravi ključ
   BINANCE_API_SECRET=...
   SYMBOLS=BTCEUR,ETHEUR
   I_UNDERSTAND_REAL_MONEY=da
   ```
3. Pokreni `sudo systemctl restart forexbot`.

> 💡 Bot računa kapital iz **cijelog slobodnog EUR salda** na računu. Ako na istom
> računu držiš i drugu kriptovalutu ili ručno trguješ, napravi zaseban
> **Binance sub-račun** samo za bota ili mu ostavi samo iznos kojim smije trgovati.

## Realna očekivanja (500 €)
- Rizik po trejdu je oko 5 €, a cilj po uspješnom trejdu oko 10 €.
- Na H4 svijećama očekuj tek **nekoliko trejdova mjesečno**. Strpljenje je dio strategije.
- Spot strategija zarađuje samo kad cijena raste. U dugom padu tržišta (bear market) bot uglavnom miruje ili gubi male iznose.
- Provizija je 0,1% po kupnji i 0,1% po prodaji. Ako plaćaš proviziju u BNB-u, dobivaš 25% popusta.

## Za developere
```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m forexbot backtest --csv moji_podaci.csv --instrument BTCEUR   # CSV: time,open,high,low,close
```
Struktura: `forexbot/strategy.py` (signali), `risk.py` (veličina pozicije),
`binance.py` / `oanda.py` (API), `spot_bot.py` / `bot.py` (glavna petlja),
`backtest.py`, `telegram.py`.
