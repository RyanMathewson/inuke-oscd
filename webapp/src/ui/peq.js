import { el } from '../utils.js';
import { CHANNELS, PEQ_BANDS, PEQ_TYPES } from '../constants.js';
import { channelPatch } from '../state.js';
import { createEqChart } from './eq-chart.js';
import { peqCurveDb } from '../curve-math.js';

function peqBand(ch, band, { store, protocol, log }) {
  const enableToggle = el('input', { type: 'checkbox', class: 'toggle' });
  const typeSelect = el('select', {}, PEQ_TYPES.map((t) => el('option', { value: t }, t)));
  const freqInput = el('input', { type: 'number', step: '1', min: '1' });
  const gainInput = el('input', { type: 'number', step: '0.1' });
  const qInput = el('input', { type: 'number', step: '0.01', min: '0.01' });

  async function commit() {
    const type = enableToggle.checked ? typeSelect.value : 'OFF';
    const freq = parseFloat(freqInput.value) || 0;
    const gain = parseFloat(gainInput.value) || 0;
    const q = parseFloat(qInput.value) || 0;
    try {
      await protocol.setPeq(ch, band, type, freq, gain, q);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, peq: { ...c.peq, [band]: { type, freq, gain, q } } })));
      log(`Ch${ch} PEQ${band} -> ${type} ${freq}Hz ${gain}dB Q${q}`);
    } catch (err) {
      log(`Ch${ch} PEQ${band} set failed: ${err.message}`, true);
    }
  }
  [enableToggle, typeSelect, freqInput, gainInput, qInput].forEach((n) => n.addEventListener('change', commit));

  const bandEl = el('div', { class: 'band' }, [
    el('div', { class: 'band-header' }, [el('strong', {}, `Band ${band}`), enableToggle]),
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field', style: 'flex:1.4' }, [el('label', {}, 'Type'), typeSelect]),
      el('div', { class: 'field' }, [el('label', {}, 'Freq (Hz)'), freqInput]),
      el('div', { class: 'field' }, [el('label', {}, 'Gain (dB)'), gainInput]),
      el('div', { class: 'field' }, [el('label', {}, 'Q'), qInput]),
    ]),
  ]);

  const sync = (state) => {
    const p = state.channels[ch].peq[band];
    const enabled = p.type !== 'OFF';
    if (document.activeElement !== enableToggle) enableToggle.checked = enabled;
    bandEl.classList.toggle('disabled', !enabled);
    if (enabled && document.activeElement !== typeSelect) typeSelect.value = p.type;
    if (document.activeElement !== freqInput) freqInput.value = p.freq.toFixed(0);
    if (document.activeElement !== gainInput) gainInput.value = p.gain.toFixed(1);
    if (document.activeElement !== qInput) qInput.value = p.q.toFixed(2);
  };

  return { el: bandEl, sync };
}

function channelCard(ch, ctx) {
  const bands = PEQ_BANDS.map((b) => peqBand(ch, b, ctx));
  const chart = createEqChart({ dbMin: -15, dbMax: 15, dbStep: 5 });
  const card = el('div', { class: 'card' }, [
    el('h2', {}, `Channel ${ch === 1 ? 'A' : 'B'}`),
    el('div', { class: 'chart-wrap' }, [
      chart.svg,
      chart.labelsEl,
      el('p', { class: 'note' }, 'Combined response of all 8 bands. Approximate -- see curve-math.js for what this curve does and doesn\'t model.'),
    ]),
    ...bands.map((b) => b.el),
  ]);

  const sync = (state) => {
    bands.forEach((b) => b.sync(state));
    const peqState = state.channels[ch].peq;
    const bandList = PEQ_BANDS.map((b) => peqState[b]);
    chart.setCurve((f) => peqCurveDb(bandList, f));
    chart.setMarkers(
      PEQ_BANDS.map((b) => {
        const p = peqState[b];
        const disabled = p.type === 'OFF';
        return { label: b, freq: p.freq || 20, db: disabled ? 0 : p.gain, disabled };
      }),
    );
  };

  return { card, sync };
}

export function mountPeq(container, ctx) {
  const cards = CHANNELS.map((ch) => channelCard(ch, ctx));
  container.append(el('div', { class: 'grid-2' }, cards.map((c) => c.card)));
  ctx.store.subscribe((state) => cards.forEach((c) => c.sync(state)));
}
