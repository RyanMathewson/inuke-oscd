import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createStore, initialState, channelPatch } from '../src/state.js';

// Regression test: set() must merge a function-style patch's return value
// into the existing state, not replace the whole state with it. Every
// caller that uses the function form (channelPatch, the /preset/name
// handler in sync.js, setup.js's refreshPreset) returns only a partial
// object, by convention -- e.g. channelPatch returns just {channels: {...}}.

test('set() with a function patch merges the returned partial into existing state', () => {
  const store = createStore(initialState());
  store.set({ ampMode: 'BRIDGED', connected: true });
  store.set((s) => channelPatch(s, 2, (c) => ({ ...c, delay: { timeMs: 5, phaseDeg: 180 } })));

  const state = store.get();
  assert.equal(state.ampMode, 'BRIDGED');
  assert.equal(state.connected, true);
  assert.ok(Array.isArray(state.presets));
  assert.ok(state.meter);
  assert.deepEqual(state.channels[2].delay, { timeMs: 5, phaseDeg: 180 });
});

test('set() with a function patch that returns only {presets: ...} does not drop other fields', () => {
  const store = createStore(initialState());
  store.set({ ampMode: 'BRIDGED' });
  store.set((s) => ({ presets: s.presets.map((p) => (p.slot === 3 ? { ...p, name: 'Foo' } : p)) }));

  const state = store.get();
  assert.equal(state.ampMode, 'BRIDGED');
  assert.equal(state.presets.find((p) => p.slot === 3).name, 'Foo');
  assert.ok(state.channels[1]);
});
