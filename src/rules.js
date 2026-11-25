// Rules shared by the Worker and the tests: phone numbers, ISO weeks, the starting shifts,
// the CSV of shifts, and the check of a person's choice (one block a day, at most 30 hours a week).

export const MAX_WEEK_HOURS = 30;

// ---- phone numbers: one person = one normalized mobile number ----
// "091 234 5678", "+385 91 234 5678", "00385912345678" and "385912345678" are all "+385912345678"
export function normalizePhone(v) {
  let s = String(v ?? '').replace(/[\s\-\/().]/g, '');
  if (s.startsWith('00')) s = '+' + s.slice(2);
  else if (/^385\d{8,9}$/.test(s)) s = '+' + s;
  else if (/^0\d{8,10}$/.test(s)) s = '+385' + s.slice(1);
  else if (/^9\d{7,8}$/.test(s)) s = '+385' + s;
  if (s.startsWith('+3850')) s = '+385' + s.slice(5);       // "+385 (0)91 …"
  if (!/^\+[1-9]\d{7,14}$/.test(s)) return null;
  if (s.startsWith('+385') && !/^\+3859\d{7,8}$/.test(s)) return null;   // Croatian numbers must be mobile (9x)
  return s;
}

// "+385912345678" → "091 234 5678" (for the organizer's lists and the export)
export function formatPhone(p) {
  const m = /^\+385(9\d)(\d{3})(\d{3,4})$/.exec(p || '');
  return m ? `0${m[1]} ${m[2]} ${m[3]}` : p;
}

// ---- ISO weeks: 10.12.2026–02.01.2027 are weeks 50, 51, 52 and 53 of 2026 ----
export function isoWeek(day) {
  const d = new Date(day + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7 + 3);   // Thursday of the same week decides the year
  const year = d.getUTCFullYear();
  const week = 1 + Math.floor((d - Date.UTC(year, 0, 1)) / 86400000 / 7);
  return `${year}-W${String(week).padStart(2, '0')}`;
}

export const isDay = v => {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const d = new Date(v + 'T12:00:00Z');
  return !isNaN(d) && d.toISOString().slice(0, 10) === v;
};
export const addDays = (day, n) => { const d = new Date(day + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const toMin = t => +t.slice(0, 2) * 60 + +t.slice(3, 5);
// hours between two times; a shift that ends at or before it starts ends the next day (16:00–03:00 = 11 h)
export const hoursBetween = (start, end) => { let m = toMin(end) - toMin(start); if (m <= 0) m += 24 * 60; return Math.round(m / 6) / 10; };

// Shift start as a timestamp. December and January are always winter time in Croatia (UTC+1).
export const slotStartMs = s => Date.parse(`${s.day}T${s.start}:00+01:00`);

// ---- the starting shifts: 10.12.2026–02.01.2027, every day A 09–16 (1 person) and B 16–24 (2 people);
// B lasts until 03:00 on 24.12., 27.12. and 31.12. The organizer's own CSV replaces these in /admin.
export const SEASON_FIRST = '2026-12-10', SEASON_LAST = '2027-01-02';
const LONG_NIGHTS = ['2026-12-24', '2026-12-27', '2026-12-31'];
export function defaultSlots() {
  const out = [];
  for (let day = SEASON_FIRST; day <= SEASON_LAST; day = addDays(day, 1)) {
    out.push(makeSlot(day, 'A', '09:00', '16:00', 1));
    const long = LONG_NIGHTS.includes(day);
    out.push(makeSlot(day, 'B', '16:00', long ? '03:00' : '00:00', 2));
  }
  return out;
}
export function makeSlot(day, block, start, end, capacity, hours) {
  return { id: `${day}-${block}`, day, block, start, end, hours: hours || hoursBetween(start, end), capacity };
}

// ---- the organizer's CSV of shifts ----
// The columns are recognized by their headings (any order, ";" or "," or tab):
//   Datum (10.12.2026. / 2026-12-10 / 10.12.), Blok (A/B), Od + Do or Vrijeme ("09:00–16:00"), Sati, Mjesta.
// Without Blok the block follows from the start time (before noon = A). Without Sati the hours follow from the times.
const fold = s => String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').trim();

function splitCsvLine(lineText, sep) {
  const out = []; let cur = '', q = false;
  for (let i = 0; i < lineText.length; i++) {
    const c = lineText[i];
    if (q) { if (c === '"' && lineText[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
    else if (c === '"') q = true;
    else if (c === sep) { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out.map(s => s.trim());
}

export function parseDate(v) {
  const s = String(v).trim().replace(/\.$/, '');
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (m) return fmtDay(+m[1], +m[2], +m[3]);
  m = /(?:^|\s)(\d{1,2})\.\s*(\d{1,2})\.?\s*(\d{4})?$/.exec(s);       // "čet 10.12.2026" too
  if (m) return fmtDay(m[3] ? +m[3] : (+m[2] >= 7 ? 2026 : 2027), +m[2], +m[1]);
  m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(s);
  if (m) return fmtDay(+m[3], +m[2], +m[1]);
  return null;
}
const fmtDay = (y, mo, d) => { const v = `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`; return isDay(v) ? v : null; };
const parseTime = v => {
  const m = /^(\d{1,2})(?:[:.h](\d{2}))?h?$/.exec(String(v).trim());
  if (!m || +m[1] > 24 || +(m[2] || 0) > 59) return null;
  return `${String(+m[1] % 24).padStart(2, '0')}:${m[2] || '00'}`;
};
const parseNum = v => { const n = Number(String(v).trim().replace(',', '.').replace(/\s*h$/i, '')); return Number.isFinite(n) ? n : null; };

export function parseSlotsCsv(text) {
  const lines = String(text).replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) throw new Error('CSV nema redaka s terminima.');
  const sep = [';', '\t', ','].sort((a, b) => lines[0].split(b).length - lines[0].split(a).length)[0];
  const head = splitCsvLine(lines[0], sep).map(fold);
  const rows = lines.slice(1).map(l => splitCsvLine(l, sep));
  const find = (...names) => head.findIndex(h => names.some(n => h === n || (n.length > 2 && h.startsWith(n))));
  // date column: "Datum" by name, otherwise the first column whose values are dates
  let iDate = find('datum', 'date');
  if (iDate < 0) iDate = head.findIndex((_, i) => rows.every(r => parseDate(r[i] || '')));
  const iBlock = find('blok', 'block', 'smjena', 'termin');
  const iFrom = find('od', 'pocetak', 'start', 'from');
  const iTo = find('do', 'kraj', 'end', 'to');
  const iTime = find('vrijeme', 'time');
  const iHours = find('sati', 'hours', 'trajanje', 'h');
  const iCap = find('mjesta', 'kapacitet', 'broj osoba', 'osoba', 'capacity');
  if (iDate < 0) throw new Error('Nema stupca s datumom (npr. "Datum").');
  if (iCap < 0) throw new Error('Nema stupca s brojem mjesta (npr. "Mjesta").');

  const slots = [], errors = [];
  rows.forEach((r, n) => {
    const at = `Redak ${n + 2}`;
    const day = parseDate(r[iDate] || '');
    if (!day) return errors.push(`${at}: neispravan datum "${r[iDate] || ''}"`);
    let start = iFrom >= 0 ? parseTime(r[iFrom] || '') : null, end = iTo >= 0 ? parseTime(r[iTo] || '') : null;
    if (!start || !end) {   // "Vrijeme" column, or any cell like "09:00–16:00"
      const cell = iTime >= 0 ? r[iTime] : r.find(c => /^\d{1,2}[:.]\d{2}\s*[–—\-]\s*\d{1,2}[:.]\d{2}$/.test(c));
      const m = String(cell || '').split(/\s*[–—\-]\s*/);
      if (m.length === 2) { start = parseTime(m[0]); end = parseTime(m[1]); }
    }
    let block = iBlock >= 0 ? (String(r[iBlock] || '').toUpperCase().match(/\b([AB])\b/) || [])[1] : null;
    if (!block && start) block = toMin(start) < 12 * 60 ? 'A' : 'B';
    if (!start || !end) {
      if (block === 'A') { start = '09:00'; end = '16:00'; }
      else if (block === 'B') { start = '16:00'; end = '00:00'; }
    }
    if (!block || !start || !end) return errors.push(`${at}: nedostaje blok ili vrijeme`);
    const cap = parseNum(r[iCap] || '');
    if (cap === null || cap < 0 || cap > 50 || !Number.isInteger(cap)) return errors.push(`${at}: neispravan broj mjesta "${r[iCap] || ''}"`);
    const h = iHours >= 0 && String(r[iHours] || '').trim() ? parseNum(r[iHours]) : hoursBetween(start, end);
    if (h === null || h <= 0 || h > 24) return errors.push(`${at}: neispravan broj sati "${r[iHours] || ''}"`);
    slots.push(makeSlot(day, block, start, end, cap, h));
  });
  const seen = new Set();
  for (const s of slots) { if (seen.has(s.id)) errors.push(`Termin ${s.day} ${s.block} se ponavlja`); seen.add(s.id); }
  if (errors.length) throw new Error(errors.slice(0, 8).join('\n') + (errors.length > 8 ? `\n… još ${errors.length - 8}` : ''));
  if (!slots.length) throw new Error('CSV nema termina.');
  return slots.sort((a, b) => a.id.localeCompare(b.id));
}

// ---- a person's choice ----
// existing: the person's shifts already booked [{day, hours}], chosen: the new shifts [{id, day, hours}].
// Returns null or {error, day|week, hours}.
export function checkChoice(existing, chosen, maxWeek = MAX_WEEK_HOURS) {
  const days = new Set(existing.map(s => s.day));
  for (const s of chosen) {
    if (days.has(s.day)) return { error: 'one_per_day', day: s.day, slot: s.id };
    days.add(s.day);
  }
  const weeks = {};
  for (const s of [...existing, ...chosen]) { const w = isoWeek(s.day); weeks[w] = (weeks[w] || 0) + s.hours; }
  for (const [w, h] of Object.entries(weeks)) {
    if (h > maxWeek + 1e-9 && chosen.some(s => isoWeek(s.day) === w)) return { error: 'week_hours', week: w, hours: h };
  }
  return null;
}

export function weekHours(list) {
  const weeks = {};
  for (const s of list) { const w = isoWeek(s.day); weeks[w] = Math.round(((weeks[w] || 0) + s.hours) * 10) / 10; }
  return weeks;
}
