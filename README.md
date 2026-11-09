# Čišćenje apartmana

Web aplikacija za firmu koja čisti apartmane drugih vlasnika: klijenti, njihovi apartmani, raspored čišćenja, čistačice i mjesečni obračun.

## Što radi
- **Raspored iz Booking.com / Airbnb kalendara.** Za svaki objekt upišete iCal link(ove) koje vam pošalje vlasnik. Svakih 30 minuta aplikacija ih pročita i **svaki odlazak gostiju postaje čišćenje** na taj dan. Ako je rezervacija otkazana, čišćenje se samo otkaže, a ako se vrati, vraća se i čišćenje. Ista rezervacija u dva kalendara (Booking i Airbnb) računa se samo jednom.
- **⚡ Isti dan dolazak**: vidi se kad novi gosti dolaze na dan čišćenja, a inače datum sljedećeg dolaska.
- **Čistačice** dobiju tajni link (bez lozinke) koji spreme na početni zaslon mobitela. U njemu vide:
  - svoja čišćenja za sljedeća 2 tjedna te slobodne poslove koje mogu preuzeti („🙋 Preuzimam”),
  - adresu s navigacijom, **ulaz (ključ, šifru)** i upute, ali samo za svoje poslove,
  - **listu zadataka** po prostorijama s kvačicama,
  - „▶️ Počinjem” i „✅ Gotovo”, uz polje za **štetu ili kvar** te napomenu,
  - kalendar za mobitel (📅) i broj svojih čišćenja u mjesecu.
  
  **Cijene i klijente čistačice ne vide.**
- **Ručna čišćenja**: međučišćenje, generalno ili bilo što drugo, s vremenom, brojem osoba za koje se priprema i napomenom.
- **Obračun po mjesecu**: po klijentu (cijena + dodatno, npr. pranje rublja), oznaka „plaćeno”, poruka s obračunom preko WhatsAppa ili e-maila i izvoz u CSV (Excel). Ima i obračun za ekipu: broj čišćenja, sati i plaća po čišćenju ili po satu.
- **WhatsApp jednim dodirom**: pošaljite čistačici posao ili link, a vlasniku poruku „apartman je očišćen”.
- **Telegram obavijesti** (neobavezno): očišćeno (⚠️ ako je prijavljena šteta), netko je preuzeo posao, nova ili otkazana rezervacija, kalendar se ne može pročitati.
- **Google kalendar** sa svim čišćenjima (tajni link).

## Postavljanje (jednom)
1. Cloudflare → **Workers & Pages** → **Create** → **Import a repository** → odaberite ovaj repozitorij → **Deploy** (ostalo ostaviti kako jest).
2. Worker `ciscenje` → **Settings** → **Variables and Secrets** → **Add** → type **Secret**, ime `ADMIN_PIN`, vrijednost vaš PIN (npr. 6 znamenki).
3. Otvorite `https://ciscenje.<vaš-račun>.workers.dev/admin` i upišite PIN.
4. Redom: **⚙️ Postavke** (naziv firme, telefon) → **🧹 Ekipa** (čistačice, i vi ako čistite) → **👤 Klijenti** (vlasnici) → **🏠 Objekti** (apartmani s linkovima kalendara, cijenom, ulazom, uputama i listom zadataka).
5. U **🧹 Ekipa** dodirnite „💬 Pošalji link” za svaku osobu.

Neobavezno: **Settings → Domains & Routes → Add → Custom domain**, npr. `ciscenje.vasadomena.hr`.

## Gdje vlasnik nalazi link kalendara
- **Booking.com**: Extranet → Cijene i dostupnost → Sinkronizacija kalendara → Izvoz kalendara → kopirati link.
- **Airbnb**: Kalendar → oglas → Dostupnost → Poveži kalendare → Izvoz kalendara → kopirati link.
- Ostali (npr. channel manager) uglavnom imaju „iCal export”.

Ako objekt nema kalendar, čišćenja dodajete ručno („＋ Dodaj čišćenje”).

## Obavijesti na Telegram (neobavezno)
1. U Telegramu otvorite **@BotFather** → `/newbot` → upišite ime → dobijete token.
2. Cloudflare → Worker `ciscenje` → **Settings → Variables and Secrets → Add → Secret**, ime `TELEGRAM_BOT_TOKEN`, vrijednost token.
3. Svaka osoba koja želi obavijesti pošalje botu `/start`. Zatim u `/admin` → **⚙️ Postavke** dodirnete „Poveži i pošalji probnu poruku”.

## Sigurnost
- Administracija traži PIN. Nakon 10 pogrešnih pokušaja s iste adrese prijava je blokirana 15 minuta.
- Link čistačice je ključ: „Novi link” poništava stari, a arhiviranje osobe gasi njezin link. Nakon 30 nepostojećih linkova u sat vremena adresa se blokira.
- Šifru ulaza vidi samo osoba kojoj je posao dodijeljen. Stranice nisu indeksirane, a link se ne šalje drugim stranicama (no-referrer).

## Tehnički
Cloudflare Worker (`src/index.js`) s jednim Durable Objectom (SQLite) i cron okidačem svakih 30 minuta (`wrangler.toml`). Početna lista zadataka nalazi se u `src/checklist.js`, a uređuje se po objektu u administraciji.

Lokalno testiranje: `npx wrangler dev` uz datoteku `.dev.vars` (`ADMIN_PIN=1234`). Cron se može pokrenuti ovako: `npx wrangler dev --test-scheduled` pa `curl "localhost:8787/__scheduled"`.
