import { test } from 'node:test';
import assert from 'node:assert/strict';
import { peqBandDb, peqCurveDb, xoverCurveDb, logSpace } from '../src/curve-math.js';

test('PEQ band peaks at exactly its gain right at the center frequency', () => {
  assert.ok(Math.abs(peqBandDb('PEQ', 1000, 6, 1.0, 1000) - 6) < 1e-9);
  assert.ok(Math.abs(peqBandDb('PEQ', 1000, -8, 2.0, 1000) - -8) < 1e-9);
});

test('PEQ band decays toward 0dB far from its center frequency', () => {
  const near = peqBandDb('PEQ', 1000, 6, 1.0, 1000);
  const far = peqBandDb('PEQ', 1000, 6, 1.0, 100);
  assert.ok(Math.abs(far) < Math.abs(near));
  assert.ok(Math.abs(peqBandDb('PEQ', 1000, 6, 1.0, 100000)) < 0.5);
});

test('a disabled/zero-gain band contributes nothing', () => {
  assert.equal(peqBandDb('OFF', 1000, 6, 1.0, 1000), 0);
  assert.equal(peqBandDb('PEQ', 1000, 0, 1.0, 1000), 0);
  assert.equal(peqBandDb('PEQ', 0, 6, 1.0, 1000), 0);
});

test('low shelf approaches full gain well below its frequency and 0dB well above it', () => {
  const low = peqBandDb('LS12', 200, 6, 1, 20);
  const high = peqBandDb('LS12', 200, 6, 1, 20000);
  assert.ok(low > 5.5);
  assert.ok(Math.abs(high) < 0.1);
});

test('high shelf approaches full gain well above its frequency and 0dB well below it', () => {
  const low = peqBandDb('HS12', 4000, -6, 1, 20);
  const high = peqBandDb('HS12', 4000, -6, 1, 20000);
  assert.ok(Math.abs(low) < 0.1);
  assert.ok(high < -5.5);
});

test('higher shelf order (12 vs 6) transitions more sharply', () => {
  // one octave below the shelf frequency, LS12 should be closer to full gain than LS6
  const ls6 = peqBandDb('LS6', 1000, 6, 1, 500);
  const ls12 = peqBandDb('LS12', 1000, 6, 1, 500);
  assert.ok(ls12 > ls6);
});

test('peqCurveDb sums multiple active bands and skips OFF bands', () => {
  const bands = [
    { type: 'PEQ', freq: 1000, gain: 3, q: 5 },
    { type: 'OFF', freq: 1000, gain: 100, q: 5 },
    { type: 'PEQ', freq: 1000, gain: 2, q: 5 },
  ];
  assert.ok(Math.abs(peqCurveDb(bands, 1000) - 5) < 1e-6);
});

test('xover HP attenuates well below cutoff and passes well above it', () => {
  const hp = { type: 'BUT24', freq: 100 };
  const below = xoverCurveDb(hp, null, 0, 10);
  const above = xoverCurveDb(hp, null, 0, 10000);
  assert.ok(below < -20);
  assert.ok(Math.abs(above) < 1);
});

test('xover LP attenuates well above cutoff and passes well below it', () => {
  const lp = { type: 'BUT24', freq: 1000 };
  const below = xoverCurveDb(null, lp, 0, 100);
  const above = xoverCurveDb(null, lp, 0, 100000);
  assert.ok(Math.abs(below) < 1);
  assert.ok(above < -20);
});

test('a higher-order (steeper slope) filter attenuates more at a fixed offset from cutoff', () => {
  const lp12 = { type: 'BUT12', freq: 1000 };
  const lp48 = { type: 'BUT48', freq: 1000 };
  const at2x = (t) => xoverCurveDb(null, t, 0, 2000);
  assert.ok(at2x(lp48) < at2x(lp12));
});

test('OFF crossover stages contribute nothing, gain offset still applies', () => {
  assert.equal(xoverCurveDb({ type: 'OFF', freq: 100 }, { type: 'OFF', freq: 1000 }, 3.5, 500), 3.5);
});

test('logSpace produces count points spanning exactly [min, max] on a log scale', () => {
  const points = logSpace(20, 20000, 5);
  assert.equal(points.length, 5);
  assert.ok(Math.abs(points[0] - 20) < 1e-9);
  assert.ok(Math.abs(points[4] - 20000) < 1e-6);
  // midpoint of a log sweep from 20 to 20000 is the geometric mean, ~632.45
  assert.ok(Math.abs(points[2] - Math.sqrt(20 * 20000)) < 1e-6);
});
