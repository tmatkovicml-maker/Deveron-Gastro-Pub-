// Runs the Worker locally (wrangler dev, empty database) and checks it over HTTP, including many sign-ups
// arriving at the same moment for the last places. Run: npm run test:server
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const PORT = 8790 + Math.floor(Math.random() * 100);
const BASE = `http://127.0.0.1:${PORT}`;
const PW = 'test-lozinka';
let proc, dir, ipN = 0;

before(async () => {
  dir = mkdtempSync(join(tmpdir(), 'advent-'));
  proc = spawn('npx', ['wrangler', 'dev', '--port', String(PORT), '--ip', '127.0.0.1', '--persist-to', dir,
    '--var', `ADMIN_PASSWORD:${PW}`, '--show-interactive-dev-session=false'], { stdio: ['ignore', 'pipe', 'pipe'], detached: true, env: { ...process.env, WRANGLER_SEND_METRICS: 'false' } });
  let log = '';
  proc.stdout.on('data', d => log += d); proc.stderr.on('data', d => log += d);
  for (let i = 0; i < 360; i++) {
    try { if ((await fetch(BASE + '/api/stanje')).ok) return; } catch {}
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('wrangler dev did not start:\n' + log);
}, { timeout: 200000 });
after(() => { try { process.kill(-proc.pid, 'SIGTERM'); } catch {} rmSync(dir, { recursive: true, force: true }); });

// every request comes from its own IP unless given one, so the per-IP limit does not get in the way
const call = (path, { body, method, admin, ip } = {}) => fetch(BASE + path, {
  method: method || (body ? 'POST' : 'GET'),
  headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': ip || `10.0.${Math.floor(++ipN / 250)}.${ipN % 250}`,
    ...(admin ? { 'X-Admin-Password': PW } : {}) },
  body: body ? JSON.stringify(body) : undefined,
}).then(async r => ({ status: r.status, data: await r.json().catch(() => null) }));
const signUp = (slots, phone, name = 'Test Učenik', extra = {}) =>
  call('/api/prijava', { body: { name, phone, slots, adult: true, consent: true, website: '', ...extra } });
const phone = n => `091 ${String(1000000 + n).slice(1, 4)} ${String(1000000 + n).slice(4)}`;
const setCap = (id, capacity) => call(`/api/admin/slots/${id}`, { body: { capacity }, admin: true });
const free = async id => (await call('/api/stanje')).data.slots.find(s => s.id === id).free;

test('public state: 48 shifts, nothing personal', async () => {
  const { data } = await call('/api/stanje');
  assert.equal(data.slots.length, 48);
  assert.equal(data.open, true);
  assert.ok(data.slots.every(s => !('taken' in s) || s.taken === undefined));
});

test('30 people at once for the last place: exactly one gets it', async () => {
  await setCap('2026-12-20-A', 1);
  const res = await Promise.all(Array.from({ length: 30 }, (_, i) => signUp(['2026-12-20-A'], phone(100 + i))));
  assert.equal(res.filter(r => r.status === 200).length, 1);
  assert.ok(res.filter(r => r.status !== 200).every(r => r.data.error === 'full'));
  assert.equal(await free('2026-12-20-A'), 0);
});

test('40 people at once for 3 places: exactly three get them', async () => {
  await setCap('2026-12-21-B', 3);
  const res = await Promise.all(Array.from({ length: 40 }, (_, i) => signUp(['2026-12-21-B'], phone(200 + i))));
  assert.equal(res.filter(r => r.status === 200).length, 3);
  assert.equal(await free('2026-12-21-B'), 0);
});

test('one person sending many sign-ups at once stays at 30 h a week', async () => {
  const days = ['2026-12-14', '2026-12-15', '2026-12-16', '2026-12-17', '2026-12-18'];
  for (const d of days) await setCap(`${d}-B`, 5);
  const res = await Promise.all(days.map(d => signUp([`${d}-B`], phone(300))));   // 5 × 8 h in week 51
  assert.equal(res.filter(r => r.status === 200).length, 3);                     // 24 h; a 4th would be 32 h
  assert.ok(res.filter(r => r.status !== 200).every(r => r.data.error === 'week_hours'));
  const { data } = await call('/api/admin/data', { admin: true });
  const p = data.people.find(x => x.phone_fmt === phone(300));
  assert.ok(p && p.weeks['2026-W51'] <= 30, JSON.stringify(p));
});

test('one block a day, also when A and B are sent at the same moment', async () => {
  const res = await Promise.all([signUp(['2026-12-22-A'], phone(400)), signUp(['2026-12-22-B'], '+385 91 000 400')]);   // same number, other spelling
  assert.equal(res.filter(r => r.status === 200).length, 1);
  assert.equal(res.find(r => r.status !== 200).data.error, 'one_per_day');
  const both = await signUp(['2026-12-23-A', '2026-12-23-B'], phone(401));
  assert.equal(both.data.error, 'one_per_day');
});

test('a sign-up with a rule broken is rejected as a whole', async () => {
  // week 52: 23.12. B (8) + 24.12. B (11) + 25.12. B (8) + 26.12. A (7) = 34 h
  const r = await signUp(['2026-12-23-B', '2026-12-24-B', '2026-12-25-B', '2026-12-26-A'], phone(500));
  assert.equal(r.data.error, 'week_hours');
  assert.equal((await call('/api/admin/data', { admin: true })).data.regs.filter(x => x.phone_fmt === phone(500)).length, 0);
});

test('form checks: adult, consent, honeypot, name, phone', async () => {
  assert.equal((await signUp(['2026-12-26-A'], phone(600), 'Ana Anić', { adult: false })).data.error, 'adult');
  assert.equal((await signUp(['2026-12-26-A'], phone(600), 'Ana Anić', { consent: false })).data.error, 'consent');
  assert.equal((await signUp(['2026-12-26-A'], phone(600), 'Ana Anić', { website: 'http://spam' })).data.error, 'invalid');
  assert.equal((await signUp(['2026-12-26-A'], phone(600), 'Ana')).data.error, 'name');
  assert.equal((await signUp(['2026-12-26-A'], '051 123 456', 'Ana Anić')).data.error, 'phone');
});

test('sign-up, private link, cancel; nothing personal in the public state', async () => {
  const r = await signUp(['2026-12-28-A', '2026-12-29-B'], '0981234567', 'Marko Marić');
  assert.equal(r.status, 200);
  assert.equal(r.data.regs.length, 2);
  const mine = await call(`/api/moji/${r.data.token}`);
  assert.equal(mine.data.name, 'Marko Marić');
  const pub = JSON.stringify((await call('/api/stanje')).data);
  assert.ok(!pub.includes('Marko') && !pub.includes('981234567'));
  const c = await call(`/api/moji/${r.data.token}/otkazi`, { body: { id: r.data.regs[0].id } });
  assert.equal(c.data.regs.length, 1);
  assert.equal((await call(`/api/moji/${r.data.token}/otkazi`, { body: { id: 999999 } })).status, 404);
});

test('closed sign-up is refused; organizer opens it again', async () => {
  await call('/api/admin/settings', { body: { open: false }, admin: true });
  assert.equal((await signUp(['2026-12-30-A'], phone(700))).data.error, 'closed');
  await call('/api/admin/settings', { body: { open: true }, admin: true });
  assert.equal((await signUp(['2026-12-30-A'], phone(700))).status, 200);
});

test('manual confirmation: pending holds the place until the organizer confirms', async () => {
  await call('/api/admin/settings', { body: { manual: true }, admin: true });
  await setCap('2026-12-31-A', 1);
  const r = await signUp(['2026-12-31-A'], phone(800));
  assert.equal(r.data.regs[0].status, 'pending');
  assert.equal((await signUp(['2026-12-31-A'], phone(801))).data.error, 'full');
  const id = r.data.regs[0].id;
  const after = await call(`/api/admin/regs/${id}/confirm`, { body: {}, admin: true });
  assert.equal(after.data.regs.find(x => x.id === id).status, 'confirmed');
  await call('/api/admin/settings', { body: { manual: false }, admin: true });
});

test('organizer: wrong password, add by hand (force), export, CSV import, wipe', async () => {
  assert.equal((await fetch(BASE + '/api/admin/data', { headers: { 'X-Admin-Password': 'krivo', 'CF-Connecting-IP': '10.9.9.9' } })).status, 401);
  const full = await call('/api/admin/regs', { body: { slot: '2026-12-20-A', name: 'Ivo Ivić', phone: phone(900) }, admin: true });
  assert.equal(full.data.error, 'full');
  const forced = await call('/api/admin/regs', { body: { slot: '2026-12-20-A', name: 'Ivo Ivić', phone: phone(900), force: true }, admin: true });
  assert.equal(forced.status, 200);
  const bytes = new Uint8Array(await fetch(BASE + '/api/admin/export.csv', { headers: { 'X-Admin-Password': PW } }).then(r => r.arrayBuffer()));
  assert.deepEqual([...bytes.slice(0, 3)], [0xef, 0xbb, 0xbf]);   // BOM, so Excel reads the letters right
  const csv = new TextDecoder().decode(bytes);
  assert.ok(csv.startsWith('Datum;Dan;Tjedan;Blok'));
  assert.ok(csv.includes('Ivo Ivić') && csv.includes(phone(900)));
  // importing shifts that would drop a shift with sign-ups is refused
  const bad = await call('/api/admin/import', { body: { csv: 'Datum;Blok;Mjesta\n10.12.2026.;A;2\n' }, admin: true });
  assert.equal(bad.data.error, 'slots_in_use');
  const wiped = await call('/api/admin/wipe', { body: { confirm: 'OBRIŠI' }, admin: true });
  assert.equal(wiped.data.regs.length, 0);
  const csvText = 'Datum;Blok;Od;Do;Sati;Mjesta\n' + (await call('/api/stanje')).data.slots
    .map(s => `${s.day};${s.block};${s.start};${s.end};${s.hours};${s.id === '2026-12-24-B' ? 4 : 2}`).join('\n');
  const ok = await call('/api/admin/import', { body: { csv: csvText }, admin: true });
  assert.equal(ok.data.slots.find(s => s.id === '2026-12-24-B').capacity, 4);
});

test('QR code: PNG and SVG of the public page', async () => {
  const png = new Uint8Array(await fetch(BASE + '/qr.png').then(r => r.arrayBuffer()));
  assert.deepEqual([...png.slice(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const svg = await fetch(BASE + '/qr.svg').then(r => r.text());
  assert.ok(svg.includes('<svg') && svg.includes('<path'));
});

test('per-IP limit on sign-ups', async () => {
  const one = [];
  for (let i = 0; i < 17; i++) one.push(await call('/api/prijava', { ip: '10.200.0.1', body: { name: 'Spam Spam', phone: phone(2000 + i), slots: ['2027-01-02-A'], adult: true, consent: true } }));
  assert.ok(one.slice(15).every(r => r.data.error === 'too_many'));
});
