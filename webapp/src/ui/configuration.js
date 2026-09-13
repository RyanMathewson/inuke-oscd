import { el } from '../utils.js';
import { CHANNELS } from '../constants.js';
import { channelPatch } from '../state.js';

function channelCard(ch, { store, protocol, log }) {
  const delayTime = el('input', { type: 'number', step: '0.1', min: '0' });
  const phaseSelect = el('select', {}, [el('option', { value: '0' }, '0°'), el('option', { value: '180' }, '180°')]);
  const thresh = el('input', { type: 'number', step: '0.1' });
  const release = el('input', { type: 'number', step: '0.1', min: '0' });
  const hold = el('input', { type: 'number', step: '0.1', min: '0' });

  async function commitDelay() {
    const timeMs = parseFloat(delayTime.value) || 0;
    const phaseDeg = parseInt(phaseSelect.value, 10);
    try {
      await protocol.setDelay(ch, timeMs, phaseDeg);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, delay: { timeMs, phaseDeg } })));
      log(`Ch${ch} delay -> ${timeMs}ms @ ${phaseDeg}°`);
    } catch (err) {
      log(`Ch${ch} setDelay failed: ${err.message}`, true);
    }
  }
  async function commitLimiter() {
    const thresholdVp = parseFloat(thresh.value) || 0;
    const releaseMs = parseFloat(release.value) || 0;
    const holdMs = parseFloat(hold.value) || 0;
    try {
      await protocol.setLimiter(ch, thresholdVp, releaseMs, holdMs);
      store.set((s) => channelPatch(s, ch, (c) => ({ ...c, limiter: { thresholdVp, releaseMs, holdMs } })));
      log(`Ch${ch} limiter -> thr=${thresholdVp}Vp rel=${releaseMs}ms hold=${holdMs}ms`);
    } catch (err) {
      log(`Ch${ch} setLimiter failed: ${err.message}`, true);
    }
  }

  delayTime.addEventListener('change', commitDelay);
  phaseSelect.addEventListener('change', commitDelay);
  thresh.addEventListener('change', commitLimiter);
  release.addEventListener('change', commitLimiter);
  hold.addEventListener('change', commitLimiter);

  const card = el('div', { class: 'card' }, [
    el('h2', {}, `Channel ${ch === 1 ? 'A' : 'B'}`),
    el('h3', {}, 'Delay / Phase'),
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', {}, 'Delay (ms)'), delayTime]),
      el('div', { class: 'field' }, [el('label', {}, 'Phase'), phaseSelect]),
    ]),
    el('h3', {}, 'Limiter'),
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', {}, 'Threshold (V peak)'), thresh]),
      el('div', { class: 'field' }, [el('label', {}, 'Release (ms)'), release]),
      el('div', { class: 'field' }, [el('label', {}, 'Hold (ms)'), hold]),
    ]),
    el('p', { class: 'note' }, 'Threshold is peak volts on the wire, not dBFS -- the vendor app\'s dBFS readout is a locally-computed display whose exact scale was never reverse-engineered, so it isn\'t reproduced here (see PROTOCOL_NOTES.md).'),
  ]);

  const sync = (state) => {
    const c = state.channels[ch];
    if (document.activeElement !== delayTime) delayTime.value = c.delay.timeMs.toFixed(1);
    if (document.activeElement !== phaseSelect) phaseSelect.value = String(c.delay.phaseDeg);
    if (document.activeElement !== thresh) thresh.value = c.limiter.thresholdVp.toFixed(1);
    if (document.activeElement !== release) release.value = c.limiter.releaseMs.toFixed(1);
    if (document.activeElement !== hold) hold.value = c.limiter.holdMs.toFixed(1);
  };

  return { card, sync };
}

export function mountConfiguration(container, ctx) {
  const cards = CHANNELS.map((ch) => channelCard(ch, ctx));
  container.append(el('div', { class: 'grid-2' }, cards.map((c) => c.card)));
  ctx.store.subscribe((state) => cards.forEach((c) => c.sync(state)));
}
