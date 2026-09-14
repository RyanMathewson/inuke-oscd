import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { formatArp, parseArp, ArpFormatError } from '../src/arp.js';
import { initialState } from '../src/state.js';

const FIXTURE = readFileSync(new URL('../../existing_settings.arp', import.meta.url), 'utf8');

test('round-trips a live state slice through formatArp -> parseArp', () => {
  const state = initialState();
  state.ampMode = 'BRIDGED';
  state.channels[1].peq[3] = { type: 'PEQ', freq: 250, gain: -4.5, q: 2.5 };
  state.channels[2].limiter = { thresholdVp: 69.9, releaseMs: 100, holdMs: 50 };

  const text = formatArp(state);
  const parsed = parseArp(text);

  assert.equal(parsed.ampMode, 'BRIDGED');
  assert.deepEqual(parsed.channels[1].peq[3], { type: 'PEQ', freq: 250, gain: -4.5, q: 2.5 });
  assert.deepEqual(parsed.channels[2].limiter, { thresholdVp: 69.9, releaseMs: 100, holdMs: 50 });
});

test('writer reproduces NkNN shorthand for frequencies >= 1000 Hz', () => {
  const state = initialState();
  state.channels[1].peq[1] = { type: 'PEQ', freq: 4000, gain: 0, q: 1 };
  const text = formatArp(state);
  assert.match(text, /4k00/);
});

test('parses the real vendor-saved existing_settings.arp fixture', () => {
  const parsed = parseArp(FIXTURE);
  assert.equal(parsed.ampMode, 'BIAMP1');

  const p2 = parsed.channels[1].peq[2];
  assert.equal(p2.type, 'PEQ');
  assert.ok(Math.abs(p2.freq - 33.9) < 0.01);
  assert.ok(Math.abs(p2.gain - -10.0) < 0.01);
  assert.ok(Math.abs(p2.q - 4.41) < 0.01);

  assert.ok(Math.abs(parsed.channels[1].peq[7].freq - 4000) < 0.01);
  assert.ok(Math.abs(parsed.channels[1].peq[8].freq - 10000) < 0.01);
});

test('parseArp rejects text without BEGIN_OSC_DATA/END_OSC_DATA markers', () => {
  assert.throws(() => parseArp('this is not a preset file'), ArpFormatError);
});

test('parseArp rejects a structurally-marked file missing /ampmode', () => {
  const text = '\r\nBEGIN_OSC_DATA\r\n/channel/1/delay fi 0.0 0\r\nEND_OSC_DATA';
  assert.throws(() => parseArp(text), ArpFormatError);
});
