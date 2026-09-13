import { el, clampNum } from '../utils.js';
import { CHANNELS, PEQ_BANDS, PEQ_TYPES, BOUNDS } from '../constants.js';
import { channelPatch } from '../state.js';
import { createEqChart } from './eq-chart.js';
import { peqCurveDb } from '../curve-math.js';
import { confirmDialog } from './dialog.js';

function peqBand(ch, band, { store, protocol, log }) {
  const enableToggle = el('input', { type: 'checkbox', class: 'toggle' });
  const typeSelect = el('select', {}, PEQ_TYPES.map((t) => el('option', { value: t }, t)));
  const freqInput = el('input', { type: 'number', step: '1', min: BOUNDS.freqHz.min, max: BOUNDS.freqHz.max });
  const gainInput = el('input', { type: 'number', step: '0.1', min: BOUNDS.gainDb.min, max: BOUNDS.gainDb.max });
  const qInput = el('input', { type: 'number', step: '0.01', min: BOUNDS.q.min, max: BOUNDS.q.max });

  async function commit() {
    const type = enableToggle.checked ? typeSelect.value : 'OFF';
    const freq = clampNum(freqInput.value, BOUNDS.freqHz, 40);
    const gain = clampNum(gainInput.value, BOUNDS.gainDb, 0);
    const q = clampNum(qInput.value, BOUNDS.q, 1);
    freqInput.value = freq;
    gainInput.value = gain;
    qInput.value = q;
    try {
      await protocol.setPeq(ch, band, type, freq, gain, q);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, peq: { ...c.peq, [band]: { type, freq, gain, q } } })));
      log(`Ch${ch} PEQ${band} -> ${type} ${freq}Hz ${gain}dB Q${q}`);
    } catch (err) {
      log(`Ch${ch} PEQ${band} set failed: ${err.message}`, true);
    }
  }
  [enableToggle, typeSelect, freqInput, gainInput, qInput].forEach((n) => n.addEventListener('change', commit));

  const bandEl = el('div', { class: 'band-col' }, [
    el('div', { class: 'band-col-header' }, [el('strong', {}, band), enableToggle]),
    el('div', { class: 'field' }, [el('label', {}, 'Type'), typeSelect]),
    el('div', { class: 'field' }, [el('label', {}, 'Freq'), freqInput]),
    el('div', { class: 'field' }, [el('label', {}, 'Gain'), gainInput]),
    el('div', { class: 'field' }, [el('label', {}, 'Q'), qInput]),
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

function channelLabel(ch) {
  return ch === 1 ? 'A' : 'B';
}

function channelCard(ch, ctx) {
  const { store, protocol, log } = ctx;
  const otherCh = ch === 1 ? 2 : 1;
  const bands = PEQ_BANDS.map((b) => peqBand(ch, b, ctx));
  const chart = createEqChart({ dbMin: -15, dbMax: 15, dbStep: 5 });

  const resetBtn = el(
    'button',
    {
      onclick: async () => {
        if (!(await confirmDialog(`Reset all 8 PEQ bands on Channel ${channelLabel(ch)} to off/flat?`))) return;
        const current = store.get().channels[ch].peq;
        for (const b of PEQ_BANDS) {
          const p = current[b];
          try {
            await protocol.setPeq(ch, b, 'OFF', p.freq, 0, p.q);
            store.set((s) => channelPatch(s, ch, (c) => ({ ...c, peq: { ...c.peq, [b]: { ...c.peq[b], type: 'OFF', gain: 0 } } })));
          } catch (err) {
            log(`Ch${ch} PEQ${b} reset failed: ${err.message}`, true);
          }
        }
        log(`Ch${ch} PEQ reset (all bands off, gain 0)`);
      },
    },
    'Reset',
  );

  const copyBtn = el(
    'button',
    {
      onclick: async () => {
        if (!(await confirmDialog(`Copy Channel ${channelLabel(ch)}'s PEQ settings onto Channel ${channelLabel(otherCh)}? This overwrites Channel ${channelLabel(otherCh)}'s current PEQ.`))) return;
        const source = store.get().channels[ch].peq;
        for (const b of PEQ_BANDS) {
          const p = source[b];
          try {
            await protocol.setPeq(otherCh, b, p.type, p.freq, p.gain, p.q);
            store.set((s) => channelPatch(s, otherCh, (c) => ({ ...c, peq: { ...c.peq, [b]: { ...p } } })));
          } catch (err) {
            log(`Ch${otherCh} PEQ${b} copy failed: ${err.message}`, true);
          }
        }
        log(`Copied Channel ${channelLabel(ch)} PEQ -> Channel ${channelLabel(otherCh)}`);
      },
    },
    `Copy to ${channelLabel(otherCh)}`,
  );

  const card = el('div', { class: 'card' }, [
    el('div', { class: 'band-header' }, [el('h2', { style: 'margin:0' }, `Channel ${channelLabel(ch)}`), el('div', { class: 'field-row' }, [resetBtn, copyBtn])]),
    el('div', { class: 'chart-wrap' }, [
      chart.svg,
      chart.labelsEl,
      el('p', { class: 'note' }, 'Combined response of all 8 bands. Approximate -- see curve-math.js for what this curve does and doesn\'t model.'),
    ]),
    el('div', { class: 'peq-bands' }, bands.map((b) => b.el)),
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
  container.append(...cards.map((c) => c.card));
  ctx.store.subscribe((state) => cards.forEach((c) => c.sync(state)));
}
