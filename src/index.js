// Shift sign-up for the Advent hut in Mali Lošinj (10.12.2026–02.01.2027).
// Adult students pick their shifts without an account; a shift closes as soon as it is full.
//
// Public (no account):
//   GET  /api/stanje                     shifts with free places, whether sign-up is open, terms (no names, no phones)
//   POST /api/prijava                    {name, phone, slots: [id], adult, consent, website}  → {token, regs}
//   GET  /api/moji/:token                the shifts booked with this private link
//   POST /api/moji/:token/otkazi         {id}  cancel one shift (until the cancellation deadline)
//   GET  /qr.svg, /qr.png                QR code of the public page for print (PUBLIC_URL or this address)
// Organizer (X-Admin-Password = ADMIN_PASSWORD):
//   GET  /api/admin/data                 shifts, all sign-ups with names and phones, settings
//   GET  /api/admin/export.csv           all sign-ups for Excel
//   POST /api/admin/settings             {open, cancel_hours, manual, terms, organizer, wipe_on}
//   POST /api/admin/slots/:id            {capacity}
//   POST /api/admin/import               {csv}  replace the shifts with the organizer's CSV
//   POST /api/admin/regs                 {slot, name, phone, force}  add a sign-up by hand
//   POST /api/admin/regs/:id/confirm     confirm a sign-up (when sign-ups are confirmed by hand)
//   DELETE /api/admin/regs/:id           remove a sign-up
//   POST /api/admin/wipe                 {confirm: "OBRIŠI"}  delete all names and phones now
// Pages: /  sign-up · /moji/:token  my shifts · /admin  organizer
//
// Everything is in one Durable Object (SQLite). A Durable Object runs one request at a time and
// signUp() does its checks and writes in one synchronous transaction, so two people can never
// take the same last place, and nobody can go over 30 hours a week or take two blocks on one day.
import { DurableObject } from 'cloudflare:workers';
import PUBLIC_PAGE from './public.html';
import ADMIN_PAGE from './admin.html';
import { qrSvg, qrPng } from './qr.js';
import {
  MAX_WEEK_HOURS, normalizePhone, formatPhone, isoWeek, isDay, checkChoice, weekHours,
  defaultSlots, parseSlotsCsv, slotStartMs,
} from './rules.js';

const MINUTE = 60 * 1000, HOUR = 60 * MINUTE, DAY = 24 * HOUR;
const DEFAULTS = {
  open: true,             // sign-up open
  cancel_hours: 48,       // a student can cancel until this many hours before the shift starts
  manual: false,          // false: a sign-up counts at once; true: the organizer confirms each one (it holds the place meanwhile)
  terms: '',              // pay and conditions, shown on the page only when filled in
  organizer: '',          // who collects the data (privacy notice)
  wipe_on: '2027-01-31',  // names and phones are deleted automatically on this day
};
const LIMITS = { signup: [15, 10 * MINUTE], cancel: [30, 10 * MINUTE], mine: [120, 10 * MINUTE], admin_fail: [10, 15 * MINUTE] };

const str = (v, max) => String(v ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
const text = (v, max) => String(v ?? '').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, '').trim().slice(0, max);
const validName = v => { const s = str(v, 80); return /^[\p{L}][\p{L}'’.\- ]*\s[\p{L}][\p{L}'’.\- ]*$/u.test(s) ? s : null; };

function newToken() {
  const b = crypto.getRandomValues(new Uint8Array(18));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export class Store extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS limits (k TEXT NOT NULL, at INTEGER NOT NULL)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS slots (id TEXT PRIMARY KEY, day TEXT NOT NULL, block TEXT NOT NULL,
      start TEXT NOT NULL, "end" TEXT NOT NULL, hours REAL NOT NULL, capacity INTEGER NOT NULL)`);
    // one row per person per shift; token = the private link of the sign-up it was made with
    this.sql.exec(`CREATE TABLE IF NOT EXISTS regs (id INTEGER PRIMARY KEY AUTOINCREMENT, slot_id TEXT NOT NULL,
      phone TEXT NOT NULL, name TEXT NOT NULL, token TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, created INTEGER NOT NULL,
      UNIQUE (slot_id, phone))`);
    this.sql.exec('CREATE INDEX IF NOT EXISTS regs_phone ON regs (phone)');
    this.sql.exec('CREATE INDEX IF NOT EXISTS regs_token ON regs (token)');
    if (this.sql.exec('SELECT COUNT(*) AS n FROM slots').one().n === 0) this.insertSlots(defaultSlots());
  }

  // ---- settings ----
  settings() {
    const out = { ...DEFAULTS };
    for (const r of this.sql.exec('SELECT k, v FROM settings').toArray()) if (r.k in DEFAULTS) out[r.k] = JSON.parse(r.v);
    return out;
  }
  put(k, v) { this.sql.exec('INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v', k, JSON.stringify(v)); }

  // ---- rate limits per IP ----
  limited(kind, ip) {
    const [max, per] = LIMITS[kind], k = `${kind}:${ip}`;
    const n = this.sql.exec('SELECT COUNT(*) AS n FROM limits WHERE k = ? AND at > ?', k, Date.now() - per).one().n;
    return n >= max;
  }
  hit(kind, ip) {
    this.sql.exec('DELETE FROM limits WHERE at < ?', Date.now() - DAY);   // IP addresses are kept one day at most
    this.sql.exec('INSERT INTO limits (k, at) VALUES (?, ?)', `${kind}:${ip}`, Date.now());
  }
  adminBlocked(ip) { return this.limited('admin_fail', ip); }
  adminFailed(ip) { this.hit('admin_fail', ip); }

  // ---- shifts ----
  slots() {
    return this.sql.exec(`SELECT s.id, s.day, s.block, s.start, s."end" AS "end", s.hours, s.capacity,
      (SELECT COUNT(*) FROM regs r WHERE r.slot_id = s.id) AS taken FROM slots s ORDER BY s.day, s.block`).toArray();
  }
  slot(id) {
    return this.sql.exec(`SELECT id, day, block, start, "end" AS "end", hours, capacity FROM slots WHERE id = ?`, id).toArray()[0] || null;
  }
  taken(id) { return this.sql.exec('SELECT COUNT(*) AS n FROM regs WHERE slot_id = ?', id).one().n; }
  insertSlots(list) {
    for (const s of list) {
      this.sql.exec(`INSERT INTO slots (id, day, block, start, "end", hours, capacity) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET day = excluded.day, block = excluded.block, start = excluded.start, "end" = excluded."end",
        hours = excluded.hours, capacity = excluded.capacity`, s.id, s.day, s.block, s.start, s.end, s.hours, s.capacity);
    }
  }
  personShifts(phone) {
    return this.sql.exec('SELECT s.id, s.day, s.hours FROM regs r JOIN slots s ON s.id = r.slot_id WHERE r.phone = ?', phone).toArray();
  }

  // ---- public ----
  publicState() {
    const st = this.settings();
    return {
      open: st.open, cancel_hours: st.cancel_hours, manual: st.manual, terms: st.terms, organizer: st.organizer,
      wipe_on: st.wipe_on, max_week: MAX_WEEK_HOURS, now: Date.now(),
      slots: this.slots().map(s => ({ ...s, free: Math.max(0, s.capacity - s.taken), taken: undefined })),
    };
  }

  // The checks and the writes happen in one synchronous transaction: nothing else runs in between.
  async signUp({ name, phone, slots: ids }, ip) {
    if (this.limited('signup', ip)) return { status: 429, error: 'too_many' };
    this.hit('signup', ip);
    const res = this.ctx.storage.transactionSync(() => {
      const st = this.settings();
      if (!st.open) return { status: 409, error: 'closed' };
      const chosen = ids.map(id => this.slot(id));
      if (chosen.some(s => !s)) return { status: 409, error: 'unknown_slot' };
      const now = Date.now();
      for (const s of chosen) {
        if (slotStartMs(s) <= now) return { status: 409, error: 'past', slot: s.id };
        if (this.taken(s.id) >= s.capacity) return { status: 409, error: 'full', slot: s.id };
      }
      const bad = checkChoice(this.personShifts(phone), chosen);
      if (bad) return { status: 409, ...bad };
      const token = newToken(), status = st.manual ? 'pending' : 'confirmed';
      for (const s of chosen) {
        this.sql.exec(`INSERT INTO regs (slot_id, phone, name, token, status, source, created) VALUES (?, ?, ?, ?, ?, 'web', ?)`,
          s.id, phone, name, token, status, now);
      }
      return { token };
    });
    if (res.error) return { ...res, state: this.publicState() };
    await this.scheduleWipe();
    return { ...this.mine(res.token), token: res.token };
  }

  mine(token) {
    const st = this.settings(), now = Date.now();
    const regs = this.sql.exec(`SELECT r.id, r.name, r.status, s.id AS slot_id, s.day, s.block, s.start, s."end" AS "end", s.hours
      FROM regs r JOIN slots s ON s.id = r.slot_id WHERE r.token = ? ORDER BY s.day, s.block`, token).toArray()
      .map(r => ({ ...r, can_cancel: now < slotStartMs(r) - st.cancel_hours * HOUR }));
    return { regs, name: regs[0]?.name || '', cancel_hours: st.cancel_hours, manual: st.manual };
  }
  mineChecked(token, ip) {
    if (this.limited('mine', ip)) return { status: 429, error: 'too_many' };
    this.hit('mine', ip);
    return this.mine(token);
  }

  cancel(token, id, ip) {
    if (this.limited('cancel', ip)) return { status: 429, error: 'too_many' };
    this.hit('cancel', ip);
    const r = this.sql.exec(`SELECT r.id, s.day, s.start FROM regs r JOIN slots s ON s.id = r.slot_id WHERE r.id = ? AND r.token = ?`, id, token).toArray()[0];
    if (!r) return { status: 404, error: 'not_found' };
    if (Date.now() >= slotStartMs(r) - this.settings().cancel_hours * HOUR) return { status: 409, error: 'too_late' };
    this.sql.exec('DELETE FROM regs WHERE id = ?', id);
    return this.mine(token);
  }

  // ---- organizer ----
  adminData() {
    const regs = this.sql.exec(`SELECT r.id, r.slot_id, r.name, r.phone, r.status, r.source, r.created, r.token, s.day, s.hours
      FROM regs r JOIN slots s ON s.id = r.slot_id ORDER BY s.day, s.block, r.created`).toArray();
    // people: one per phone number, with hours per ISO week and in total
    const people = {};
    for (const r of regs) {
      const p = people[r.phone] ||= { phone: r.phone, phone_fmt: formatPhone(r.phone), name: r.name, shifts: [], total: 0 };
      p.name = r.name;
      p.shifts.push({ id: r.slot_id, day: r.day, hours: r.hours });
      p.total = Math.round((p.total + r.hours) * 10) / 10;
    }
    for (const p of Object.values(people)) {
      p.weeks = weekHours(p.shifts);
      p.over = Object.values(p.weeks).some(h => h > MAX_WEEK_HOURS);
    }
    return {
      settings: this.settings(), max_week: MAX_WEEK_HOURS, slots: this.slots(),
      regs: regs.map(r => ({ ...r, phone_fmt: formatPhone(r.phone), day: undefined, hours: undefined })),
      people: Object.values(people).sort((a, b) => a.name.localeCompare(b.name, 'hr')),
    };
  }

  async saveSettings(v) {
    const cur = this.settings();
    for (const k of Object.keys(DEFAULTS)) if (v[k] !== undefined) this.put(k, v[k]);
    if (v.wipe_on !== undefined && v.wipe_on !== cur.wipe_on) this.put('wiped_for', null);
    await this.scheduleWipe();
    return this.adminData();
  }

  setCapacity(id, capacity) {
    if (!this.slot(id)) return { status: 404, error: 'not_found' };
    this.sql.exec('UPDATE slots SET capacity = ? WHERE id = ?', capacity, id);
    return this.adminData();
  }

  importSlots(list) {
    return this.ctx.storage.transactionSync(() => {
      const ids = new Set(list.map(s => s.id));
      const orphans = this.sql.exec('SELECT DISTINCT slot_id FROM regs').toArray().map(r => r.slot_id).filter(id => !ids.has(id));
      if (orphans.length) return { status: 409, error: 'slots_in_use', slots: orphans };
      for (const r of this.sql.exec('SELECT id FROM slots').toArray()) if (!ids.has(r.id)) this.sql.exec('DELETE FROM slots WHERE id = ?', r.id);
      this.insertSlots(list);
      return this.adminData();
    });
  }

  // force: add even if the shift is full or the person would break a rule (the organizer decides)
  addReg({ slot, name, phone, force }) {
    const res = this.ctx.storage.transactionSync(() => {
      const s = this.slot(slot);
      if (!s) return { status: 404, error: 'unknown_slot' };
      if (this.sql.exec('SELECT 1 FROM regs WHERE slot_id = ? AND phone = ?', slot, phone).toArray().length) return { status: 409, error: 'already' };
      if (!force) {
        if (this.taken(slot) >= s.capacity) return { status: 409, error: 'full', slot };
        const bad = checkChoice(this.personShifts(phone), [s]);
        if (bad) return { status: 409, ...bad };
      }
      // the person's existing private link, so the organizer can send one link for all their shifts
      const prev = this.sql.exec('SELECT token FROM regs WHERE phone = ? ORDER BY created DESC LIMIT 1', phone).toArray()[0];
      this.sql.exec(`INSERT INTO regs (slot_id, phone, name, token, status, source, created) VALUES (?, ?, ?, ?, 'confirmed', 'admin', ?)`,
        slot, phone, name, prev ? prev.token : newToken(), Date.now());
      return null;
    });
    return res || this.adminData();
  }
  removeReg(id) { this.sql.exec('DELETE FROM regs WHERE id = ?', id); return this.adminData(); }
  confirmReg(id) { this.sql.exec(`UPDATE regs SET status = 'confirmed' WHERE id = ?`, id); return this.adminData(); }

  exportRows() {
    return this.sql.exec(`SELECT s.day, s.block, s.start, s."end" AS "end", s.hours, r.name, r.phone, r.status, r.created
      FROM regs r JOIN slots s ON s.id = r.slot_id ORDER BY s.day, s.block, r.name`).toArray();
  }

  // ---- privacy: names and phones are deleted on wipe_on (or now, from /admin) ----
  wipe() {
    this.sql.exec('DELETE FROM regs');
    this.sql.exec('DELETE FROM limits');
    return this.adminData();
  }
  wipeMs() { const d = this.settings().wipe_on; return isDay(d) ? Date.parse(d + 'T00:00:00+01:00') : null; }
  async scheduleWipe() {
    const at = this.wipeMs();
    if (at && this.get('wiped_for') !== this.settings().wipe_on) await this.ctx.storage.setAlarm(Math.max(at, Date.now() + MINUTE));
    else await this.ctx.storage.deleteAlarm();
  }
  get(k) { const r = this.sql.exec('SELECT v FROM settings WHERE k = ?', k).toArray()[0]; return r ? JSON.parse(r.v) : null; }
  async alarm() {
    const at = this.wipeMs();
    if (at && Date.now() >= at) {
      this.wipe();
      this.put('wiped_for', this.settings().wipe_on);
      this.put('open', false);
    } else await this.scheduleWipe();
  }
}

// ---- HTTP ----
const SEC = { 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer' };
const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...SEC },
});
const page = (html, robots) => new Response(html, {
  headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', ...SEC, ...(robots ? { 'X-Robots-Tag': robots } : {}) },
});
async function body(req) { try { return await req.json(); } catch { return null; } }

function sameString(a, b) {
  const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x[i] || 0) ^ (y[i] || 0);
  return d === 0;
}

function validSettings(b) {
  if (!b || typeof b !== 'object') return null;
  const out = {};
  if ('open' in b) out.open = !!b.open;
  if ('manual' in b) out.manual = !!b.manual;
  if ('cancel_hours' in b) { const n = Number(b.cancel_hours); if (!Number.isInteger(n) || n < 0 || n > 24 * 30) return null; out.cancel_hours = n; }
  if ('terms' in b) out.terms = text(b.terms, 2000);
  if ('organizer' in b) out.organizer = text(b.organizer, 400);
  if ('wipe_on' in b) { if (!isDay(b.wipe_on)) return null; out.wipe_on = b.wipe_on; }
  return out;
}

const DAYS_HR = ['ned', 'pon', 'uto', 'sri', 'čet', 'pet', 'sub'];
const hrDate = d => `${+d.slice(8, 10)}.${+d.slice(5, 7)}.${d.slice(0, 4)}.`;
function exportCsv(rows) {
  const q = v => { const s = String(v ?? ''); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const out = [['Datum', 'Dan', 'Tjedan', 'Blok', 'Vrijeme', 'Sati', 'Ime i prezime', 'Mobitel', 'Status', 'Prijavljeno']];
  for (const r of rows) {
    out.push([hrDate(r.day), DAYS_HR[new Date(r.day + 'T12:00:00Z').getUTCDay()], isoWeek(r.day).slice(-2), r.block,
      `${r.start}–${r.end}`, String(r.hours).replace('.', ','), r.name, formatPhone(r.phone),
      r.status === 'pending' ? 'čeka potvrdu' : 'potvrđeno',
      new Date(r.created).toLocaleString('hr-HR', { timeZone: 'Europe/Zagreb' })]);
  }
  // semicolons and a BOM: Excel with Croatian settings opens it with the right columns and letters
  return '﻿' + out.map(r => r.map(q).join(';')).join('\r\n') + '\r\n';
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url), path = url.pathname, method = request.method;
    const store = env.STORE.get(env.STORE.idFromName('main'));
    const ip = request.headers.get('CF-Connecting-IP') || 'local';

    if (method === 'GET' && (path === '/' || path === '/index.html')) return page(PUBLIC_PAGE);
    if (method === 'GET' && /^\/moji\/[\w-]{16,40}$/.test(path)) return page(PUBLIC_PAGE, 'noindex');
    if (method === 'GET' && path === '/admin') return page(ADMIN_PAGE, 'noindex');
    if (method === 'GET' && path === '/robots.txt') return new Response('User-agent: *\nDisallow: /moji/\nDisallow: /admin\nDisallow: /api/\n');

    if (method === 'GET' && (path === '/qr.svg' || path === '/qr.png')) {
      const target = env.PUBLIC_URL || `${url.origin}/`;
      if (path === '/qr.svg') return new Response(qrSvg(target), { headers: { 'Content-Type': 'image/svg+xml', 'Content-Disposition': 'inline; filename="qr-prijave.svg"' } });
      const scale = Math.min(80, Math.max(10, parseInt(url.searchParams.get('scale')) || 40));
      return new Response(await qrPng(target, scale), { headers: { 'Content-Type': 'image/png', 'Content-Disposition': 'inline; filename="qr-prijave.png"' } });
    }

    if (path === '/api/stanje' && method === 'GET') return json(await store.publicState());

    if (path === '/api/prijava' && method === 'POST') {
      const b = await body(request);
      if (!b || typeof b !== 'object') return json({ error: 'invalid' }, 400);
      if (b.website) return json({ error: 'invalid' }, 400);                        // honeypot: people never see this field
      if (b.adult !== true) return json({ error: 'adult' }, 400);
      if (b.consent !== true) return json({ error: 'consent' }, 400);
      const name = validName(b.name);
      if (!name) return json({ error: 'name' }, 400);
      const phone = normalizePhone(b.phone);
      if (!phone) return json({ error: 'phone' }, 400);
      const ids = Array.isArray(b.slots) ? [...new Set(b.slots.map(String))] : [];
      if (!ids.length || ids.length > 40 || ids.some(id => !/^\d{4}-\d{2}-\d{2}-[AB]$/.test(id))) return json({ error: 'no_slots' }, 400);
      const res = await store.signUp({ name, phone, slots: ids }, ip);
      return json(res, res.status || 200);
    }

    let m = path.match(/^\/api\/moji\/([\w-]{16,40})(\/otkazi)?$/);
    if (m && !m[2] && method === 'GET') { const res = await store.mineChecked(m[1], ip); return json(res, res.status || 200); }
    if (m && m[2] && method === 'POST') {
      const id = Number((await body(request))?.id);
      if (!Number.isInteger(id)) return json({ error: 'invalid' }, 400);
      const res = await store.cancel(m[1], id, ip);
      return json(res, res.status || 200);
    }

    if (path.startsWith('/api/admin/')) {
      if (!env.ADMIN_PASSWORD) return json({ error: 'no_password' }, 503);
      if (await store.adminBlocked(ip)) return json({ error: 'too_many' }, 429);
      if (!sameString(request.headers.get('X-Admin-Password') || '', env.ADMIN_PASSWORD)) {
        await store.adminFailed(ip);
        return json({ error: 'password' }, 401);
      }
      const route = path.slice('/api/admin/'.length);
      if (route === 'data' && method === 'GET') return json(await store.adminData());
      if (route === 'export.csv' && method === 'GET') {
        return new Response(exportCsv(await store.exportRows()), { headers: {
          'Content-Type': 'text/csv; charset=utf-8', 'Cache-Control': 'no-store',
          'Content-Disposition': 'attachment; filename="prijave-advent-2026.csv"' } });
      }
      if (route === 'settings' && method === 'POST') {
        const s = validSettings(await body(request));
        return s ? json(await store.saveSettings(s)) : json({ error: 'invalid' }, 400);
      }
      if (route === 'import' && method === 'POST') {
        let list;
        try { list = parseSlotsCsv((await body(request))?.csv || ''); } catch (e) { return json({ error: 'csv', message: e.message }, 400); }
        const res = await store.importSlots(list);
        return json(res, res.status || 200);
      }
      if (route === 'wipe' && method === 'POST') {
        if ((await body(request))?.confirm !== 'OBRIŠI') return json({ error: 'invalid' }, 400);
        return json(await store.wipe());
      }
      if (route === 'regs' && method === 'POST') {
        const b = await body(request) || {};
        const name = validName(b.name), phone = normalizePhone(b.phone);
        if (!name) return json({ error: 'name' }, 400);
        if (!phone) return json({ error: 'phone' }, 400);
        const res = await store.addReg({ slot: String(b.slot || ''), name, phone, force: !!b.force });
        return json(res, res.status || 200);
      }
      m = route.match(/^regs\/(\d+)(\/confirm)?$/);
      if (m && !m[2] && method === 'DELETE') return json(await store.removeReg(+m[1]));
      if (m && m[2] && method === 'POST') return json(await store.confirmReg(+m[1]));
      m = route.match(/^slots\/(\d{4}-\d{2}-\d{2}-[AB])$/);
      if (m && method === 'POST') {
        const cap = Number((await body(request))?.capacity);
        if (!Number.isInteger(cap) || cap < 0 || cap > 50) return json({ error: 'invalid' }, 400);
        const res = await store.setCapacity(m[1], cap);
        return json(res, res.status || 200);
      }
      return json({ error: 'not_found' }, 404);
    }

    return json({ error: 'not_found' }, 404);
  },
};
