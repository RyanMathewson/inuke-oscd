import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createStore, initialState } from '../src/state.js';
import { applyMessageToState } from '../src/sync.js';

function storeWithInitial() {
  return createStore(initialState());
}

test('/ampmode updates top-level ampMode', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/ampmode', typetags: 's', args: ['BRIDGED'] });
  assert.equal(store.get().ampMode, 'BRIDGED');
});

test('/channel/2/peq/5 updates only that band on channel 2, leaving channel 1 and other bands untouched', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/channel/2/peq/5', typetags: 'sfff', args: ['HS12', 8000, -2, 0.7] });
  const state = store.get();
  assert.deepEqual(state.channels[2].peq[5], { type: 'HS12', freq: 8000, gain: -2, q: 0.7 });
  assert.deepEqual(state.channels[1].peq[5], { type: 'OFF', freq: 0, gain: 0, q: 0 });
  assert.deepEqual(state.channels[2].peq[1], { type: 'OFF', freq: 0, gain: 0, q: 0 });
});

test('/channel/1/xover/hp and /channel/1/xover/lp update independently', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/channel/1/xover/hp', typetags: 'sf', args: ['BUT24', 80] });
  applyMessageToState(store, { addr: '/channel/1/xover/lp', typetags: 'sf', args: ['BES12', 120] });
  const x = store.get().channels[1].xover;
  assert.deepEqual(x.hp, { type: 'BUT24', freq: 80 });
  assert.deepEqual(x.lp, { type: 'BES12', freq: 120 });
});

test('/channel/2/deq/1/comp updates comp without clobbering that band\'s time/filt', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/channel/2/deq/1/time', typetags: 'ff', args: [5, 50] });
  applyMessageToState(store, { addr: '/channel/2/deq/1/comp', typetags: 'fff', args: [7, -13, 3] });
  const band = store.get().channels[2].deq[1];
  assert.deepEqual(band.comp, { gain: 7, threshold: -13, ratio: 3 });
  assert.deepEqual(band.time, { attack: 5, release: 50 });
});

test('/meter with 4 args updates the meter block', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/meter', typetags: 'ffff', args: [0.1, 0.2, 0.3, 0.4] });
  assert.deepEqual(store.get().meter, { inputA: 0.1, inputB: 0.2, outputA: 0.3, outputB: 0.4 });
});

test('/meter with 1 arg (the host->device heartbeat shape) is ignored, not mistaken for a device push', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/meter', typetags: 'f', args: [10.0] });
  assert.deepEqual(store.get().meter, { inputA: 0, inputB: 0, outputA: 0, outputB: 0 });
});

test('/preset/name updates only the matching slot', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/preset/name', typetags: 'iis', args: [7, 2, 'MyPreset'] });
  const presets = store.get().presets;
  assert.deepEqual(presets.find((p) => p.slot === 7), { slot: 7, modeEnum: 2, name: 'MyPreset' });
  assert.deepEqual(presets.find((p) => p.slot === 8), { slot: 8, name: 'EMPTY', modeEnum: 0 });
});

test('/lock coerces its int arg to a boolean', () => {
  const store = storeWithInitial();
  applyMessageToState(store, { addr: '/lock', typetags: 'i', args: [1] });
  assert.equal(store.get().lock, true);
  applyMessageToState(store, { addr: '/lock', typetags: 'i', args: [0] });
  assert.equal(store.get().lock, false);
});

test('a message with null args (e.g. a bare GET echoed back oddly) is ignored without throwing', () => {
  const store = storeWithInitial();
  assert.doesNotThrow(() => applyMessageToState(store, { addr: '/ampmode', typetags: null, args: null }));
});

test('an unrecognized channel sub-address is ignored without throwing', () => {
  const store = storeWithInitial();
  assert.doesNotThrow(() => applyMessageToState(store, { addr: '/channel/1/unknown/thing', typetags: 'f', args: [1] }));
});
