import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clampNum } from '../src/utils.js';

test('clampNum passes through an in-range value', () => {
  assert.equal(clampNum('1000', { min: 1, max: 20000 }), 1000);
});

test('clampNum clamps a below-range value to min', () => {
  assert.equal(clampNum('-5', { min: 1, max: 20000 }), 1);
  assert.equal(clampNum('0', { min: 1, max: 20000 }), 1);
});

test('clampNum clamps an above-range value to max', () => {
  assert.equal(clampNum('999999', { min: 1, max: 20000 }), 20000);
});

test('clampNum falls back for non-finite input (empty, garbage, NaN)', () => {
  assert.equal(clampNum('', { min: 1, max: 20000 }, 40), 40);
  assert.equal(clampNum('abc', { min: 1, max: 20000 }, 40), 40);
  assert.equal(clampNum(undefined, { min: -24, max: 24 }, 0), 0);
});

test('clampNum defaults its fallback to min when none is given', () => {
  assert.equal(clampNum('nope', { min: 0.01, max: 20 }), 0.01);
});
