# Apartmani – aplikacija za goste

Mala web aplikacija za goste apartmana na Lošinju:
- **informacije**: apartman (Wi-Fi, check-in/out, adresa, kontakt, kućni red…), Mali Lošinj, otok, plaže, restorani, korisni brojevi i trajekti
- **prijava gostiju za eVisitor**: gost sam upiše podatke iz putovnice / osobne za sve osobe
- jezici: hrvatski, engleski, njemački, talijanski (gost bira, a zadano je jezik koji odaberete kod boravka)

Stranica **nije javna**: za svaki boravak napravite link (`/g/…`) i pošaljete ga gostu. Bez linka se ne vidi ništa, a link radi do 3 dana nakon odlaska.

## Privatnost
- Podaci s putovnica čuvaju se **najviše 7 dana** nakon što ih gost pošalje, a zatim ih Worker **sam trajno briše** (Durable Object alarm). Gumbom „Obriši podatke s putovnica sada" možete ih obrisati i ranije.
- U evidenciji ostaju samo **prezime, datumi boravka**, apartman i broj gostiju.
- Gost ne može vidjeti već poslane podatke s putovnice, nego samo imena. Nacrt obrasca ostaje samo na njegovom mobitelu, pa ga može ispraviti.
- Stranice nisu indeksirane (noindex), a link se ne šalje drugim stranicama (no-referrer).

## Postavljanje (jednom)
1. Cloudflare → **Workers & Pages** → **Create** → **Import a repository** → `Deveron-Gastro-Pub-` → **Deploy** (ostalo ostaviti kako jest).
2. Worker `apartmani` → **Settings** → **Variables and Secrets** → **Add** → type **Secret**, ime `ADMIN_PIN`, vrijednost vaš PIN (npr. 6 znamenki).
3. Otvorite `https://apartmani.<vaš-račun>.workers.dev/admin` i upišite PIN.
4. Neobavezno: **Settings → Domains & Routes → Add → Custom domain**, npr. `apartmani.deveronpub.com`, da link izgleda ljepše.

## Administracija (`/admin`)
- **🗓 Boravci**: novi boravak (apartman, prezime, dolazak, odlazak, broj gostiju, jezik) → „Napravi link" → pošaljite preko WhatsAppa, SMS-a ili e-maila (poruka je već napisana na jeziku gosta).
  Kad gost pošalje prijavu, boravak dobije oznaku „Prijavljeno – upiši u eVisitor". „🛂 Podaci za eVisitor" prikazuje podatke istim redom kao eVisitor (dodir kopira podatak). Nakon upisa označite „✓ Upisano u eVisitor" i gost više ne može mijenjati prijavu.
- **📒 Evidencija**: svi boravci po godini (prezime, datumi, noći, apartman, broj gostiju) i izvoz u CSV.
- **🏠 Apartmani**: naziv, adresa, link na kartu, Wi-Fi, check-in/out, telefon i upute (dolazak, kućni red, smeće, parking…). Može ih biti više.
- **📝 Sadržaj**: mjesto, otok, plaže, restorani, korisno. Svaka stavka ima naslov, tekst, link i sliku, za svaki jezik posebno. Ako prijevod nedostaje, gost vidi engleski pa hrvatski.
- **⚙️ Postavke**: ime i kontakt domaćina (prikazuje se u obavijesti o zaštiti podataka).

Početni tekstovi su samo primjer (`src/content.js`). Provjerite ih i dopunite u administraciji (Wi-Fi, adrese, vaše omiljene plaže i restorane).

## eVisitor
eVisitor nema besplatno sučelje kroz koje bi privatni iznajmljivač automatski slao prijave, pa se podaci prepisuju ručno. Aplikacija ih zato prikazuje pregledno i redom kao u eVisitoru. Gost upisuje: ime, prezime, spol, datum rođenja, državu (i mjesto) rođenja, državljanstvo, državu i mjesto prebivališta, vrstu i broj isprave te približno vrijeme dolaska.

## API
- `GET /api/g/:token` – podaci za stranicu gosta
- `POST /api/g/:token/guests` – prijava `{guests: [...], arrival_time}`
- `GET /api/admin/data`, `POST /api/admin/apartments|content|host`, `POST /api/admin/stays`, `POST /api/admin/stays/:id`, `POST /api/admin/stays/:id/entered|wipe`, `DELETE /api/admin/stays/:id` (zaglavlje `X-Admin-Pin`)

Zaštita: nakon 10 pogrešnih PIN-ova s iste adrese prijava je blokirana 15 minuta. Nakon 30 nepostojećih linkova u sat vremena adresa je blokirana, a jedan boravak može poslati najviše 20 prijava dnevno.

Lokalno testiranje: `npx wrangler dev` uz datoteku `.dev.vars` (`ADMIN_PIN=1234`).
