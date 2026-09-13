import { el, clampNum } from '../utils.js';
import { CHANNELS, DEQ_BANDS, DEQ_FILT_TYPES, BOUNDS } from '../constants.js';
import { channelPatch } from '../state.js';
import { createEqChart } from './eq-chart.js';

function deqBand(ch, band, { store, protocol, log }) {
  const enableToggle = el('input', { type: 'checkbox', class: 'toggle' });
  const filtType = el('select', {}, DEQ_FILT_TYPES.map((t) => el('option', { value: t }, t)));
  const filtFreq = el('input', { type: 'number', step: '1', min: BOUNDS.freqHz.min, max: BOUNDS.freqHz.max });
  const filtQ = el('input', { type: 'number', step: '0.01', min: BOUNDS.q.min, max: BOUNDS.q.max });
  const compGain = el('input', { type: 'number', step: '0.1', min: BOUNDS.gainDb.min, max: BOUNDS.gainDb.max });
  const compThresh = el('input', { type: 'number', step: '0.1', min: BOUNDS.thresholdDb.min, max: BOUNDS.thresholdDb.max });
  const compRatio = el('input', { type: 'number', step: '0.1', min: BOUNDS.ratio.min, max: BOUNDS.ratio.max });
  const timeAttack = el('input', { type: 'number', step: '0.1', min: BOUNDS.timeMs.min, max: BOUNDS.timeMs.max });
  const timeRelease = el('input', { type: 'number', step: '0.1', min: BOUNDS.timeMs.min, max: BOUNDS.timeMs.max });

  async function commitFilt() {
    const type = enableToggle.checked ? filtType.value : 'OFF';
    const freq = clampNum(filtFreq.value, BOUNDS.freqHz, 40);
    const q = clampNum(filtQ.value, BOUNDS.q, 1);
    filtFreq.value = freq;
    filtQ.value = q;
    try {
      await protocol.setDeqFilt(ch, band, type, freq, q);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, deq: { ...c.deq, [band]: { ...c.deq[band], filt: { type, freq, q } } } })));
      log(`Ch${ch} DEQ${band} filt -> ${type} ${freq}Hz Q${q}`);
    } catch (err) {
      log(`Ch${ch} DEQ${band} setDeqFilt failed: ${err.message}`, true);
    }
  }
  async function commitComp() {
    const gain = clampNum(compGain.value, BOUNDS.gainDb, 0);
    const threshold = clampNum(compThresh.value, BOUNDS.thresholdDb, -20);
    const ratio = clampNum(compRatio.value, BOUNDS.ratio, 1);
    compGain.value = gain;
    compThresh.value = threshold;
    compRatio.value = ratio;
    try {
      await protocol.setDeqComp(ch, band, gain, threshold, ratio);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, deq: { ...c.deq, [band]: { ...c.deq[band], comp: { gain, threshold, ratio } } } })));
      log(`Ch${ch} DEQ${band} comp -> gain=${gain}dB thr=${threshold}dB ratio=1:${ratio}`);
    } catch (err) {
      log(`Ch${ch} DEQ${band} setDeqComp failed: ${err.message}`, true);
    }
  }
  async function commitTime() {
    const attack = clampNum(timeAttack.value, BOUNDS.timeMs, 0);
    const release = clampNum(timeRelease.value, BOUNDS.timeMs, 0);
    timeAttack.value = attack;
    timeRelease.value = release;
    try {
      await protocol.setDeqTime(ch, band, attack, release);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, deq: { ...c.deq, [band]: { ...c.deq[band], time: { attack, release } } } })));
      log(`Ch${ch} DEQ${band} time -> atk=${attack}ms rel=${release}ms`);
    } catch (err) {
      log(`Ch${ch} DEQ${band} setDeqTime failed: ${err.message}`, true);
    }
  }

  [enableToggle, filtType, filtFreq, filtQ].forEach((n) => n.addEventListener('change', commitFilt));
  [compGain, compThresh, compRatio].forEach((n) => n.addEventListener('change', commitComp));
  [timeAttack, timeRelease].forEach((n) => n.addEventListener('change', commitTime));

  const chart = createEqChart({ dbMin: -50, dbMax: 0, dbStep: 10 });
  chart.setCurve(() => 0);

  const bandEl = el('div', { class: 'band' }, [
    el('div', { class: 'band-header' }, [el('strong', {}, `DEQ ${band}`), enableToggle]),
    el('div', { class: 'chart-wrap' }, [
      chart.svg,
      chart.labelsEl,
      el('p', { class: 'note' }, 'Marker shows the sidechain filter\'s center frequency -- gain is signal-dependent, so there\'s no static curve to draw.'),
    ]),
    el('h3', {}, 'Sidechain filter'),
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field', style: 'flex:1.2' }, [el('label', {}, 'Type'), filtType]),
      el('div', { class: 'field' }, [el('label', {}, 'Freq (Hz)'), filtFreq]),
      el('div', { class: 'field' }, [el('label', {}, 'Q'), filtQ]),
    ]),
    el('h3', {}, 'Compressor'),
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', {}, 'Gain (dB)'), compGain]),
      el('div', { class: 'field' }, [el('label', {}, 'Threshold (dB)'), compThresh]),
      el('div', { class: 'field' }, [el('label', {}, 'Ratio (1:x)'), compRatio]),
    ]),
    el('h3', {}, 'Timing'),
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', {}, 'Attack (ms)'), timeAttack]),
      el('div', { class: 'field' }, [el('label', {}, 'Release (ms)'), timeRelease]),
    ]),
  ]);

  const sync = (state) => {
    const d = state.channels[ch].deq[band];
    const enabled = d.filt.type !== 'OFF';
    if (document.activeElement !== enableToggle) enableToggle.checked = enabled;
    bandEl.classList.toggle('disabled', !enabled);
    if (enabled && document.activeElement !== filtType) filtType.value = d.filt.type;
    if (document.activeElement !== filtFreq) filtFreq.value = d.filt.freq.toFixed(0);
    if (document.activeElement !== filtQ) filtQ.value = d.filt.q.toFixed(2);
    if (document.activeElement !== compGain) compGain.value = d.comp.gain.toFixed(1);
    if (document.activeElement !== compThresh) compThresh.value = d.comp.threshold.toFixed(1);
    if (document.activeElement !== compRatio) compRatio.value = d.comp.ratio.toFixed(1);
    if (document.activeElement !== timeAttack) timeAttack.value = d.time.attack.toFixed(1);
    if (document.activeElement !== timeRelease) timeRelease.value = d.time.release.toFixed(1);

    chart.setMarkers([{ label: band, freq: d.filt.freq || 20, db: 0, disabled: !enabled }]);
  };

  return { el: bandEl, sync };
}

function channelCard(ch, ctx) {
  const bands = DEQ_BANDS.map((b) => deqBand(ch, b, ctx));
  const card = el('div', { class: 'card' }, [el('h2', {}, `Channel ${ch === 1 ? 'A' : 'B'}`), ...bands.map((b) => b.el)]);
  const sync = (state) => bands.forEach((b) => b.sync(state));
  return { card, sync };
}

export function mountDeq(container, ctx) {
  const cards = CHANNELS.map((ch) => channelCard(ch, ctx));
  container.append(el('div', { class: 'grid-2' }, cards.map((c) => c.card)));
  ctx.store.subscribe((state) => cards.forEach((c) => c.sync(state)));
}
