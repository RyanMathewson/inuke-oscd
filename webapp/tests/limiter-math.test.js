import { test } from 'node:test';
import assert from 'node:assert/strict';
import { vpToDbfsEstimate, DBFS_REFERENCE_VP, peakWatts } from '../src/limiter-math.js';

test('reproduces the one confirmed data point: 69.9 Vp -> -1.7 dBFS (legacy app screenshot default)', () => {
  assert.ok(Math.abs(vpToDbfsEstimate(69.9) - -1.7) < 0.02);
});

test('the reference voltage itself reads as exactly 0 dBFS', () => {
  assert.ok(Math.abs(vpToDbfsEstimate(DBFS_REFERENCE_VP)) < 1e-9);
});

test('a threshold above the reference voltage is positive dBFS', () => {
  assert.ok(vpToDbfsEstimate(120) > 0);
});

test('zero or negative input has no defined dBFS -- returns -Infinity rather than NaN or throwing', () => {
  assert.equal(vpToDbfsEstimate(0), -Infinity);
  assert.equal(vpToDbfsEstimate(-5), -Infinity);
});

test('peakWatts reproduces the legacy app screenshot exactly: 69.9 Vp @ 8 ohms -> 305.4 W', () => {
  assert.ok(Math.abs(peakWatts(69.9, 8) - 305.4) < 0.05);
});

test('peakWatts halves as ohms doubles, for a fixed voltage', () => {
  const at4 = peakWatts(69.9, 4);
  const at8 = peakWatts(69.9, 8);
  assert.ok(Math.abs(at8 * 2 - at4) < 1e-9);
});

test('peakWatts is 0 for a zero/negative voltage or load, not NaN or throwing', () => {
  assert.equal(peakWatts(0, 8), 0);
  assert.equal(peakWatts(-10, 8), 0);
  assert.equal(peakWatts(69.9, 0), 0);
});
