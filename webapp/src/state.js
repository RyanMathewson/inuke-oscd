import { CHANNELS, PEQ_BANDS, DEQ_BANDS, PRESET_SLOT_COUNT } from './constants.js';

export function createStore(initial) {
  let state = initial;
  const listeners = new Set();
  return {
    get: () => state,
    set(patch) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      state = { ...state, ...next };
      for (const l of listeners) l(state);
    },
    subscribe(fn) {
      listeners.add(fn);
      fn(state);
      return () => listeners.delete(fn);
    },
  };
}

function emptyChannel() {
  return {
    peq: Object.fromEntries(PEQ_BANDS.map((b) => [b, { type: 'OFF', freq: 0, gain: 0, q: 0 }])),
    xover: { hp: { type: 'OFF', freq: 0 }, lp: { type: 'OFF', freq: 0 }, gain: 0 },
    deq: Object.fromEntries(
      DEQ_BANDS.map((b) => [
        b,
        {
          comp: { gain: 0, threshold: 0, ratio: 1 },
          time: { attack: 0, release: 0 },
          filt: { type: 'OFF', freq: 0, q: 0 },
        },
      ]),
    ),
    delay: { timeMs: 0, phaseDeg: 0 },
    limiter: { thresholdVp: 0, releaseMs: 0, holdMs: 0 },
  };
}

export function initialState() {
  return {
    supported: true,
    connected: false,
    busy: false,
    syncProgress: null,
    lastError: null,
    log: [],
    info: null,
    ampName: '',
    ampMode: 'STEREO',
    gain: null,
    lock: null,
    channels: { 1: emptyChannel(), 2: emptyChannel() },
    presets: Array.from({ length: PRESET_SLOT_COUNT }, (_, i) => ({ slot: i + 1, name: 'EMPTY', modeEnum: 0 })),
    selectedPreset: 1,
    meter: { inputA: 0, inputB: 0, outputA: 0, outputB: 0 },
  };
}

export function channelPatch(state, ch, patch) {
  return {
    channels: {
      ...state.channels,
      [ch]: typeof patch === 'function' ? patch(state.channels[ch]) : { ...state.channels[ch], ...patch },
    },
  };
}
