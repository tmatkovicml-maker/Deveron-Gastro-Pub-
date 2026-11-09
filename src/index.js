// Apartment cleaning business: clients (owners), their apartments, the cleaning schedule
// and the cleaners.
//
// Cleaning jobs come from the apartments' Booking.com / Airbnb calendars (iCal links, read every
// 30 minutes): every departure is a cleaning on that day. Jobs can also be added by hand.
// Each cleaner has a secret link (/r/<token>) with their jobs, the address, the entry instructions
// and the checklist; they start and finish the job there and report problems.
// Prices and clients are never shown to cleaners.
//
// Owner (X-Admin-Pin = ADMIN_PIN):
//   GET  /api/admin/data                    everything for the owner page
//   POST /api/admin/clients                 {id?, name, phone, email, note}
//   POST /api/admin/clients/:id/archive     {on}
//   POST /api/admin/apts                    {id?, client_id, name, address, map, access, info, checkout, checkin,
//                                            price, minutes, cleaner_id, checklist: [..], icals: [..]}
//   POST /api/admin/apts/:id/archive        {on}
//   POST /api/admin/cleaners                {id?, name, phone, rate_job, rate_hour}
//   POST /api/admin/cleaners/:id/archive    {on}
//   POST /api/admin/cleaners/:id/renew      new secret link (the old one stops working)
//   POST /api/admin/jobs                    {id?, apt_id, date, time, type, cleaner_id, guests, price, extra, extra_note, note}
//   POST /api/admin/jobs/:id/(cancel|restore|reopen|done)
//   DELETE /api/admin/jobs/:id              hand-made jobs only (calendar jobs are cancelled instead)
//   POST /api/admin/paid                    {ids: [..], on}  charged to the client
//   POST /api/admin/company                 {name, phone, email}
//   POST /api/admin/sync                    {apt_id?}  read the calendars now
//   POST|DELETE /api/admin/telegram         Telegram notifications (TELEGRAM_BOT_TOKEN)
//   POST /api/admin/calendar                {renew?} → secret calendar link /cal/<token>.ics
// Cleaner (token from the link):
//   GET  /api/r/:token                      their jobs from yesterday to 14 days ahead + jobs nobody took
//   POST /api/r/:token/jobs/:id/(take|start|checks|finish|undo)
//   GET  /r/:token.ics                      their jobs for the phone calendar
// Pages: /admin owner · /r/:token cleaner
import { DurableObject } from 'cloudflare:workers';
import ADMIN_PAGE from './admin.html';
import CLEANER_PAGE from './cleaner.html';
import HOME_PAGE from './home.html';
import { DEFAULT_CHECKLIST } from './checklist.js';

const MINUTE = 60 * 1000, HOUR = 60 * MINUTE, DAY = 24 * HOUR;
const JOB_TYPES = ['turnover', 'mid', 'deep', 'other'];
const TYPE_NAMES = { turnover: 'Izlazno čišćenje', mid: 'Međučišćenje', deep: 'Generalno čišćenje', other: 'Ostalo' };
const CLEANER_DAYS_AHEAD = 14;
const UNDO_HOURS = 12;           // a cleaner can undo "finished" for this long
const SYNC_DAYS_AHEAD = 400;

const zagrebDay = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Europe/Zagreb' });
const zagrebTime = ts => new Date(ts).toLocaleTimeString('hr-HR', { timeZone: 'Europe/Zagreb', hour: '2-digit', minute: '2-digit' });
const addDays = (day, n) => { const d = new Date(day + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const isDay = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !isNaN(new Date(v + 'T12:00:00Z')) && new Date(v + 'T12:00:00Z').toISOString().slice(0, 10) === v;
const str = (v, max) => String(v ?? '').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, '').trim().slice(0, max);
const line = (v, max) => str(v, max).replace(/\s+/g, ' ');
const safeLink = v => { const s = line(v, 1000); return /^https?:\/\//i.test(s) ? s : ''; };
const hhmm = v => /^([01]\d|2[0-3]):[0-5]\d$/.test(v) ? v : '';
const money = v => { const n = Math.round(parseFloat(String(v ?? '').replace(',', '.')) * 100) / 100; return isFinite(n) && n > 0 ? Math.min(n, 100000) : 0; };
const intIn = (v, min, max) => { const n = parseInt(v, 10); return isFinite(n) ? Math.max(min, Math.min(max, n)) : min; };
const idOrNull = v => { const n = parseInt(v, 10); return n > 0 ? n : null; };
const hrDay = d => `${+d.slice(8, 10)}.${+d.slice(5, 7)}.`;

function newToken() {
  const b = crypto.getRandomValues(new Uint8Array(18));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function sameString(a, b) {
  const x = new TextEncoder().encode(String(a)), y = new TextEncoder().encode(String(b));
  if (x.length !== y.length) return false;
  let d = 0;
  for (let i = 0; i < x.length; i++) d |= x[i] ^ y[i];
  return d === 0;
}

// ---- validation ----
const validClient = c => ({ id: idOrNull(c?.id), name: line(c?.name, 100), phone: line(c?.phone, 30), email: line(c?.email, 100), note: str(c?.note, 1000) });
function validApt(a) {
  const lines = (v, n, max) => (Array.isArray(v) ? v : String(v ?? '').split('\n')).map(x => line(x, max)).filter(Boolean).slice(0, n);
  return {
    id: idOrNull(a?.id), client_id: idOrNull(a?.client_id), name: line(a?.name, 80), address: line(a?.address, 160), map: safeLink(a?.map),
    access: str(a?.access, 1000), info: str(a?.info, 3000), checkout: hhmm(a?.checkout), checkin: hhmm(a?.checkin),
    price: money(a?.price), minutes: intIn(a?.minutes, 0, 1440), cleaner_id: idOrNull(a?.cleaner_id),
    checklist: lines(a?.checklist, 80, 200), icals: lines(a?.icals, 5, 1000).map(safeLink).filter(Boolean),
  };
}
const validCleaner = c => ({ id: idOrNull(c?.id), name: line(c?.name, 60), phone: line(c?.phone, 30), rate_job: money(c?.rate_job), rate_hour: money(c?.rate_hour) });
function validJob(j) {
  const v = {
    id: idOrNull(j?.id), apt_id: idOrNull(j?.apt_id), date: line(j?.date, 10), time: hhmm(j?.time),
    type: JOB_TYPES.includes(j?.type) ? j.type : 'turnover', cleaner_id: idOrNull(j?.cleaner_id),
    guests: intIn(j?.guests, 0, 30), price: money(j?.price), extra: money(j?.extra), extra_note: line(j?.extra_note, 120), note: str(j?.note, 1000),
  };
  return v.apt_id && isDay(v.date) ? v : null;
}

// ---- iCal (Booking.com, Airbnb, …): occupied periods ----
function parseIcs(text) {
  const lines = text.replace(/\r\n[ \t]/g, '').replace(/\n[ \t]/g, '').split(/\r?\n/);
  const out = [];
  let ev = null;
  for (const l of lines) {
    if (l === 'BEGIN:VEVENT') ev = {};
    else if (l === 'END:VEVENT') {
      if (ev && ev.start && !ev.cancelled) {
        const end = ev.end && ev.end > ev.start ? ev.end : addDays(ev.start, 1);
        out.push({ start: ev.start, end });
      }
      ev = null;
    } else if (ev) {
      const m = l.match(/^(DTSTART|DTEND|STATUS)(?:;[^:]*)?:(.*)$/);
      if (!m) continue;
      if (m[1] === 'STATUS') { ev.cancelled = /CANCELLED/i.test(m[2]); continue; }
      const d = m[2].match(/^(\d{4})(\d{2})(\d{2})/);
      if (d && isDay(`${d[1]}-${d[2]}-${d[3]}`)) ev[m[1] === 'DTSTART' ? 'start' : 'end'] = `${d[1]}-${d[2]}-${d[3]}`;
    }
  }
  return out;
}
// The same booking often shows up in two calendars (Booking blocks the dates on Airbnb and the
// other way round), so overlapping periods are joined. Back-to-back stays stay separate.
function mergeRanges(list) {
  const sorted = [...list].sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
  const out = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r.start < last.end) { if (r.end > last.end) last.end = r.end; }
    else out.push({ ...r });
  }
  return out;
}

export class Store extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.env = env;
    const sql = this.sql = ctx.storage.sql;
    sql.exec(`CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)`);
    sql.exec(`CREATE TABLE IF NOT EXISTS limits (k TEXT NOT NULL, at INTEGER NOT NULL)`);
    sql.exec(`CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1)`);
    sql.exec(`CREATE TABLE IF NOT EXISTS apts (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, name TEXT NOT NULL,
      address TEXT NOT NULL DEFAULT '', map TEXT NOT NULL DEFAULT '', access TEXT NOT NULL DEFAULT '', info TEXT NOT NULL DEFAULT '',
      checkout TEXT NOT NULL DEFAULT '', checkin TEXT NOT NULL DEFAULT '', price REAL NOT NULL DEFAULT 0, minutes INTEGER NOT NULL DEFAULT 0,
      cleaner_id INTEGER, checklist TEXT NOT NULL DEFAULT '[]', icals TEXT NOT NULL DEFAULT '[]',
      sync_at INTEGER, sync_err TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1)`);
    sql.exec(`CREATE TABLE IF NOT EXISTS cleaners (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
      token TEXT NOT NULL UNIQUE, rate_job REAL NOT NULL DEFAULT 0, rate_hour REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)`);
    // occupied periods read from the apartment calendars (replaced on every sync)
    sql.exec(`CREATE TABLE IF NOT EXISTS bookings (apt_id INTEGER NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL)`);
    sql.exec('CREATE INDEX IF NOT EXISTS bookings_apt ON bookings (apt_id, start)');
    // status: planned · done · cancelled; cancel_by: 'sync' (gone from the calendar, comes back if it reappears) or 'admin'
    sql.exec(`CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER NOT NULL,
      apt_id INTEGER NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'turnover',
      source TEXT NOT NULL DEFAULT 'manual', ical_key TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'planned', cancel_by TEXT NOT NULL DEFAULT '',
      cleaner_id INTEGER, guests INTEGER NOT NULL DEFAULT 0, price REAL NOT NULL DEFAULT 0, extra REAL NOT NULL DEFAULT 0,
      extra_note TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', started INTEGER, finished INTEGER, done_by INTEGER,
      checks TEXT NOT NULL DEFAULT '[]', report TEXT NOT NULL DEFAULT '', problem TEXT NOT NULL DEFAULT '', paid INTEGER)`);
    sql.exec('CREATE INDEX IF NOT EXISTS jobs_date ON jobs (date)');
  }

  // ---- settings, limits ----
  get(k, fallback) {
    const r = this.sql.exec('SELECT v FROM settings WHERE k = ?', k).toArray()[0];
    return r ? JSON.parse(r.v) : fallback;
  }
  put(k, v) { this.sql.exec('INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v', k, JSON.stringify(v)); }
  count(k, since) { return this.sql.exec('SELECT COUNT(*) AS n FROM limits WHERE k = ? AND at > ?', k, since).one().n; }
  hit(k) {
    this.sql.exec('INSERT INTO limits (k, at) VALUES (?, ?)', k, Date.now());
    this.sql.exec('DELETE FROM limits WHERE at < ?', Date.now() - DAY);
  }
  adminBlocked(ip) { return this.count('pin:' + ip, Date.now() - 15 * MINUTE) >= 10; }
  adminFailed(ip) { this.hit('pin:' + ip); }

  // ---- Telegram ----
  async notify(text) {
    const chats = this.get('tg_chats', []);
    if (!this.env.TELEGRAM_BOT_TOKEN || !chats.length || !text) return;
    await Promise.all(chats.map(c => telegram(this.env, 'sendMessage', { chat_id: c.id, text: text.slice(0, 4000) }).catch(() => {})));
  }
  telegramChats() { return this.get('tg_chats', []); }
  saveTelegramChats(list) { this.put('tg_chats', list); return list; }

  // ---- owner ----
  jobRows(where, ...args) {
    return this.sql.exec(`SELECT j.*, (SELECT MIN(b.start) FROM bookings b WHERE b.apt_id = j.apt_id AND b.start >= j.date) AS next_in
      FROM jobs j WHERE ${where} ORDER BY j.date, j.time, j.id`, ...args).toArray()
      .map(j => ({ ...j, checks: JSON.parse(j.checks) }));
  }
  adminData() {
    const apts = this.sql.exec('SELECT * FROM apts ORDER BY name').toArray()
      .map(a => ({ ...a, checklist: JSON.parse(a.checklist), icals: JSON.parse(a.icals) }));
    return {
      company: this.get('company', { name: '', phone: '', email: '' }),
      clients: this.sql.exec('SELECT * FROM clients ORDER BY name').toArray(),
      apts, cleaners: this.sql.exec('SELECT * FROM cleaners ORDER BY name').toArray(),
      jobs: this.jobRows('j.date >= ?', addDays(zagrebDay(), -800)),
      tg_chats: this.get('tg_chats', []), cal_token: this.get('cal_token', ''),
      default_checklist: DEFAULT_CHECKLIST, today: zagrebDay(),
    };
  }
  saveCompany(c) { this.put('company', { name: line(c?.name, 100), phone: line(c?.phone, 30), email: line(c?.email, 100) }); return { ok: true }; }

  saveClient(c) {
    if (c.id) {
      this.sql.exec('UPDATE clients SET name = ?, phone = ?, email = ?, note = ? WHERE id = ?', c.name, c.phone, c.email, c.note, c.id);
      return { id: c.id };
    }
    return this.sql.exec('INSERT INTO clients (name, phone, email, note) VALUES (?, ?, ?, ?) RETURNING id', c.name, c.phone, c.email, c.note).one();
  }
  archive(table, id, on) {
    if (!['clients', 'apts', 'cleaners'].includes(table)) return { error: 'invalid' };
    this.sql.exec(`UPDATE ${table} SET active = ? WHERE id = ?`, on ? 0 : 1, id);
    return { ok: true };
  }

  async saveApt(a) {
    let id = a.id;
    const icals = JSON.stringify(a.icals);
    if (id) {
      const old = this.sql.exec('SELECT icals FROM apts WHERE id = ?', id).toArray()[0];
      if (!old) return { error: 'not_found' };
      this.sql.exec(`UPDATE apts SET client_id = ?, name = ?, address = ?, map = ?, access = ?, info = ?, checkout = ?, checkin = ?,
        price = ?, minutes = ?, cleaner_id = ?, checklist = ?, icals = ? WHERE id = ?`,
        a.client_id, a.name, a.address, a.map, a.access, a.info, a.checkout, a.checkin, a.price, a.minutes, a.cleaner_id,
        JSON.stringify(a.checklist), icals, id);
      if (old.icals !== icals) {
        this.sql.exec('UPDATE apts SET sync_at = NULL, sync_err = ? WHERE id = ?', '', id);
        if (!a.icals.length) this.sql.exec('DELETE FROM bookings WHERE apt_id = ?', id);
      }
    } else {
      id = this.sql.exec(`INSERT INTO apts (client_id, name, address, map, access, info, checkout, checkin, price, minutes, cleaner_id, checklist, icals)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`,
        a.client_id, a.name, a.address, a.map, a.access, a.info, a.checkout, a.checkin, a.price, a.minutes, a.cleaner_id,
        JSON.stringify(a.checklist.length ? a.checklist : DEFAULT_CHECKLIST), icals).one().id;
    }
    // planned jobs that nobody took yet follow the apartment's cleaner
    if (a.cleaner_id) this.sql.exec(`UPDATE jobs SET cleaner_id = ? WHERE apt_id = ? AND status = 'planned' AND cleaner_id IS NULL AND date >= ?`,
      a.cleaner_id, id, zagrebDay());
    let sync = null;
    if (a.icals.length) sync = await this.sync(id);
    return { id, sync };
  }

  saveCleaner(c) {
    if (c.id) {
      this.sql.exec('UPDATE cleaners SET name = ?, phone = ?, rate_job = ?, rate_hour = ? WHERE id = ?', c.name, c.phone, c.rate_job, c.rate_hour, c.id);
      return { id: c.id };
    }
    return this.sql.exec('INSERT INTO cleaners (name, phone, token, rate_job, rate_hour) VALUES (?, ?, ?, ?, ?) RETURNING id',
      c.name, c.phone, newToken(), c.rate_job, c.rate_hour).one();
  }
  renewCleaner(id) { this.sql.exec('UPDATE cleaners SET token = ? WHERE id = ?', newToken(), id); return { ok: true }; }

  saveJob(j) {
    const apt = this.sql.exec('SELECT * FROM apts WHERE id = ?', j.apt_id).toArray()[0];
    if (!apt) return { error: 'invalid' };
    if (j.id) {
      this.sql.exec(`UPDATE jobs SET apt_id = ?, date = ?, time = ?, type = ?, cleaner_id = ?, guests = ?, price = ?, extra = ?, extra_note = ?, note = ?
        WHERE id = ?`, j.apt_id, j.date, j.time, j.type, j.cleaner_id, j.guests, j.price || apt.price, j.extra, j.extra_note, j.note, j.id);
      return { id: j.id };
    }
    return this.sql.exec(`INSERT INTO jobs (created, apt_id, date, time, type, cleaner_id, guests, price, extra, extra_note, note)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`, Date.now(), j.apt_id, j.date, j.time, j.type,
      j.cleaner_id ?? apt.cleaner_id, j.guests, j.price || apt.price, j.extra, j.extra_note, j.note).one();
  }
  jobAction(id, action) {
    const j = this.sql.exec('SELECT * FROM jobs WHERE id = ?', id).toArray()[0];
    if (!j) return { error: 'not_found' };
    if (action === 'cancel') this.sql.exec(`UPDATE jobs SET status = 'cancelled', cancel_by = 'admin' WHERE id = ? AND status = 'planned'`, id);
    else if (action === 'restore') this.sql.exec(`UPDATE jobs SET status = 'planned', cancel_by = '' WHERE id = ? AND status = 'cancelled'`, id);
    else if (action === 'reopen') this.sql.exec(`UPDATE jobs SET status = 'planned', finished = NULL, done_by = NULL WHERE id = ? AND status = 'done'`, id);
    else if (action === 'done') this.sql.exec(`UPDATE jobs SET status = 'done', finished = COALESCE(finished, ?), done_by = COALESCE(done_by, cleaner_id)
      WHERE id = ? AND status = 'planned'`, Date.now(), id);
    else if (action === 'delete') {
      if (j.source === 'ical') return this.jobAction(id, 'cancel');
      this.sql.exec('DELETE FROM jobs WHERE id = ?', id);
    } else return { error: 'invalid' };
    return { ok: true };
  }
  setPaid(ids, on) {
    for (const id of ids) this.sql.exec(`UPDATE jobs SET paid = ? WHERE id = ? AND status = 'done'`, on ? Date.now() : null, id);
    return { ok: true };
  }

  // ---- calendars: every departure is a cleaning ----
  async sync(onlyAptId) {
    const t = zagrebDay();
    const apts = this.sql.exec('SELECT * FROM apts WHERE active = 1').toArray()
      .filter(a => (!onlyAptId || a.id === onlyAptId) && JSON.parse(a.icals).length);
    const msgs = [], result = [];
    for (const a of apts) {
      let ranges = [];
      try {
        for (const u of JSON.parse(a.icals)) {
          const r = await fetch(u, { headers: { 'User-Agent': 'ciscenje-apartmana/1.0', Accept: 'text/calendar' }, redirect: 'follow' });
          if (!r.ok) throw new Error(`kalendar ${new URL(u).hostname} vraća grešku ${r.status}`);
          const text = await r.text();
          if (!text.includes('BEGIN:VCALENDAR')) throw new Error(`${new URL(u).hostname}: link nije iCal kalendar`);
          ranges.push(...parseIcs(text));
        }
      } catch (e) {
        // keep the jobs as they are when a calendar cannot be read
        this.sql.exec('UPDATE apts SET sync_err = ? WHERE id = ?', line(e.message || 'greška', 200), a.id);
        if (!a.sync_err) msgs.push(`⚠️ ${a.name}: kalendar se ne može pročitati (${line(e.message, 120)})`);
        result.push({ apt: a.id, error: e.message });
        continue;
      }
      const merged = mergeRanges(ranges).filter(r => r.end >= addDays(t, -60) && r.start <= addDays(t, SYNC_DAYS_AHEAD));
      this.sql.exec('DELETE FROM bookings WHERE apt_id = ?', a.id);
      for (const r of merged) this.sql.exec('INSERT INTO bookings (apt_id, start, end) VALUES (?, ?, ?)', a.id, r.start, r.end);

      const ends = new Set(merged.map(r => r.end).filter(e => e >= t && e <= addDays(t, SYNC_DAYS_AHEAD)));
      const first = !a.sync_at;
      const jobs = this.sql.exec(`SELECT * FROM jobs WHERE apt_id = ? AND source = 'ical' AND ical_key >= ?`, a.id, `${a.id}:${t}`).toArray()
        .filter(j => j.ical_key.startsWith(a.id + ':'));
      const known = new Set(jobs.map(j => j.ical_key.slice(String(a.id).length + 1)));
      let added = 0;
      for (const j of jobs) {
        const day = j.ical_key.slice(String(a.id).length + 1);
        if (!ends.has(day) && j.status === 'planned') {
          this.sql.exec(`UPDATE jobs SET status = 'cancelled', cancel_by = 'sync' WHERE id = ?`, j.id);
          msgs.push(`❌ Otkazano čišćenje: ${a.name} · ${hrDay(j.date)} (rezervacija je nestala iz kalendara)`);
        } else if (ends.has(day) && j.status === 'cancelled' && j.cancel_by === 'sync') {
          this.sql.exec(`UPDATE jobs SET status = 'planned', cancel_by = '' WHERE id = ?`, j.id);
          msgs.push(`↩️ Ponovno čišćenje: ${a.name} · ${hrDay(j.date)}`);
        }
      }
      for (const day of [...ends].sort()) {
        if (known.has(day)) continue;
        this.sql.exec(`INSERT INTO jobs (created, apt_id, date, type, source, ical_key, cleaner_id, price)
          VALUES (?, ?, ?, 'turnover', 'ical', ?, ?, ?) ON CONFLICT(ical_key) DO NOTHING`,
          Date.now(), a.id, day, `${a.id}:${day}`, a.cleaner_id, a.price);
        added++;
        if (!first) {
          const sameDay = merged.some(r => r.start === day);
          msgs.push(`🆕 Novo čišćenje: ${a.name} · ${hrDay(day)}${sameDay ? ' · ⚡ isti dan dolaze novi gosti' : ''}`);
        }
      }
      if (first && added) msgs.push(`📅 ${a.name}: uvezeno ${added} čišćenja iz kalendara`);
      this.sql.exec('UPDATE apts SET sync_at = ?, sync_err = ? WHERE id = ?', Date.now(), '', a.id);
      result.push({ apt: a.id, added, bookings: merged.length });
    }
    if (msgs.length) await this.notify(msgs.join('\n'));
    return result;
  }

  // ---- calendar feeds ----
  calendarToken(renew) {
    let t = this.get('cal_token', '');
    if (!t || renew) { t = newToken(); this.put('cal_token', t); }
    return t;
  }
  feed(kind, token) {
    let rows, title;
    const from = addDays(zagrebDay(), -60);
    if (kind === 'admin') {
      const t = this.get('cal_token', '');
      if (!t || !sameString(token, t)) return null;
      rows = this.jobRows(`j.status != 'cancelled' AND j.date >= ?`, from);
      title = this.get('company', {}).name || 'Čišćenje';
    } else {
      const c = this.sql.exec('SELECT * FROM cleaners WHERE token = ? AND active = 1', token).toArray()[0];
      if (!c) return null;
      rows = this.jobRows(`j.status != 'cancelled' AND j.date >= ? AND j.cleaner_id = ?`, from, c.id);
      title = 'Čišćenje – ' + c.name;
    }
    const apts = Object.fromEntries(this.sql.exec('SELECT id, name, address, checkout, checkin FROM apts').toArray().map(a => [a.id, a]));
    const cleaners = Object.fromEntries(this.sql.exec('SELECT id, name FROM cleaners').toArray().map(c => [c.id, c.name]));
    return { title, jobs: rows.map(j => ({ ...j, apt: apts[j.apt_id] || {}, cleaner: cleaners[j.cleaner_id] || '' })), admin: kind === 'admin' };
  }

  // ---- cleaners ----
  cleanerByToken(token, ip) {
    if (this.count('bad:' + ip, Date.now() - HOUR) >= 30) return { error: 'too_many', status: 429 };
    const c = this.sql.exec('SELECT * FROM cleaners WHERE token = ? AND active = 1', token).toArray()[0];
    if (!c) { this.hit('bad:' + ip); return { error: 'not_found', status: 404 }; }
    return { c };
  }
  cleanerView(token, ip) {
    const { c, ...err } = this.cleanerByToken(token, ip);
    if (!c) return err;
    const t = zagrebDay();
    const apts = Object.fromEntries(this.sql.exec('SELECT * FROM apts').toArray().map(a => [a.id, a]));
    const rows = this.jobRows(`j.date BETWEEN ? AND ? AND (j.cleaner_id = ? AND j.status != 'cancelled' OR j.cleaner_id IS NULL AND j.status = 'planned')`,
      addDays(t, -1), addDays(t, CLEANER_DAYS_AHEAD), c.id);
    // late jobs that are still not done
    const late = this.jobRows(`j.date < ? AND j.date >= ? AND j.cleaner_id = ? AND j.status = 'planned'`, addDays(t, -1), addDays(t, -30), c.id);
    const jobs = [...late, ...rows].map(j => {
      const a = apts[j.apt_id] || {};
      const mine = j.cleaner_id === c.id;
      // no prices or clients for cleaners; entry codes only for their own jobs
      return {
        id: j.id, date: j.date, time: j.time, type: j.type, status: j.status, guests: j.guests, note: j.note, next_in: j.next_in,
        started: j.started, finished: j.finished, checks: j.checks, report: j.report, problem: j.problem, mine,
        apt: { name: a.name, address: a.address, map: a.map, checkout: a.checkout, checkin: a.checkin, minutes: a.minutes,
          checklist: JSON.parse(a.checklist || '[]'), ...(mine ? { access: a.access, info: a.info } : {}) },
      };
    });
    const month = t.slice(0, 7);
    const done = this.sql.exec(`SELECT COUNT(*) AS n, SUM(CASE WHEN started AND finished > started THEN finished - started ELSE 0 END) AS ms
      FROM jobs WHERE status = 'done' AND done_by = ? AND substr(date, 1, 7) = ?`, c.id, month).one();
    return { cleaner: { name: c.name }, today: t, jobs, month: { n: done.n, minutes: Math.round((done.ms || 0) / MINUTE) },
      company: this.get('company', { name: '', phone: '' }), undo_hours: UNDO_HOURS };
  }
  async cleanerAction(token, id, action, data, ip) {
    const { c, ...err } = this.cleanerByToken(token, ip);
    if (!c) return err;
    if (this.count('act:' + c.id, Date.now() - HOUR) >= 300) return { error: 'too_many', status: 429 };
    this.hit('act:' + c.id);
    const j = this.sql.exec('SELECT * FROM jobs WHERE id = ?', id).toArray()[0];
    if (!j || j.status === 'cancelled') return { error: 'not_found', status: 404 };
    const apt = this.sql.exec('SELECT * FROM apts WHERE id = ?', j.apt_id).toArray()[0] || { name: '?' };
    const t = zagrebDay();
    if (action === 'take') {
      if (j.cleaner_id || j.status !== 'planned' || j.date > addDays(t, CLEANER_DAYS_AHEAD)) return { error: 'taken', status: 409 };
      this.sql.exec('UPDATE jobs SET cleaner_id = ? WHERE id = ? AND cleaner_id IS NULL', c.id, id);
      await this.notify(`🙋 ${c.name} preuzima čišćenje: ${apt.name} · ${hrDay(j.date)}`);
      return { ok: true };
    }
    if (j.cleaner_id !== c.id) return { error: 'not_yours', status: 403 };
    if (action === 'start') {
      if (j.status !== 'planned') return { error: 'done', status: 409 };
      this.sql.exec('UPDATE jobs SET started = COALESCE(started, ?) WHERE id = ?', Date.now(), id);
      return { ok: true };
    }
    if (action === 'checks') {
      if (j.status !== 'planned') return { error: 'done', status: 409 };
      const list = JSON.parse(apt.checklist || '[]');
      const checks = Array.isArray(data?.checks) ? [...new Set(data.checks.map(x => line(x, 200)))].filter(x => list.includes(x)) : [];
      this.sql.exec('UPDATE jobs SET checks = ?, started = COALESCE(started, ?) WHERE id = ?', JSON.stringify(checks), Date.now(), id);
      return { ok: true };
    }
    if (action === 'finish') {
      if (j.status !== 'planned') return { error: 'done', status: 409 };
      const report = str(data?.report, 2000), problem = str(data?.problem, 2000), now = Date.now();
      this.sql.exec(`UPDATE jobs SET status = 'done', finished = ?, started = COALESCE(started, ?), done_by = ?, report = ?, problem = ? WHERE id = ?`,
        now, now, c.id, report, problem, id);
      const started = j.started || now;
      const mins = Math.round((now - started) / MINUTE);
      await this.notify(`${problem ? '⚠️' : '✅'} Očišćeno: ${apt.name} · ${hrDay(j.date)}\n${c.name}, gotovo u ${zagrebTime(now)}` +
        `${j.started ? ` (${Math.floor(mins / 60)} h ${mins % 60} min)` : ''}` +
        `${problem ? `\n⚠️ Problem: ${problem}` : ''}${report ? `\n📝 ${report}` : ''}`);
      return { ok: true };
    }
    if (action === 'undo') {
      if (j.status !== 'done' || j.done_by !== c.id || Date.now() - j.finished > UNDO_HOURS * HOUR || j.paid) return { error: 'too_late', status: 409 };
      this.sql.exec(`UPDATE jobs SET status = 'planned', finished = NULL, done_by = NULL WHERE id = ?`, id);
      await this.notify(`↩️ ${c.name}: poništeno „gotovo" – ${apt.name} · ${hrDay(j.date)}`);
      return { ok: true };
    }
    return { error: 'invalid', status: 400 };
  }
}

// ---- Telegram (optional, TELEGRAM_BOT_TOKEN) ----
async function telegram(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}),
  });
  return r.json().catch(() => ({}));
}

// ---- iCalendar feed of the cleanings ----
const icsText = s => String(s || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
function icsFold(l) {
  const out = [];
  let cur = '', size = 0;
  for (const ch of l) {
    const n = new TextEncoder().encode(ch).length;
    if (size + n > 73) { out.push(cur); cur = ' '; size = 1; }
    cur += ch; size += n;
  }
  out.push(cur);
  return out.join('\r\n');
}
function feedIcs(feed, link) {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '');
  const d = day => day.replace(/-/g, '');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ciscenje//cleaning//HR', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
    `X-WR-CALNAME:${icsText(feed.title)}`, 'X-WR-TIMEZONE:Europe/Zagreb', 'REFRESH-INTERVAL;VALUE=DURATION:PT1H'];
  for (const j of feed.jobs) {
    const a = j.apt;
    const window = [a.checkout && `odjava gostiju ${a.checkout}`, j.next_in === j.date ? `⚡ isti dan dolaze novi gosti${a.checkin ? ' u ' + a.checkin : ''}`
      : j.next_in ? `sljedeći dolazak ${hrDay(j.next_in)}` : ''].filter(Boolean).join(' · ');
    const desc = [TYPE_NAMES[j.type], window, j.guests ? `Pripremiti za ${j.guests} osoba` : '', a.address,
      feed.admin && (j.cleaner ? `Čistačica: ${j.cleaner}` : 'Nitko nije preuzeo'), j.note, j.status === 'done' ? '✓ Očišćeno' : '', link].filter(Boolean).join('\n');
    const start = j.time ? `DTSTART;TZID=Europe/Zagreb:${d(j.date)}T${j.time.replace(':', '')}00` : `DTSTART;VALUE=DATE:${d(j.date)}`;
    const end = j.time ? `DURATION:PT${Math.max(30, a.minutes || 120)}M` : `DTEND;VALUE=DATE:${d(addDays(j.date, 1))}`;
    lines.push('BEGIN:VEVENT', `UID:job-${j.id}@ciscenje`, `DTSTAMP:${stamp}`, start, end,
      `SUMMARY:${icsText(`${j.status === 'done' ? '✓' : '🧹'} ${a.name || 'Apartman'}${j.next_in === j.date ? ' ⚡' : ''}`)}`,
      `DESCRIPTION:${icsText(desc)}`, ...(a.address ? [`LOCATION:${icsText(a.address)}`] : []), 'TRANSP:TRANSPARENT', 'END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  return lines.map(icsFold).join('\r\n') + '\r\n';
}

// ---- HTTP ----
const API_HEADERS = { 'Content-Type': 'application/json;charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' };
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: API_HEADERS });
const page = html => new Response(html, {
  headers: {
    'Content-Type': 'text/html;charset=utf-8', 'Cache-Control': 'no-store',
    // the link itself is the key, so it must never leak to other sites
    'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow', 'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
  },
});
const ics = text => new Response(text, { headers: { 'Content-Type': 'text/calendar;charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } });
async function body(request) {
  try { return await request.json(); } catch { return null; }
}
const storeOf = env => env.STORE.get(env.STORE.idFromName('ciscenje'));

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    const ip = request.headers.get('CF-Connecting-IP') || 'local';

    if (path === '/favicon.ico') return new Response(null, { status: 204 });
    if (path === '/robots.txt') return new Response('User-agent: *\nDisallow: /\n', { headers: { 'Content-Type': 'text/plain' } });
    if (path === '/' || path === '/index.html') return page(HOME_PAGE);
    if ((path === '/admin' || path === '/admin/') && method === 'GET') return page(ADMIN_PAGE);
    if (/^\/r\/[\w-]{10,40}\/?$/.test(path) && method === 'GET') return page(CLEANER_PAGE);

    // Everything below needs the database (Durable Object binding STORE from wrangler.toml)
    if (!env.STORE) {
      console.error('Durable Object binding STORE is missing – deploy with wrangler.toml');
      return json({ error: 'no_store' }, 503);
    }
    const store = storeOf(env);

    // calendar feeds (secret links)
    let m = path.match(/^\/cal\/([\w-]{10,40})\.ics$/);
    if (m && method === 'GET') {
      const feed = await store.feed('admin', m[1]);
      return feed ? ics(feedIcs(feed, url.origin + '/admin')) : new Response('Not found', { status: 404 });
    }
    m = path.match(/^\/r\/([\w-]{10,40})\.ics$/);
    if (m && method === 'GET') {
      const feed = await store.feed('cleaner', m[1]);
      return feed ? ics(feedIcs(feed, `${url.origin}/r/${m[1]}`)) : new Response('Not found', { status: 404 });
    }

    // ---- cleaners ----
    m = path.match(/^\/api\/r\/([\w-]{10,40})$/);
    if (m && method === 'GET') {
      const res = await store.cleanerView(m[1], ip);
      return json(res, res.status || 200);
    }
    m = path.match(/^\/api\/r\/([\w-]{10,40})\/jobs\/(\d+)\/(take|start|checks|finish|undo)$/);
    if (m && method === 'POST') {
      const res = await store.cleanerAction(m[1], +m[2], m[3], await body(request), ip);
      return json(res, res.status || 200);
    }

    // ---- owner ----
    if (path.startsWith('/api/admin/')) {
      if (!env.ADMIN_PIN) return json({ error: 'no_pin' }, 503);
      if (await store.adminBlocked(ip)) return json({ error: 'too_many' }, 429);
      if (!sameString(request.headers.get('X-Admin-Pin') || '', env.ADMIN_PIN)) {
        await store.adminFailed(ip);
        return json({ error: 'pin' }, 401);
      }
      const route = path.slice('/api/admin/'.length);
      const b = method === 'POST' ? await body(request) : null;
      const out = r => json(r, r?.error ? (r.error === 'not_found' ? 404 : 400) : 200);

      if (route === 'data' && method === 'GET') return json({ ...(await store.adminData()), tg_token: !!env.TELEGRAM_BOT_TOKEN });
      if (route === 'company' && method === 'POST') return out(await store.saveCompany(b));
      if (route === 'sync' && method === 'POST') return out({ result: await store.sync(idOrNull(b?.apt_id)) });
      if (route === 'calendar' && method === 'POST') return out({ token: await store.calendarToken(!!b?.renew) });
      if (route === 'paid' && method === 'POST') {
        const ids = Array.isArray(b?.ids) ? b.ids.map(idOrNull).filter(Boolean).slice(0, 2000) : [];
        return out(await store.setPaid(ids, !!b?.on));
      }

      // Telegram: everyone who has written to the bot is connected and gets a test message
      if (route === 'telegram' && method === 'POST') {
        if (!env.TELEGRAM_BOT_TOKEN) return json({ error: 'no_token' }, 400);
        const up = await telegram(env, 'getUpdates', {}).catch(() => ({}));
        if (!up.ok) return json({ error: 'bad_token' }, 400);
        const chats = await store.telegramChats();
        for (const u of up.result || []) {
          const c = (u.message || u.my_chat_member || {}).chat;
          if (c && !chats.some(x => x.id === c.id)) chats.push({ id: c.id, name: line(c.first_name || c.title || c.username || '', 60) });
        }
        await store.saveTelegramChats(chats);
        await Promise.all(chats.map(c => telegram(env, 'sendMessage', { chat_id: c.id, text: '✅ Obavijesti o čišćenju su uključene.' })));
        return json({ chats });
      }
      if (route === 'telegram' && method === 'DELETE') return json({ chats: await store.saveTelegramChats([]) });

      if (route === 'clients' && method === 'POST') {
        const c = validClient(b);
        return c.name ? out(await store.saveClient(c)) : json({ error: 'invalid' }, 400);
      }
      if (route === 'apts' && method === 'POST') {
        const a = validApt(b);
        return a.name ? out(await store.saveApt(a)) : json({ error: 'invalid' }, 400);
      }
      if (route === 'cleaners' && method === 'POST') {
        const c = validCleaner(b);
        return c.name ? out(await store.saveCleaner(c)) : json({ error: 'invalid' }, 400);
      }
      m = route.match(/^(clients|apts|cleaners)\/(\d+)\/archive$/);
      if (m && method === 'POST') return out(await store.archive(m[1], +m[2], !!b?.on));
      m = route.match(/^cleaners\/(\d+)\/renew$/);
      if (m && method === 'POST') return out(await store.renewCleaner(+m[1]));
      m = route.match(/^apts\/(\d+)\/sync$/);
      if (m && method === 'POST') return out({ result: await store.sync(+m[1]) });

      if (route === 'jobs' && method === 'POST') {
        const j = validJob(b);
        return j ? out(await store.saveJob(j)) : json({ error: 'invalid' }, 400);
      }
      m = route.match(/^jobs\/(\d+)(?:\/(cancel|restore|reopen|done))?$/);
      if (m && m[2] && method === 'POST') return out(await store.jobAction(+m[1], m[2]));
      if (m && !m[2] && method === 'DELETE') return out(await store.jobAction(+m[1], 'delete'));
      return json({ error: 'not_found' }, 404);
    }

    return json({ error: 'not_found' }, 404);
  },

  // every 30 minutes: read the Booking.com / Airbnb calendars
  async scheduled(event, env, ctx) {
    if (env.STORE) ctx.waitUntil(storeOf(env).sync());
  },
};
