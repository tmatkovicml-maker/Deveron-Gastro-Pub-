import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizePhone, isoWeek, checkChoice, defaultSlots, parseSlotsCsv, hoursBetween } from '../src/rules.js';

test('phone numbers are normalized to one form', () => {
  for (const v of ['091 234 5678', '+385 91 234 5678', '00385912345678', '385912345678', '091/234-5678', '+385 (0)91 234 5678'])
    assert.equal(normalizePhone(v), '+385912345678', v);
  assert.equal(normalizePhone('098 123 456'), '+38598123456');
  assert.equal(normalizePhone('+49 151 23456789'), '+4915123456789');
  for (const v of ['', '123', '051 234 567', 'abc', '+385 1 2345 678']) assert.equal(normalizePhone(v), null, v);
});

test('ISO weeks of the season are 50–53', () => {
  assert.equal(isoWeek('2026-12-10'), '2026-W50');
  assert.equal(isoWeek('2026-12-13'), '2026-W50');
  assert.equal(isoWeek('2026-12-14'), '2026-W51');
  assert.equal(isoWeek('2026-12-27'), '2026-W52');
  assert.equal(isoWeek('2026-12-28'), '2026-W53');
  assert.equal(isoWeek('2027-01-02'), '2026-W53');
});

test('starting shifts: 24 days, 48 shifts, long nights 11 h', () => {
  const s = defaultSlots();
  assert.equal(s.length, 48);
  assert.equal(s[0].id, '2026-12-10-A'); assert.equal(s.at(-1).id, '2027-01-02-B');
  assert.equal(s.find(x => x.id === '2026-12-10-A').hours, 7);
  assert.equal(s.find(x => x.id === '2026-12-10-B').hours, 8);
  for (const d of ['2026-12-24', '2026-12-27', '2026-12-31']) assert.equal(s.find(x => x.id === `${d}-B`).hours, 11);
  assert.equal(hoursBetween('16:00', '00:00'), 8);
});

test('one block a day', () => {
  const a = { id: '2026-12-15-A', day: '2026-12-15', hours: 7 }, b = { id: '2026-12-15-B', day: '2026-12-15', hours: 8 };
  assert.equal(checkChoice([], [a, b]).error, 'one_per_day');
  assert.equal(checkChoice([a], [b]).error, 'one_per_day');
  assert.equal(checkChoice([], [a]), null);
});

test('at most 30 hours in an ISO week', () => {
  const B = d => ({ id: `${d}-B`, day: d, hours: 8 }), A = d => ({ id: `${d}-A`, day: d, hours: 7 });
  // week 51: 3 × B = 24 h + A = 31 h → too many
  assert.equal(checkChoice([], [B('2026-12-14'), B('2026-12-15'), B('2026-12-16'), A('2026-12-17')]).error, 'week_hours');
  // 2 × B + 2 × A = 30 h → allowed
  assert.equal(checkChoice([], [B('2026-12-14'), B('2026-12-15'), A('2026-12-16'), A('2026-12-17')]), null);
  // existing hours count too
  assert.equal(checkChoice([B('2026-12-14'), B('2026-12-15'), A('2026-12-16')], [B('2026-12-17')]).error, 'week_hours');
  // other weeks are separate: Sunday 20.12. is week 51, Monday 21.12. week 52
  assert.equal(checkChoice([B('2026-12-14'), B('2026-12-15'), A('2026-12-16'), A('2026-12-17')], [B('2026-12-21')]), null);
});

test('organizer CSV in different shapes', () => {
  const a = parseSlotsCsv('Datum;Dan;Blok;Od;Do;Sati;Mjesta\n10.12.2026.;čet;A;09:00;16:00;7;1\n10.12.2026.;čet;B;16:00;00:00;8;2\n24.12.2026.;čet;B;16:00;03:00;11;3\n');
  assert.deepEqual(a.map(s => [s.id, s.hours, s.capacity]), [['2026-12-10-A', 7, 1], ['2026-12-10-B', 8, 2], ['2026-12-24-B', 11, 3]]);
  const b = parseSlotsCsv('﻿datum,vrijeme,mjesta\n2027-01-02,09:00–16:00,2\n2027-01-02,16:00-03:00,3\n');
  assert.deepEqual(b.map(s => [s.id, s.end, s.hours]), [['2027-01-02-A', '16:00', 7], ['2027-01-02-B', '03:00', 11]]);
  const c = parseSlotsCsv('Datum;Termin;Mjesta\n31.12.;B;3\n1.1.;A;1\n');
  assert.deepEqual(c.map(s => s.id), ['2026-12-31-B', '2027-01-01-A']);
  assert.throws(() => parseSlotsCsv('Datum;Blok;Mjesta\n32.12.2026.;A;1\n'), /Redak 2/);
  assert.throws(() => parseSlotsCsv('Datum;Blok\n10.12.2026.;A\n'), /Mjesta/);
});
