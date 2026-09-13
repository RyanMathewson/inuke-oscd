import { el } from '../utils.js';
import { CHANNELS, XOVER_FAMILIES, XOVER_FAMILY_LABELS, XOVER_SLOPES } from '../constants.js';
import { channelPatch } from '../state.js';
import { createEqChart } from './eq-chart.js';
import { xoverCurveDb } from '../curve-math.js';

function parseXoverType(type) {
  if (!type || type === 'OFF') return { family: 'OFF', slope: 12 };
  const m = /^([A-Z]+)(\d+)$/.exec(type);
  if (!m) return { family: 'OFF', slope: 12 };
  return { family: m[1], slope: parseInt(m[2], 10) };
}

function filterControl(label, ch, kind, { store, protocol, log }) {
  const familySelect = el('select', {}, [
    el('option', { value: 'OFF' }, 'Off'),
    ...XOVER_FAMILIES.map((f) => el('option', { value: f }, XOVER_FAMILY_LABELS[f])),
  ]);
  const slopeSelect = el(
    'select',
    {},
    XOVER_SLOPES.map((s) => el('option', { value: String(s) }, `${s} dB/oct`)),
  );
  const freqInput = el('input', { type: 'number', step: '1', min: '0' });

  const setter = kind === 'hp' ? protocol.setXoverHp.bind(protocol) : protocol.setXoverLp.bind(protocol);

  async function commit() {
    const family = familySelect.value;
    const type = family === 'OFF' ? 'OFF' : `${family}${slopeSelect.value}`;
    const freq = parseFloat(freqInput.value) || 0;
    slopeSelect.disabled = family === 'OFF';
    try {
      await setter(ch, type, freq);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, xover: { ...c.xover, [kind]: { type, freq } } })));
      log(`Ch${ch} ${kind.toUpperCase()} -> ${type} @ ${freq}Hz`);
    } catch (err) {
      log(`Ch${ch} ${kind} set failed: ${err.message}`, true);
    }
  }
  familySelect.addEventListener('change', commit);
  slopeSelect.addEventListener('change', commit);
  freqInput.addEventListener('change', commit);

  const row = el('div', { class: 'field' }, [
    el('label', {}, label),
    el('div', { class: 'field-row' }, [familySelect, slopeSelect, freqInput, el('span', { class: 'note' }, 'Hz')]),
  ]);

  const sync = (state) => {
    const data = kind === 'hp' ? state.channels[ch].xover.hp : state.channels[ch].xover.lp;
    const { family, slope } = parseXoverType(data.type);
    if (document.activeElement !== familySelect) familySelect.value = family;
    if (document.activeElement !== slopeSelect) slopeSelect.value = String(slope);
    slopeSelect.disabled = family === 'OFF';
    if (document.activeElement !== freqInput) freqInput.value = data.freq.toFixed(0);
  };

  return { row, sync };
}

function channelCard(ch, ctx) {
  const hp = filterControl('High Pass', ch, 'hp', ctx);
  const lp = filterControl('Low Pass', ch, 'lp', ctx);
  const gainInput = el('input', { type: 'number', step: '0.1' });
  gainInput.addEventListener('change', async () => {
    const gainDb = parseFloat(gainInput.value) || 0;
    try {
      await ctx.protocol.setXoverGain(ch, gainDb);
      ctx.store.set((s) => channelPatch(s, ch, (c) => ({ ...c, xover: { ...c.xover, gain: gainDb } })));
      ctx.log(`Ch${ch} xover gain -> ${gainDb}dB`);
    } catch (err) {
      ctx.log(`Ch${ch} setXoverGain failed: ${err.message}`, true);
    }
  });

  const chart = createEqChart({ dbMin: -30, dbMax: 15, dbStep: 15 });

  const card = el('div', { class: 'card' }, [
    el('h2', {}, `Channel ${ch === 1 ? 'A' : 'B'}`),
    el('div', { class: 'chart-wrap' }, [
      chart.svg,
      chart.labelsEl,
      el('p', { class: 'note' }, 'Combined HP+LP roll-off shape. Approximate -- see curve-math.js.'),
    ]),
    hp.row,
    lp.row,
    el('div', { class: 'field' }, [el('label', {}, 'Crossover Gain (dB)'), gainInput]),
  ]);

  const sync = (state) => {
    hp.sync(state);
    lp.sync(state);
    if (document.activeElement !== gainInput) gainInput.value = state.channels[ch].xover.gain.toFixed(1);

    const { hp: hpState, lp: lpState, gain } = state.channels[ch].xover;
    const curveFn = (f) => xoverCurveDb(hpState, lpState, gain, f);
    chart.setCurve(curveFn);
    const markers = [];
    if (hpState.type !== 'OFF') markers.push({ label: 'HP', freq: hpState.freq || 20, db: curveFn(hpState.freq || 20) });
    if (lpState.type !== 'OFF') markers.push({ label: 'LP', freq: lpState.freq || 20000, db: curveFn(lpState.freq || 20000) });
    chart.setMarkers(markers);
  };

  return { card, sync };
}

export function mountCrossover(container, ctx) {
  const cards = CHANNELS.map((ch) => channelCard(ch, ctx));
  container.append(el('div', { class: 'grid-2' }, cards.map((c) => c.card)));
  ctx.store.subscribe((state) => cards.forEach((c) => c.sync(state)));
}
