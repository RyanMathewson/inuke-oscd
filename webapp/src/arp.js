// Read/write the vendor app's own `.arp` preset file format. See
// docs/PROTOCOL_NOTES.md, "`.arp` preset file format" and "OSC address
// space", plus the real sample at ../../existing_settings.arp. Plain-text
// dump of OSC SET messages between BEGIN_OSC_DATA/END_OSC_DATA markers, one
// line per persisted address -- loading a preset is just replaying these
// lines as OSC SETs.
//
// formatArp/parseArp operate on the same { ampMode, channels } shape as
// webapp/src/state.js's store slice, so a live-synced state can round-trip:
// store.get() -> formatArp() -> (file) -> parseArp() -> push via protocol.js.
import { emptyChannel } from './state.js';
import { CHANNELS, PEQ_BANDS, DEQ_BANDS } from './constants.js';

export class ArpFormatError extends Error {}

// --- numeric formatting (write side) ---------------------------------
// Byte-exact vendor formatting isn't required -- only structure and values
// need to round-trip. Frequencies reproduce the vendor's "NkNN" shorthand
// for values >= 1000 Hz, since that's the one piece of cosmetic fidelity
// worth having for files a user might reopen in the vendor app.

function formatNum(v) {
  let s = Number(v).toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  if (s === '' || s === '-' || s === '-0') s = '0';
  return s;
}

function formatFreq(v) {
  v = Number(v);
  if (v < 1000) return formatNum(v);
  const thousands = v / 1000;
  let whole = Math.trunc(thousands);
  let frac = Math.round((thousands - whole) * 100);
  if (frac >= 100) {
    whole += 1;
    frac = 0;
  }
  return `${whole}k${String(frac).padStart(2, '0')}`;
}

function parseFreqToken(tok) {
  if (tok.includes('k')) {
    const [left, right] = tok.split('k');
    return parseFloat(`${left}.${right}`) * 1000;
  }
  return parseFloat(tok);
}

// --- writer -------------------------------------------------------------

function peqLine(ch, band, p) {
  return `/channel/${ch}/peq/${band} sfff ${p.type} ${formatFreq(p.freq)} ${formatNum(p.gain)} ${formatNum(p.q)}`;
}
function xoverHpLine(ch, hp) {
  return `/channel/${ch}/xover/hp sf ${hp.type} ${formatFreq(hp.freq)}`;
}
function xoverLpLine(ch, lp) {
  return `/channel/${ch}/xover/lp sf ${lp.type} ${formatFreq(lp.freq)}`;
}
function xoverGainLine(ch, gain) {
  return `/channel/${ch}/xover/gain f ${formatNum(gain)}`;
}
function deqCompLine(ch, band, c) {
  return `/channel/${ch}/deq/${band}/comp fff ${formatNum(c.gain)} ${formatNum(c.threshold)} ${formatNum(c.ratio)}`;
}
function deqTimeLine(ch, band, t) {
  return `/channel/${ch}/deq/${band}/time ff ${formatNum(t.attack)} ${formatNum(t.release)}`;
}
function deqFiltLine(ch, band, f) {
  return `/channel/${ch}/deq/${band}/filt sff ${f.type} ${formatFreq(f.freq)} ${formatNum(f.q)}`;
}
function delayLine(ch, d) {
  return `/channel/${ch}/delay fi ${formatNum(d.timeMs)} ${Math.trunc(d.phaseDeg)}`;
}
function limiterLine(ch, l) {
  return `/channel/${ch}/limiter fff ${formatNum(l.thresholdVp)} ${formatNum(l.releaseMs)} ${formatNum(l.holdMs)}`;
}

export function formatArp({ ampMode, channels }) {
  const lines = [`/ampmode s ${ampMode}`];
  for (const ch of CHANNELS) {
    const c = channels[ch];
    for (const band of PEQ_BANDS) lines.push(peqLine(ch, band, c.peq[band]));
    lines.push(xoverHpLine(ch, c.xover.hp));
    lines.push(xoverLpLine(ch, c.xover.lp));
    lines.push(xoverGainLine(ch, c.xover.gain));
    for (const band of DEQ_BANDS) {
      lines.push(deqCompLine(ch, band, c.deq[band].comp));
      lines.push(deqTimeLine(ch, band, c.deq[band].time));
      lines.push(deqFiltLine(ch, band, c.deq[band].filt));
    }
    lines.push(delayLine(ch, c.delay));
    lines.push(limiterLine(ch, c.limiter));
  }
  return `\r\nBEGIN_OSC_DATA\r\n${lines.join('\r\n')}\r\nEND_OSC_DATA`;
}

// --- reader ---------------------------------------------------------------

function decodeArgs(addr, typetags, raw) {
  if (raw.length !== typetags.length) {
    throw new ArpFormatError(`malformed line for ${addr}: expected ${typetags.length} arg(s) for typetags '${typetags}', got ${raw.length}`);
  }
  const out = [];
  for (let i = 0; i < typetags.length; i++) {
    const t = typetags[i];
    const v = raw[i];
    if (t === 'f') out.push(parseFreqToken(v));
    else if (t === 'i') out.push(parseInt(v, 10));
    else if (t === 's') out.push(v);
    else throw new ArpFormatError(`unsupported typetag '${t}' on line for ${addr}`);
  }
  return out;
}

export function parseArp(text) {
  const lines = text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0);

  const begin = lines.indexOf('BEGIN_OSC_DATA');
  const end = lines.indexOf('END_OSC_DATA');
  if (begin === -1 || end === -1) {
    throw new ArpFormatError('not a valid Preset (.arp) file (missing BEGIN_OSC_DATA/END_OSC_DATA markers)');
  }
  if (end < begin) {
    throw new ArpFormatError('not a valid Preset (.arp) file (END_OSC_DATA precedes BEGIN_OSC_DATA)');
  }

  let ampMode = null;
  const channels = {};
  for (const ch of CHANNELS) channels[ch] = emptyChannel();

  for (const line of lines.slice(begin + 1, end)) {
    const parts = line.split(/\s+/);
    if (parts.length < 2) throw new ArpFormatError(`malformed line: ${line}`);
    const [addr, typetags, ...raw] = parts;
    const args = decodeArgs(addr, typetags, raw);

    if (addr === '/ampmode') {
      ampMode = args[0];
      continue;
    }

    const m = /^\/channel\/(\d)\/(.+)$/.exec(addr);
    if (!m) continue; // not a persisted address we track (e.g. /meter) -- ignore
    const ch = Number(m[1]);
    if (!channels[ch]) continue;
    const rest = m[2];

    let bm;
    if ((bm = /^peq\/(\d)$/.exec(rest))) {
      const band = Number(bm[1]);
      channels[ch].peq[band] = { type: args[0], freq: args[1], gain: args[2], q: args[3] };
    } else if (rest === 'xover/hp') {
      channels[ch].xover.hp = { type: args[0], freq: args[1] };
    } else if (rest === 'xover/lp') {
      channels[ch].xover.lp = { type: args[0], freq: args[1] };
    } else if (rest === 'xover/gain') {
      channels[ch].xover.gain = args[0];
    } else if ((bm = /^deq\/(\d)\/comp$/.exec(rest))) {
      const band = Number(bm[1]);
      channels[ch].deq[band].comp = { gain: args[0], threshold: args[1], ratio: args[2] };
    } else if ((bm = /^deq\/(\d)\/time$/.exec(rest))) {
      const band = Number(bm[1]);
      channels[ch].deq[band].time = { attack: args[0], release: args[1] };
    } else if ((bm = /^deq\/(\d)\/filt$/.exec(rest))) {
      const band = Number(bm[1]);
      channels[ch].deq[band].filt = { type: args[0], freq: args[1], q: args[2] };
    } else if (rest === 'delay') {
      channels[ch].delay = { timeMs: args[0], phaseDeg: args[1] };
    } else if (rest === 'limiter') {
      channels[ch].limiter = { thresholdVp: args[0], releaseMs: args[1], holdMs: args[2] };
    }
    // else: unrecognized channel sub-address -- ignore for forward compat
  }

  if (ampMode === null) {
    throw new ArpFormatError('not a valid Preset (.arp) file (no /ampmode entry found)');
  }

  return { ampMode, channels };
}
