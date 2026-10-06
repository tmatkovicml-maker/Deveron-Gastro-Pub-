// Guest app for the apartments: information about the apartment, the town, the island,
// beaches and restaurants, plus the guest registration form for eVisitor.
//
// There is no public page. The host creates a stay in /admin and sends the guest its link
// (/g/<token>); only someone with that link sees the page and can register.
//
// Guests (token from the link):
//   GET  /api/g/:token                 apartment, content and registration state
//   POST /api/g/:token/guests          {guests: [...], arrival_time}  registration (can be corrected until the host locks it)
// Host (X-Admin-Pin = ADMIN_PIN):
//   GET  /api/admin/data               apartments, content, host details and all stays
//   POST /api/admin/apartments         [{id, name, address, map, wifi_ssid, wifi_pass, checkin, checkout, phone, items}]
//   POST /api/admin/content            {sections: [{id, icon, title, items}]}
//   POST /api/admin/host               {name, phone, email}
//   POST /api/admin/stays              {apt, surname, arrival, departure, expected, lang, note} → {id, token}
//   POST /api/admin/stays/:id          same fields, edit a stay
//   POST /api/admin/stays/:id/entered  {on}  entered in eVisitor (locks the guest form)
//   POST /api/admin/stays/:id/wipe     delete the passport data now
//   DELETE /api/admin/stays/:id        delete the stay completely
// Pages: /g/:token  guest page · /admin  host page
//
// Privacy: passport data is kept 7 days after the guest sends it, then removed by a
// Durable Object alarm. What remains is the surname(s), the dates of the stay, the apartment
// and the number of guests. Everything is stored in one Durable Object (SQLite).
import { DurableObject } from 'cloudflare:workers';
import GUEST_PAGE from './guest.html';
import ADMIN_PAGE from './admin.html';
import HOME_PAGE from './home.html';
import { DEFAULT_APARTMENTS, DEFAULT_CONTENT, DEFAULT_HOST } from './content.js';

const MINUTE = 60 * 1000, HOUR = 60 * MINUTE, DAY = 24 * HOUR;
const KEEP_GUEST_DATA = 7 * DAY;
const LINK_DAYS_AFTER = 3;          // the guest link keeps working this many days after departure
const MAX_GUESTS = 12;
const LANGS = ['hr', 'en', 'de', 'it'];
const DOC_TYPES = ['passport', 'id', 'other'];

const zagrebDay = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Europe/Zagreb' });
const addDays = (day, n) => { const d = new Date(day + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const isDay = v => /^\d{4}-\d{2}-\d{2}$/.test(v) && !isNaN(new Date(v + 'T12:00:00Z')) && new Date(v + 'T12:00:00Z').toISOString().slice(0, 10) === v;
const str = (v, max) => String(v ?? '').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, '').trim().slice(0, max);
const line = (v, max) => str(v, max).replace(/\s+/g, ' ');
const safeLink = v => { const s = line(v, 500); return /^(https?:\/\/|tel:|mailto:|geo:)/i.test(s) ? s : ''; };

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
function multi(v, max) {
  const o = {};
  if (v && typeof v === 'object') for (const l of LANGS) { const s = str(v[l], max); if (s) o[l] = s; }
  return o;
}
function validItems(list) {
  if (!Array.isArray(list)) return [];
  return list.slice(0, 40).map(i => ({
    title: multi(i?.title, 120), text: multi(i?.text, 3000), link: safeLink(i?.link), img: safeLink(i?.img),
  })).filter(i => Object.keys(i.title).length || Object.keys(i.text).length);
}
function validApartments(list) {
  if (!Array.isArray(list) || !list.length || list.length > 30) return null;
  const ids = new Set();
  const out = list.map(a => {
    let id = line(a?.id, 20).replace(/[^a-z0-9_-]/gi, '');
    if (!id || ids.has(id)) id = 'a' + crypto.randomUUID().slice(0, 8);
    ids.add(id);
    return {
      id, name: line(a?.name, 80), address: line(a?.address, 160), map: safeLink(a?.map),
      wifi_ssid: line(a?.wifi_ssid, 64), wifi_pass: line(a?.wifi_pass, 64),
      checkin: line(a?.checkin, 40), checkout: line(a?.checkout, 40), phone: line(a?.phone, 30),
      items: validItems(a?.items),
    };
  });
  return out.every(a => a.name) ? out : null;
}
function validContent(c) {
  if (!c || !Array.isArray(c.sections) || c.sections.length > 20) return null;
  return {
    sections: c.sections.map((s, n) => ({
      id: line(s?.id, 20).replace(/[^a-z0-9_-]/gi, '') || 's' + n,
      icon: line(s?.icon, 8), title: multi(s?.title, 60), items: validItems(s?.items),
    })).filter(s => Object.keys(s.title).length),
  };
}
function validHost(h) {
  return { name: line(h?.name, 100), phone: line(h?.phone, 30), email: line(h?.email, 100) };
}
function validStay(s, apartments) {
  const st = {
    apt: line(s?.apt, 20), surname: line(s?.surname, 60), arrival: line(s?.arrival, 10), departure: line(s?.departure, 10),
    expected: Math.max(1, Math.min(MAX_GUESTS, parseInt(s?.expected, 10) || 1)),
    lang: LANGS.includes(s?.lang) ? s.lang : 'en', note: str(s?.note, 300),
  };
  if (!apartments.some(a => a.id === st.apt)) return null;
  if (!isDay(st.arrival) || !isDay(st.departure) || st.departure < st.arrival) return null;
  return st;
}
const today = () => new Date().toISOString().slice(0, 10);
function validGuest(g) {
  const v = {
    first: line(g?.first, 60), last: line(g?.last, 60), sex: g?.sex === 'M' || g?.sex === 'F' ? g.sex : '',
    dob: line(g?.dob, 10), birth_country: line(g?.birth_country, 2).toUpperCase(), birth_city: line(g?.birth_city, 60),
    citizenship: line(g?.citizenship, 2).toUpperCase(), res_country: line(g?.res_country, 2).toUpperCase(),
    res_city: line(g?.res_city, 60), doc_type: DOC_TYPES.includes(g?.doc_type) ? g.doc_type : '',
    doc_number: line(g?.doc_number, 20).toUpperCase(),
  };
  const cc = /^[A-Z]{2}$/;
  if (!v.first || !v.last || !v.sex || !v.doc_type || !v.res_city) return null;
  if (!isDay(v.dob) || v.dob < '1900-01-01' || v.dob > today()) return null;
  if (!cc.test(v.birth_country) || !cc.test(v.citizenship) || !cc.test(v.res_country)) return null;
  if (!/^[A-Z0-9][A-Z0-9 -]{2,19}$/.test(v.doc_number)) return null;
  return v;
}

export class Store extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS limits (k TEXT NOT NULL, at INTEGER NOT NULL)`);
    // guests holds the passport data (JSON) until it is wiped; surnames and n_guests stay
    this.sql.exec(`CREATE TABLE IF NOT EXISTS stays (
      id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE, created INTEGER NOT NULL,
      apt TEXT NOT NULL, surname TEXT NOT NULL DEFAULT '', arrival TEXT NOT NULL, departure TEXT NOT NULL,
      expected INTEGER NOT NULL DEFAULT 1, lang TEXT NOT NULL DEFAULT 'en', note TEXT NOT NULL DEFAULT '',
      guests TEXT, surnames TEXT NOT NULL DEFAULT '', n_guests INTEGER NOT NULL DEFAULT 0, arrival_time TEXT NOT NULL DEFAULT '',
      submitted INTEGER, entered INTEGER, wiped INTEGER)`);
    this.sql.exec('CREATE INDEX IF NOT EXISTS stays_arrival ON stays (arrival)');
  }

  // ---- settings ----
  get(k, fallback) {
    const r = this.sql.exec('SELECT v FROM settings WHERE k = ?', k).toArray()[0];
    return r ? JSON.parse(r.v) : fallback;
  }
  put(k, v) {
    this.sql.exec('INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v', k, JSON.stringify(v));
  }
  apartments() { return this.get('apartments', DEFAULT_APARTMENTS); }

  // ---- rate limits ----
  count(k, since) {
    return this.sql.exec('SELECT COUNT(*) AS n FROM limits WHERE k = ? AND at > ?', k, since).one().n;
  }
  hit(k) { this.sql.exec('INSERT INTO limits (k, at) VALUES (?, ?)', k, Date.now()); }

  // ---- privacy: remove passport data 7 days after it was sent ----
  async cleanup() {
    const now = Date.now();
    this.sql.exec('DELETE FROM limits WHERE at < ?', now - DAY);
    this.sql.exec('UPDATE stays SET guests = NULL, wiped = ? WHERE guests IS NOT NULL AND submitted < ?', now, now - KEEP_GUEST_DATA);
    const next = this.sql.exec('SELECT MIN(submitted) AS t FROM stays WHERE guests IS NOT NULL').one().t;
    if (next) await this.ctx.storage.setAlarm(next + KEEP_GUEST_DATA + MINUTE);
    else await this.ctx.storage.deleteAlarm();
  }
  async alarm() { await this.cleanup(); }

  stayByToken(token) {
    const s = this.sql.exec('SELECT * FROM stays WHERE token = ?', token).toArray()[0];
    if (!s || addDays(s.departure, LINK_DAYS_AFTER) < zagrebDay()) return null;
    return s;
  }

  // ---- guests ----
  async guestView(token, ip) {
    await this.cleanup();
    if (this.count('bad:' + ip, Date.now() - HOUR) >= 30) return { error: 'too_many', status: 429 };
    const s = this.stayByToken(token);
    if (!s) { this.hit('bad:' + ip); return { error: 'not_found', status: 404 }; }
    const apt = this.apartments().find(a => a.id === s.apt) || this.apartments()[0];
    const names = s.guests ? JSON.parse(s.guests).map(g => `${g.first} ${g.last}`) : [];
    return {
      stay: {
        arrival: s.arrival, departure: s.departure, expected: s.expected, lang: s.lang,
        arrival_time: s.arrival_time, sent: !!s.submitted, names, n_guests: s.n_guests,
        locked: !!(s.entered || s.wiped),
      },
      apartment: apt, content: this.get('content', DEFAULT_CONTENT), host: this.get('host', DEFAULT_HOST),
      keep_days: KEEP_GUEST_DATA / DAY,
    };
  }

  async submitGuests(token, guests, arrivalTime, ip) {
    await this.cleanup();
    if (this.count('bad:' + ip, Date.now() - HOUR) >= 30) return { error: 'too_many', status: 429 };
    const s = this.stayByToken(token);
    if (!s) { this.hit('bad:' + ip); return { error: 'not_found', status: 404 }; }
    if (s.entered || s.wiped) return { error: 'locked', status: 409 };
    if (this.count('sub:' + s.id, Date.now() - DAY) >= 20) return { error: 'too_many', status: 429 };
    this.hit('sub:' + s.id);
    const surnames = [...new Set(guests.map(g => g.last))].join(', ');
    this.sql.exec('UPDATE stays SET guests = ?, surnames = ?, n_guests = ?, arrival_time = ?, submitted = ? WHERE id = ?',
      JSON.stringify(guests), surnames, guests.length, arrivalTime, Date.now(), s.id);
    await this.cleanup();
    return { ok: true };
  }

  // ---- host ----
  adminBlocked(ip) { return this.count('pin:' + ip, Date.now() - 15 * MINUTE) >= 10; }
  adminFailed(ip) { this.hit('pin:' + ip); }

  async adminData() {
    await this.cleanup();
    const stays = this.sql.exec('SELECT * FROM stays ORDER BY arrival DESC, id DESC').toArray()
      .map(s => ({ ...s, guests: s.guests ? JSON.parse(s.guests) : null, wipe_at: s.guests ? s.submitted + KEEP_GUEST_DATA : null }));
    return {
      apartments: this.apartments(), content: this.get('content', DEFAULT_CONTENT), host: this.get('host', DEFAULT_HOST),
      stays, keep_days: KEEP_GUEST_DATA / DAY, link_days_after: LINK_DAYS_AFTER,
    };
  }
  saveApartments(list) { this.put('apartments', list); return { ok: true }; }
  saveContent(c) { this.put('content', c); return { ok: true }; }
  saveHost(h) { this.put('host', h); return { ok: true }; }

  createStay(st) {
    const token = newToken();
    const row = this.sql.exec(`INSERT INTO stays (token, created, apt, surname, arrival, departure, expected, lang, note)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`,
      token, Date.now(), st.apt, st.surname, st.arrival, st.departure, st.expected, st.lang, st.note).one();
    return { id: row.id, token };
  }
  updateStay(id, st) {
    this.sql.exec('UPDATE stays SET apt = ?, surname = ?, arrival = ?, departure = ?, expected = ?, lang = ?, note = ? WHERE id = ?',
      st.apt, st.surname, st.arrival, st.departure, st.expected, st.lang, st.note, id);
    return { ok: true };
  }
  markEntered(id, on) {
    this.sql.exec('UPDATE stays SET entered = ? WHERE id = ?', on ? Date.now() : null, id);
    return { ok: true };
  }
  async wipeStay(id) {
    this.sql.exec('UPDATE stays SET guests = NULL, wiped = ? WHERE id = ? AND guests IS NOT NULL', Date.now(), id);
    await this.cleanup();
    return { ok: true };
  }
  async deleteStay(id) {
    this.sql.exec('DELETE FROM stays WHERE id = ?', id);
    await this.cleanup();
    return { ok: true };
  }
}

// ---- HTTP ----
const API_HEADERS = { 'Content-Type': 'application/json;charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' };
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: API_HEADERS });
const page = html => new Response(html, {
  headers: {
    'Content-Type': 'text/html;charset=utf-8',
    'Cache-Control': 'no-store',
    // the link itself is the key, so it must never leak to other sites
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex, nofollow',
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
  },
});
async function body(request) {
  try { return await request.json(); } catch { return null; }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    const store = env.STORE.get(env.STORE.idFromName('apartmani'));
    const ip = request.headers.get('CF-Connecting-IP') || 'local';

    if (path === '/robots.txt') return new Response('User-agent: *\nDisallow: /\n', { headers: { 'Content-Type': 'text/plain' } });
    if (path === '/' || path === '/index.html') return page(HOME_PAGE);
    if (/^\/g\/[\w-]{10,40}\/?$/.test(path) && method === 'GET') return page(GUEST_PAGE);
    if ((path === '/admin' || path === '/admin/') && method === 'GET') return page(ADMIN_PAGE);

    // ---- guests ----
    let m = path.match(/^\/api\/g\/([\w-]{10,40})$/);
    if (m && method === 'GET') {
      const res = await store.guestView(m[1], ip);
      return json(res, res.status || 200);
    }
    m = path.match(/^\/api\/g\/([\w-]{10,40})\/guests$/);
    if (m && method === 'POST') {
      const b = await body(request);
      if (!b || !Array.isArray(b.guests) || !b.guests.length || b.guests.length > MAX_GUESTS) return json({ error: 'invalid' }, 400);
      const guests = b.guests.map(validGuest);
      if (guests.some(g => !g)) return json({ error: 'invalid' }, 400);
      const at = /^\d{2}:\d{2}$/.test(b.arrival_time) ? b.arrival_time : '';
      const res = await store.submitGuests(m[1], guests, at, ip);
      return json(res, res.status || 200);
    }

    // ---- host ----
    if (path.startsWith('/api/admin/')) {
      if (!env.ADMIN_PIN) return json({ error: 'no_pin' }, 503);
      if (await store.adminBlocked(ip)) return json({ error: 'too_many' }, 429);
      if (!sameString(request.headers.get('X-Admin-Pin') || '', env.ADMIN_PIN)) {
        await store.adminFailed(ip);
        return json({ error: 'pin' }, 401);
      }
      const route = path.slice('/api/admin/'.length);

      if (route === 'data' && method === 'GET') return json(await store.adminData());

      if (route === 'apartments' && method === 'POST') {
        const list = validApartments(await body(request));
        return list ? json(await store.saveApartments(list)) : json({ error: 'invalid' }, 400);
      }
      if (route === 'content' && method === 'POST') {
        const c = validContent(await body(request));
        return c ? json(await store.saveContent(c)) : json({ error: 'invalid' }, 400);
      }
      if (route === 'host' && method === 'POST') return json(await store.saveHost(validHost(await body(request))));

      if (route === 'stays' && method === 'POST') {
        const st = validStay(await body(request), await store.apartments());
        return st ? json(await store.createStay(st)) : json({ error: 'invalid' }, 400);
      }
      m = route.match(/^stays\/(\d+)(?:\/(entered|wipe))?$/);
      if (m) {
        const id = +m[1];
        if (!m[2] && method === 'POST') {
          const st = validStay(await body(request), await store.apartments());
          return st ? json(await store.updateStay(id, st)) : json({ error: 'invalid' }, 400);
        }
        if (!m[2] && method === 'DELETE') return json(await store.deleteStay(id));
        if (m[2] === 'entered' && method === 'POST') return json(await store.markEntered(id, !!(await body(request))?.on));
        if (m[2] === 'wipe' && method === 'POST') return json(await store.wipeStay(id));
      }
      return json({ error: 'not_found' }, 404);
    }

    return json({ error: 'not_found' }, 404);
  },
};
