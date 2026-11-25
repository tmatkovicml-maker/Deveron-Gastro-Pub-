# Prijava smjena: Echoes of the Island, Advent na Lošinju 2026.

Mala web aplikacija preko koje punoljetni učenici sami biraju smjene u adventskoj kućici na Trgu Republike Hrvatske u Malom Lošinju (10. 12. 2026. – 2. 1. 2027.). Stranica se otvara skeniranjem QR koda s letka, s mobitela i bez ikakvog računa.

- **Učenik** (`/`) bira termine po danima (blok A i B), upisuje ime i prezime i broj mobitela, potvrđuje da ima 18 godina i pristaje na obradu podataka. Nakon prijave dobiva **privatnu poveznicu** (`/moji/…`) na kojoj vidi svoje termine i može ih otkazati do roka.
- **Organizator** (`/admin`, lozinka) vidi tko je na kojem terminu (ime, mobitel) i koliko je mjesta ostalo. Ima i pregled po osobi sa satima po tjednu, ručno dodavanje i uklanjanje prijava, broj mjesta po terminu, otvaranje i zatvaranje prijava, izvoz u CSV za Excel, učitavanje termina iz CSV-a, QR kod i brisanje podataka.

## Pravila (provjerava ih poslužitelj, ne samo preglednik)
- **Pun termin se odmah zatvara.** Broj mjesta provjerava se na poslužitelju u jednoj transakciji. Sve prijave obrađuje jedan Cloudflare Durable Object, i to jednu po jednu, pa dvije istovremene prijave ne mogu zauzeti isto zadnje mjesto. To dokazuje test u kojem se 30 ljudi istovremeno prijavljuje na jedno mjesto i samo jedan uspije.
- **Najviše 30 sati tjedno** po osobi, po ISO tjednima (10.–13.12. je 50. tjedan, a 28.12.–2.1. je 53. tjedan).
- **Najviše jedan blok dnevno** po osobi.
- Osoba se prepoznaje po **broju mobitela**. Zapisi „091 234 5678”, „+385 91 234 5678” i „00385912345678” vode se kao isti broj.
- Ako jedan termin iz prijave ne prolazi, ne sprema se ništa i učenik dobiva objašnjenje zašto.
- Zaštita od zlouporabe: najviše 15 prijava po IP adresi u 10 minuta, skriveno polje (honeypot) za botove i 10 pogrešnih lozinki po IP adresi u 15 minuta.

## Termini
Početno je učitano 48 termina: svaki dan blok **A 09:00–16:00 (7 h, 1 osoba)** i blok **B 16:00–24:00 (8 h, 2 osobe)**. Blok B traje do 03:00 (11 h) na 24.12., 27.12. i 31.12.

**Vaš `Termini_prijave.csv`** (s koncertnim danima: A=2, B=3) učitajte u `/admin` → **Postavke** → **Termini iz CSV-a**. Stupci se prepoznaju po nazivima u bilo kojem redoslijedu, a razdjelnik može biti `;` ili `,`:

| Datum | Blok | Od | Do | Sati | Mjesta |
|---|---|---|---|---|---|
| 10.12.2026. | A | 09:00 | 16:00 | 7 | 1 |

- Umjesto stupaca Od i Do može biti jedan stupac **Vrijeme** („09:00–16:00”).
- Bez stupca **Sati** sati se računaju iz vremena.
- Primjer je u datoteci `termini-primjer.csv`.
- Postojeće prijave ostaju. Termin na kojem već ima prijava ne može se maknuti, a broj mjesta može se mijenjati.
- Broj mjesta za pojedini termin može se promijeniti i izravno u popisu termina.

## Postavke (`/admin` → Postavke)
| Postavka | Zadano | Značenje |
|---|---|---|
| Rok za otkazivanje | **48 h** prije početka smjene | Poslije toga učenik ne može sam otkazati, nego se javlja organizatoru. 0 znači da može otkazati sve do početka smjene. |
| Ručna potvrda | **isključena**, prijava vrijedi odmah | Ako je uključite, svaka prijava čeka vašu potvrdu, ali mjesto je već zauzeto. Učenik stanje vidi na svojoj poveznici. |
| Satnica i uvjeti rada | prazno | Prikazuju se učenicima samo ako ih upišete. |
| Organizator | prazno | Naziv i kontakt za obavijest o privatnosti. |
| Automatsko brisanje | **31. 1. 2027.** | Tog dana se brišu sva imena i mobiteli, a prijave se zatvaraju. |

## Puštanje na internet (Cloudflare Workers, besplatni plan)
Isto kao aplikacije za apartmane i za Deveron: Cloudflare sam objavljuje aplikaciju iz GitHuba.

1. Na dash.cloudflare.com: **Workers & Pages** → **Create** → **Import a repository** → odaberite ovaj repozitorij (grana `main`). Cloudflare čita `wrangler.toml` i napravi Worker **`advent-prijave`**.
2. **Settings → Variables and Secrets → Add** → vrsta **Secret**, naziv `ADMIN_PASSWORD`, vrijednost je vaša lozinka (dugačka, ne ista kao drugdje).
3. Stranica radi na `https://advent-prijave.<vaš-račun>.workers.dev/`. HTTPS je uključen sam od sebe.
4. *(Po želji)* Vlastita domena: **Settings → Domains & Routes → Add → Custom domain**, npr. `prijave.vasa-domena.hr`. Zatim dodajte varijablu `PUBLIC_URL` = `https://prijave.vasa-domena.hr/` (vrsta Text), da QR kod vodi na nju.
5. Otvorite `/admin`, upišite lozinku, učitajte svoj CSV termina i ispunite postavke.

## QR kod za letak
- U `/admin` → **Postavke** → **QR kod za letak** preuzmite **SVG** (vektorski, najbolji za tisak) ili **PNG** (≈1500 px ili ≈3000 px, 300 dpi). QR kod vodi na adresu na kojoj je stranica otvorena (ili na `PUBLIC_URL`).
- Izravne adrese: `/qr.svg` i `/qr.png`.
- Na računalu: `npm install` pa `npm run qr -- https://advent-prijave.<vaš-račun>.workers.dev/`. Datoteke se spreme u mapu `qr/`.
- Prije tiska skenirajte QR kod mobitelom.

## Privatnost
- Prikuplja se samo ime i prezime, broj mobitela i odabrani termini. Uz to se za ograničenje broja zahtjeva čuva IP adresa, najviše jedan dan.
- Javni dio ne prikazuje ni imena ni brojeve, nego samo broj slobodnih mjesta. Na privatnoj poveznici osoba vidi samo svoje termine.
- Nema analitike, kolačića ni vanjskih servisa. Fontovi (Barlow, licenca OFL) i logo poslužuju se iz same aplikacije, a podaci se ne šalju trećim stranama.
- Stranice `/moji/…` i `/admin` nisu indeksirane.

## Brisanje podataka nakon sezone
1. **Izvoz**: `/admin` → **⬇ Izvoz CSV (Excel)** (datum, dan, tjedan, blok, vrijeme, sati, ime, mobitel, status).
2. **Brisanje**:
   - Automatski: na datum iz postavke „Automatsko brisanje” (zadano 31. 1. 2027.) brišu se sve prijave i zatvaraju se prijave.
   - Odmah: `/admin` → **Postavke** → **Brisanje podataka** → upišite `OBRIŠI` → **Obriši sve prijave**.
3. **Potpuno uklanjanje** (po želji): na Cloudflareu **Workers & Pages → advent-prijave → Settings → Delete**. To briše i bazu.

## Lokalno pokretanje i testovi
```bash
npm install
echo 'ADMIN_PASSWORD=test' > .dev.vars
npm run dev                 # http://localhost:8787  i  /admin (lozinka: test)
npm test                    # pravila: mobitel, ISO tjedni, 30 h, jedan blok dnevno, CSV
npm run test:server         # pravi poslužitelj (wrangler dev): istovremene prijave, otkazivanje, admin, izvoz, QR
```

## Datoteke
- `src/index.js`: poslužitelj (Worker) i baza (Durable Object, SQLite)
- `src/rules.js`: pravila (mobitel, tjedni, 30 h, jedan blok dnevno, CSV termina)
- `src/public.html`: stranica za učenike
- `src/admin.html`: stranica za organizatora
- `src/qr.js` i `scripts/qr.js`: QR kod (SVG i PNG)
- `public/`: logo i fontovi
- `test/`: testovi
