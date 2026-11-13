# Trading bot (Binance + Raspberry Pi)

**Dvije strategije** (`STRATEGY` u `.env`):
- **`grid`**: "kupi nisko, prodaj visoko" s malim nalozima (npr. 6 $). Trguje češće
  i dobra je za učenje. Opis je ispod u odjeljku *Grid bot*.
- **`signal`**: EMA crossover, nekoliko većih trejdova mjesečno.

Automatski bot koji trguje po signalima, radi stalno na Raspberry Pi-ju, a s
mobitela ga pratiš i kontroliraš preko Telegrama.

- **Binance (zadano):** kriptovalute na spotu, npr. BTC/EUR i ETH/EUR.
  Nema poluge ni prodaje na kratko: bot kupuje, a prodaje na stop-lossu ili take-profitu.
- **OANDA (opcija):** pravi forex (EUR/USD...), s polugom. Uključuje se s `BROKER=oanda`.

> ⚠️ **Upozorenje:** bot ne garantira zaradu. Kriptovalute znaju pasti 10–20% u jednom danu.
> Najmanje mjesec dana koristi samo **Binance Testnet** (virtualni novac), a kasnije
> ulaži samo novac koji si možeš priuštiti izgubiti.

## Grid bot (za male iznose i učenje)

Primjer s ETH po 3000 $, rasponom ±8% i 8 razina (razmak ~2%):

```
3240 ─────────────────────  razina 8
3176 ─────────────────────  razina 7
 ...
3000  ◄── trenutna cijena
2940 ── KUPI 6 $ ─────────  razina 3   → kad se izvrši: PRODAJ @ 3000 (razina 4)
2882 ── KUPI 6 $ ─────────  razina 2   → kad se izvrši: PRODAJ @ 2940 (razina 3)
 ...
2760 ── KUPI 6 $ ─────────  razina 0
```

1. Ispod cijene postavi kupnje po 6 $, onoliko koliko imaš novca.
2. Kad cijena padne i kupnja se izvrši, odmah postavi prodaju jednu razinu više (+2%).
3. Kad se prodaja izvrši, zaradio si oko 1,8% od 6 $ (oko 0,11 $) nakon provizija, a kupnja se ponovno postavlja.
4. Na Telegram stiže poruka za svaku kupnju i prodaju, s objašnjenjem.

**Kad zarađuje:** kad cijena skače gore-dolje unutar raspona.
**Kad gubi:** kad cijena padne ispod raspona i ostane dolje. Tada držiš kupljeni ETH u minusu, kao da si ga kupio ručno.
Kad cijena naraste iznad raspona, sve je prodano sa zaradom, i za novi raspon pošalješ `/zatvori_sve`, pa `/nastavi`.

**Savjeti:**
- Uključi **"Use BNB to pay fees"** na Binanceu (i drži par dolara u BNB-u). Dobivaš 25% popusta na proviziju i bot može prodati točno onoliko koliko je kupio.
- Ne stavljaj previše razina: razmak mora biti **barem 0,5%**, inače provizije pojedu zaradu. Bot to sam provjerava.
- Prije starta pokreni backtest (`backtest.bat`). Pokazat će koliko bi krugova bilo u zadnjih godinu dana i usporedbu sa "samo kupi i drži".
- U EU se USDT ne može kupovati (MiCA pravila). Koristi **USDC** ili **EUR** parove. Ako imaš USDT, zamijeni ga u USDC preko *Binance Convert*.

## 📱 Web aplikacija (grid bot)
Kad se grid bot pokrene, pokreće i malu web aplikaciju na računalu i šalje na
Telegram adresu i PIN, npr. `http://192.168.1.10:8080`.
- Otvori adresu na mobitelu (**na kućnom WiFi-ju**), upiši PIN i dodaj stranicu na početni zaslon.
- **Prikazuje:** vrijednost računa, krugove, zaradu, usporedbu sa "samo kupi i drži",
  svijeće s Binancea (24 h / 7 dana / 30 dana) s razinama grida, nalozima koji čekaju i
  oznakama kupnji i prodaja, "ljestve" grida, graf vrijednosti kroz vrijeme i zadnje poteze.
- **Gumbi** Pauza i Nastavi. Zatvaranje svega namjerno ide samo preko Telegrama.
- Windows će pri prvom pokretanju pitati za vatrozid: dopusti pristup za **privatne mreže**.
- Isključuje se s `DASHBOARD_PORT=0`.

## Signalni bot: kako radi

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

### 3a. Pokretanje na računalu (najlakše za početak)
Bot radi dok je računalo upaljeno. Stop-loss i take-profit su ionako kod Binancea,
pa je pozicija zaštićena i kad je računalo ugašeno.

**Windows**
1. Instaliraj **Python 3.11 ili noviji** s python.org (ili iz Microsoft Storea). Ako instalacija nudi **"Add python.exe to PATH"**, označi to; nova instalacija (Python Install Manager) to radi sama.
2. Na GitHubu otvori ovaj repozitorij i odaberi granu `claude/automated-trading-app-f1e9tt`.
   Klikni **Code → Download ZIP**, raspakiraj i uđi u mapu `forex-bot`.
3. Dvoklikni **`setup_windows.bat`**. Otvorit će se Notepad: upiši testnet ključeve i Telegram, pa spremi.
4. Dvoklikni **`provjera.bat`**, a na Telegram mora stići test poruka.
5. Dvoklikni **`backtest.bat`** i pošalji mi rezultat.
6. Dvoklikni **`pokreni_bota.bat`** i ostavi prozor otvoren.
   - U *Postavke → Sustav → Napajanje* isključi stanje mirovanja (Sleep) dok bot radi.

**Mac / Linux** (u Terminalu, unutar mape `forex-bot`):
```bash
bash start.sh setup      # instalacija + izrada .env (zatim ga uredi)
bash start.sh check      # provjera veze
bash start.sh backtest   # backtest BTC i ETH
bash start.sh run        # pokreni bota (Ctrl+C za zaustavljanje)
```

### 3b. Raspberry Pi (za rad 0-24)
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
