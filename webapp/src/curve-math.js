// Magnitude-response approximations used to draw the PEQ/crossover curves.
//
// These are idealized analog-prototype formulas (a standard symmetric
// resonance shape for parametric peaks/shelves, Butterworth-style roll-off
// for crossover slopes) -- the amp's actual internal digital filter design
// (sample rate, exact topology, and any difference between the Butterworth/
// Bessel/Linkwitz-Riley crossover families) is not known from the reverse
// engineering in PROTOCOL_NOTES.md, so these curves are a visual guide to
// the configured frequency/gain/Q/slope, not a precision emulation of the
// DSP's exact response.

export function peqBandDb(type, freq, gainDb, q, f) {
  if (!type || type === 'OFF' || !freq || !gainDb) return 0;
  if (type === 'PEQ') {
    const x = f / freq;
    const denom = Math.sqrt(1 + (q * (x - 1 / x)) ** 2);
    return gainDb / denom;
  }
  const shelfOrder = { LS6: 1, LS12: 2, HS6: 1, HS12: 2 }[type];
  if (!shelfOrder) return 0;
  const isLow = type.startsWith('LS');
  const ratio = isLow ? f / freq : freq / f;
  return gainDb / (1 + ratio ** (2 * shelfOrder));
}

export function peqCurveDb(bands, f) {
  return bands.reduce((sum, b) => sum + peqBandDb(b.type, b.freq, b.gain, b.q, f), 0);
}

function xoverOrder(type) {
  const m = /(\d+)$/.exec(type || '');
  return m ? parseInt(m[1], 10) / 6 : 0;
}

function butterworthLpDb(fc, order, f) {
  if (!fc || order <= 0) return 0;
  return -10 * Math.log10(1 + (f / fc) ** (2 * order));
}

function butterworthHpDb(fc, order, f) {
  if (!fc || order <= 0) return 0;
  return -10 * Math.log10(1 + (fc / f) ** (2 * order));
}

export function xoverCurveDb(hp, lp, gainDb, f) {
  let db = gainDb || 0;
  if (hp && hp.type && hp.type !== 'OFF') db += butterworthHpDb(hp.freq, xoverOrder(hp.type), f);
  if (lp && lp.type && lp.type !== 'OFF') db += butterworthLpDb(lp.freq, xoverOrder(lp.type), f);
  return db;
}

export function logSpace(min, max, count) {
  const out = [];
  const logMin = Math.log10(min);
  const logMax = Math.log10(max);
  for (let i = 0; i < count; i++) {
    out.push(10 ** (logMin + ((logMax - logMin) * i) / (count - 1)));
  }
  return out;
}
