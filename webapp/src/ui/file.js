// Save/load the amp's full live state as a vendor-compatible `.arp` preset
// file -- the browser equivalent of the legacy app's File > Save/Load
// Preset menu. See webapp/src/arp.js for the text codec.
import { el } from '../utils.js';
import { CHANNELS, PEQ_BANDS, DEQ_BANDS } from '../constants.js';
import { formatArp, parseArp, ArpFormatError } from '../arp.js';
import { confirmDialog } from './dialog.js';

function sanitizeFilename(name) {
  const trimmed = (name || '').trim().replace(/[\\/:*?"<>|]/g, '_');
  return trimmed || 'inuke-preset';
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function pushStateToDevice(protocol, store, parsed) {
  const steps = [['ampmode', () => protocol.setAmpMode(parsed.ampMode)]];
  for (const ch of CHANNELS) {
    const c = parsed.channels[ch];
    for (const band of PEQ_BANDS) {
      const p = c.peq[band];
      steps.push([`peq${ch}.${band}`, () => protocol.setPeq(ch, band, p.type, p.freq, p.gain, p.q)]);
    }
    steps.push([`xoverHp${ch}`, () => protocol.setXoverHp(ch, c.xover.hp.type, c.xover.hp.freq)]);
    steps.push([`xoverLp${ch}`, () => protocol.setXoverLp(ch, c.xover.lp.type, c.xover.lp.freq)]);
    steps.push([`xoverGain${ch}`, () => protocol.setXoverGain(ch, c.xover.gain)]);
    for (const band of DEQ_BANDS) {
      const d = c.deq[band];
      steps.push([`deqComp${ch}.${band}`, () => protocol.setDeqComp(ch, band, d.comp.gain, d.comp.threshold, d.comp.ratio)]);
      steps.push([`deqTime${ch}.${band}`, () => protocol.setDeqTime(ch, band, d.time.attack, d.time.release)]);
      steps.push([`deqFilt${ch}.${band}`, () => protocol.setDeqFilt(ch, band, d.filt.type, d.filt.freq, d.filt.q)]);
    }
    steps.push([`delay${ch}`, () => protocol.setDelay(ch, c.delay.timeMs, c.delay.phaseDeg)]);
    steps.push([`limiter${ch}`, () => protocol.setLimiter(ch, c.limiter.thresholdVp, c.limiter.releaseMs, c.limiter.holdMs)]);
  }

  const total = steps.length;
  for (let i = 0; i < total; i++) {
    const [key, fn] = steps[i];
    await fn();
    store.set({ syncProgress: { done: i + 1, total, key } });
  }
  store.set({ ampMode: parsed.ampMode, channels: parsed.channels, syncProgress: null });
}

export function mountFile(container, { store, protocol, log }) {
  const fileInput = el('input', {
    type: 'file',
    accept: '.arp',
    hidden: true,
    onchange: async () => {
      const file = fileInput.files[0];
      fileInput.value = '';
      if (!file) return;
      let parsed;
      try {
        parsed = parseArp(await file.text());
      } catch (err) {
        if (err instanceof ArpFormatError) log(`Load failed: ${err.message}`, true);
        else log(`Load failed: could not read ${file.name}: ${err.message}`, true);
        return;
      }
      if (!(await confirmDialog(`Load "${file.name}" onto the amp? This overwrites the amp's entire live DSP state.`))) return;
      try {
        log(`Loading ${file.name}...`);
        await pushStateToDevice(protocol, store, parsed);
        log(`Loaded ${file.name}.`);
      } catch (err) {
        store.set({ syncProgress: null });
        log(`Load failed: ${err.message}`, true);
      }
    },
  });

  const saveBtn = el(
    'button',
    {
      class: 'primary',
      onclick: () => {
        const state = store.get();
        const text = formatArp(state);
        const filename = `${sanitizeFilename(state.info?.ampName || state.ampName)}.arp`;
        downloadText(filename, text);
        log(`Saved current state to ${filename}`);
      },
    },
    'Save to .arp file',
  );

  const loadBtn = el(
    'button',
    {
      onclick: () => fileInput.click(),
    },
    'Load from .arp file...',
  );

  container.append(
    el('div', { class: 'card' }, [
      el('h2', {}, 'File (.arp presets)'),
      el('div', { class: 'field-row' }, [saveBtn, loadBtn, fileInput]),
      el('p', { class: 'note' }, 'Save writes the currently synced state to a .arp file compatible with the original iNuke Remote Connect app. Load overwrites every live DSP parameter on the amp -- both channels -- with what\'s in the file.'),
    ]),
  );

  store.subscribe((state) => {
    const busy = !state.connected || !!state.syncProgress;
    saveBtn.disabled = busy;
    loadBtn.disabled = busy;
  });
}
