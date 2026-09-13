// Protocol constants from docs/PROTOCOL_NOTES.md's Quick Reference / address table.

export const AMP_MODES = ['DUAL', 'STEREO', 'BIAMP1', 'BIAMP2', 'BRIDGED'];

export const AMP_MODE_LABELS = {
  DUAL: 'Dual Mono',
  STEREO: 'Stereo',
  BIAMP1: 'Bi-Amp 1',
  BIAMP2: 'Bi-Amp 2',
  BRIDGED: 'Bridge (Channel A+B)',
};

// Enum order used by /preset/save's ampmode_enum arg (matches the UI's Mode
// button order and the amp's own empty-slot default of DUAL=0).
export const AMP_MODE_ENUM = { DUAL: 0, STEREO: 1, BIAMP1: 2, BIAMP2: 3, BRIDGED: 4 };
export const AMP_MODE_BY_ENUM = ['DUAL', 'STEREO', 'BIAMP1', 'BIAMP2', 'BRIDGED'];

// PEQ band 1 and 8 (shelf-capable) offer this full list; OFF is applied via
// the band's own enable toggle, not this dropdown -- see PROTOCOL_NOTES.md
// "Critical gotchas" #2.
export const PEQ_TYPES = ['PEQ', 'LS6', 'LS12', 'HS6', 'HS12'];

export const XOVER_FAMILIES = ['BUT', 'BES', 'LR'];
export const XOVER_FAMILY_LABELS = { BUT: 'Butterworth', BES: 'Bessel', LR: 'Linkwitz-Riley' };
export const XOVER_SLOPES = [6, 12, 18, 24, 48];

export const DEQ_FILT_TYPES = ['BP', 'LP6', 'LP12', 'HP6', 'HP12'];

export const PRESET_SLOT_COUNT = 20;
export const CHANNELS = [1, 2];
export const PEQ_BANDS = [1, 2, 3, 4, 5, 6, 7, 8];
export const DEQ_BANDS = [1, 2];

// Conservative input-validation bounds. None of these are documented device
// limits -- PROTOCOL_NOTES.md never pinned down the amp's actual valid
// ranges for these fields -- so these are deliberately generous guesses
// meant only to block nonsensical input (zero/negative frequencies break
// the log-scale chart math with NaN, for instance), not to second-guess a
// real device ceiling we don't know.
export const BOUNDS = {
  freqHz: { min: 1, max: 20000 },
  gainDb: { min: -24, max: 24 },
  thresholdDb: { min: -60, max: 0 },
  ratio: { min: 1, max: 20 },
  q: { min: 0.01, max: 20 },
  delayMs: { min: 0, max: 1000 },
  timeMs: { min: 0, max: 2000 },
  limiterThresholdVp: { min: 0, max: 200 },
  ampNameLength: 28,
  presetNameLength: 28,
};
