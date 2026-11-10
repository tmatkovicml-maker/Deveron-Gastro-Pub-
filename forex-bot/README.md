# Forex bot (OANDA + Raspberry Pi)

Automatski bot za trgovanje valutama (forex). Radi stalno na Raspberry Pi-ju,
trguje po signalima, a s mobitela ga pratiš i kontroliraš preko Telegrama.

> ⚠️ **Upozorenje:** forex kod brokera u EU trguje se kao CFD s polugom.
> Prema obaveznim upozorenjima brokera, **70–80% malih ulagača gubi novac**.
> Bot ne garantira zaradu. Najmanje mjesec dana koristi samo **demo račun**,
> a kasnije ulaži samo novac koji si možeš priuštiti izgubiti.

## Kako radi

| | |
|---|---|
| **Broker** | OANDA (v20 API), demo (`practice`) ili pravi (`live`) račun |
| **Parovi** | EUR/USD, GBP/USD, USD/JPY, EUR/GBP (mijenja se u `.env`) |
| **Svijeće** | 1 sat (H1), odluka tek kad se svijeća zatvori |
| **Signal KUPI** | EMA20 presiječe EMA50 prema gore + cijena iznad EMA200 + RSI < 70 |
| **Signal PRODAJ** | EMA20 presiječe EMA50 prema dolje + cijena ispod EMA200 + RSI > 30 |
| **Stop-loss** | 1,5 × ATR, postavljen kod brokera odmah uz nalog |
| **Take-profit** | 3 × ATR (omjer rizika i zarade 1:2) |

### Zaštita novca (ugrađena)
- **1% rizika po trejdu.** Na 500 € je to oko 5 € gubitka ako se pogodi stop-loss.
- **Najviše 2 otvorena trejda** istovremeno, najviše jedan po paru.
- **Dnevni limit gubitka od 3%.** Nakon toga bot taj dan ne otvara nove trejdove.
- **Preskače trejd ako je spread prevelik** (noću, ili oko vijesti).
- **Ograničena margina:** bot ne koristi više od 50% računa za marginu.
- **Za pravi novac treba svjesna potvrda** (`I_UNDERSTAND_REAL_MONEY=da`).
- **Stop-loss i take-profit su kod brokera.** Ako Pi ostane bez struje ili interneta, otvoreni trejd je i dalje zaštićen.

### Telegram komande
`/status` · `/pauza` · `/nastavi` · `/zatvori_sve` · `/pomoc`

Bot ti javlja svaki otvoreni trejd, zatvoreni trejd (s rezultatom u €) i
dosegnut dnevni limit.

---

## Postavljanje korak po korak

### 1. OANDA demo račun
1. Na oanda.com otvori **demo (practice) račun**. Besplatan je i dobiješ virtualni novac.
   U postavkama demo računa namjesti valutu EUR i saldo na 500, da bude realno.
2. U korisničkom portalu otvori *Manage API Access* i generiraj **API token**.
3. Zapiši **Account ID** (oblik `101-004-1234567-001`).

> Provjeri na OANDA stranici prihvaća li račune iz Hrvatske (pokriva je
> OANDA Europe). Ako ne, bot se može prilagoditi drugom brokeru s API-jem.

### 2. Telegram bot (za obavijesti na mobitel)
1. U Telegramu otvori **@BotFather**, pošalji `/newbot` i dobit ćeš **token**.
2. Pošalji bilo koju poruku svom novom botu.
3. Otvori `https://api.telegram.org/bot<TOKEN>/getUpdates`, nađi `"chat":{"id":...}` i to je **chat id**.

### 3. Raspberry Pi
Dovoljan je **Raspberry Pi 4 (2 GB)** ili **Pi 5**, s microSD karticom od 16 GB ili više
i originalnim punjačem. **Tablet ne treba.** Pi radi bez ekrana, a sve vidiš na mobitelu
kroz Telegram.

1. Pomoću *Raspberry Pi Imager* instaliraj **Raspberry Pi OS Lite (64-bit)**.
   U postavkama Imagera odmah upiši WiFi i uključi SSH.
2. Spoji se s računala: `ssh korisnik@raspberrypi.local`
3. Instaliraj bota:
   ```bash
   sudo apt-get install -y git
   git clone https://github.com/tmatkovicml-maker/Deveron-Gastro-Pub-.git
   cd Deveron-Gastro-Pub-/forex-bot
   bash deploy/install_pi.sh
   nano .env                              # upiši OANDA i Telegram podatke
   .venv/bin/python -m forexbot check     # provjera veze; stiže test poruka na Telegram
   ```

### 4. Backtest (prije pokretanja)
```bash
.venv/bin/python -m forexbot backtest --days 730
```
Dohvaća 2 godine povijesti s OANDA-e i pokazuje kako bi strategija prošla.
Obrati pažnju na **profit factor**: ispod 1 znači da bi strategija gubila novac.
Ako je rezultat loš, ne pokreći bota s pravim novcem.

### 5. Pokretanje
```bash
sudo systemctl start forexbot      # pokreni
journalctl -u forexbot -f          # prati što radi
sudo systemctl stop forexbot       # zaustavi
```
Bot se sam pokreće nakon paljenja Pi-ja ili nestanka struje.

### 6. Prijelaz na pravi novac (tek nakon barem 4 tjedna demo trgovanja)
U `.env` postavi `OANDA_ENV=live`, upiši token i ID **pravog** računa te dodaj
`I_UNDERSTAND_REAL_MONEY=da`. Zatim pokreni `sudo systemctl restart forexbot`.

## Realna očekivanja (500 €)
- Rizik po trejdu je oko 5 €, a cilj po uspješnom trejdu oko 10 €.
- Očekuj otprilike **30–40% uspješnih trejdova**. Strategija zarađuje samo ako su dobitni trejdovi dovoljno veći od gubitnih.
- Dobar mjesec donese možda **+10 do +30 €**, a loši mjeseci (−20 do −40 €) su normalni.
- Swap (noćna kamata) i proklizavanje cijene nisu u backtestu, pa je stvarni rezultat obično malo lošiji.

## Za developere
```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m forexbot backtest --csv moji_podaci.csv   # CSV: time,open,high,low,close
```
Struktura: `forexbot/strategy.py` (signali), `risk.py` (veličina pozicije),
`oanda.py` (API), `bot.py` (glavna petlja), `backtest.py`, `telegram.py`.
