import { el } from '../utils.js';
import { AMP_MODES, AMP_MODE_LABELS, AMP_MODE_ENUM, AMP_MODE_BY_ENUM, PRESET_SLOT_COUNT, BOUNDS } from '../constants.js';
import { confirmDialog } from './dialog.js';

export function mountSetup(container, { store, protocol, log }) {
  const infoBody = el('div', { class: 'note' }, 'Not connected.');
  const progressWrap = el('div', { class: 'progress', hidden: true }, [el('div', { style: 'width:0%' })]);
  const progressLabel = el('div', { class: 'note', hidden: true });

  const nameInput = el('input', { type: 'text', placeholder: 'Amp name', maxlength: BOUNDS.ampNameLength });
  const modeSelect = el(
    'select',
    {
      onchange: async () => {
        const mode = modeSelect.value;
        try {
          await protocol.setAmpMode(mode);
          store.set({ ampMode: mode });
          log(`Amp mode -> ${mode}`);
        } catch (err) {
          log(`setAmpMode failed: ${err.message}`, true);
        }
      },
    },
    AMP_MODES.map((m) => el('option', { value: m }, AMP_MODE_LABELS[m])),
  );
  const gainValue = el('div', { class: 'note' }, '—');
  const lockValue = el('div', { class: 'note' }, 'unknown until /online is sent');

  const presetNameInput = el('input', { type: 'text', placeholder: 'Preset name', maxlength: BOUNDS.presetNameLength });
  const presetTbody = el('tbody');

  async function refreshPreset(slot) {
    try {
      const p = await protocol.getPresetName(slot);
      store.set((s) => ({
        presets: s.presets.map((row) => (row.slot === slot ? { slot, name: p.name, modeEnum: p.modeEnum } : row)),
      }));
    } catch (err) {
      log(`refresh preset ${slot} failed: ${err.message}`, true);
    }
  }

  const storeBtn = el(
    'button',
    {
      class: 'primary',
      onclick: async () => {
        const s = store.get();
        const slot = s.selectedPreset;
        const modeEnum = AMP_MODE_ENUM[s.ampMode] ?? 0;
        const name = presetNameInput.value || `Slot ${slot}`;
        if (!(await confirmDialog(`Store the amp's current full state to preset slot ${slot} as "${name}"? This overwrites whatever is already there.`))) return;
        try {
          await protocol.savePreset(slot, modeEnum, name);
          log(`Stored slot ${slot} as "${name}"`);
          await refreshPreset(slot);
        } catch (err) {
          log(`Store failed: ${err.message}`, true);
        }
      },
    },
    'Store to selected slot',
  );

  const recallBtn = el(
    'button',
    {
      class: 'danger',
      onclick: async () => {
        const s = store.get();
        const slot = s.selectedPreset;
        const row = s.presets.find((p) => p.slot === slot);
        if (!(await confirmDialog(`Recall preset slot ${slot} ("${row?.name ?? ''}")? This replaces every live DSP parameter on the amp right now.`))) return;
        try {
          await protocol.loadPreset(slot, row?.name ?? '');
          log(`Recalled slot ${slot}`);
        } catch (err) {
          log(`Recall failed: ${err.message}`, true);
        }
      },
    },
    'Recall selected slot',
  );

  const presetsCard = el('div', { class: 'card' }, [
    el('h2', {}, 'Amp Presets (20 onboard slots)'),
    el('table', {}, [
      el('thead', {}, el('tr', {}, [el('th', {}, ''), el('th', {}, 'Slot'), el('th', {}, 'Name'), el('th', {}, 'Mode')])),
      presetTbody,
    ]),
    el('div', { class: 'field-row', style: 'margin-top:0.6rem' }, [presetNameInput, storeBtn, recallBtn]),
    el('p', { class: 'note' }, 'Store snapshots the amp\'s entire current state (both channels) into the selected slot. Recall replaces the amp\'s entire live state with what\'s stored -- both are immediate and irreversible without a backup.'),
  ]);

  const diagCard = el('details', { class: 'advanced' }, [
    el('summary', {}, 'Diagnostics'),
    el('div', { class: 'field-row', style: 'margin-top:0.5rem' }, [
      el('button', { onclick: async () => { try { await protocol.goOnline(); log('Sent /online'); } catch (err) { log(err.message, true); } } }, 'Send /online'),
      el('button', { onclick: async () => { try { await protocol.goOffline(); log('Sent /offline (device will stop replying to GETs until /online)'); } catch (err) { log(err.message, true); } } }, 'Send /offline'),
    ]),
    el('div', { class: 'field' }, [el('label', {}, 'Lock state (only pushed by the device after /online)'), lockValue]),
    el('p', { class: 'note' }, 'If parameter reads stop returning values, try "Send /online" first -- the amp can silently stop replying to reads until it\'s told a session is starting again.'),
  ]);

  container.append(
    el('div', { class: 'card' }, [el('h2', {}, 'Device'), infoBody, progressLabel, progressWrap]),
    el('div', { class: 'card' }, [
      el('h2', {}, 'Amp Name & Mode'),
      el('div', { class: 'field' }, [
        el('label', {}, 'Amp name'),
        el('div', { class: 'field-row' }, [
          nameInput,
          el(
            'button',
            {
              onclick: async () => {
                try {
                  await protocol.setAmpName(nameInput.value);
                  store.set({ ampName: nameInput.value });
                  log(`Amp name -> "${nameInput.value}"`);
                } catch (err) {
                  log(`setAmpName failed: ${err.message}`, true);
                }
              },
            },
            'Rename',
          ),
        ]),
      ]),
      el('div', { class: 'field' }, [el('label', {}, 'Amp mode'), modeSelect]),
      el('div', { class: 'field' }, [
        el('label', {}, 'Gain (read-only)'),
        gainValue,
      ]),
    ]),
    presetsCard,
    diagCard,
  );

  function renderPresetRows(state) {
    presetTbody.replaceChildren(
      ...state.presets.map((p) => {
        const radio = el('input', {
          type: 'radio',
          name: 'presetSlot',
          checked: state.selectedPreset === p.slot,
          onchange: () => {
            store.set({ selectedPreset: p.slot });
            presetNameInput.value = p.name === 'EMPTY' ? '' : p.name;
          },
        });
        const tr = el(
          'tr',
          { class: state.selectedPreset === p.slot ? 'selected' : '' },
          [el('td', {}, radio), el('td', {}, String(p.slot)), el('td', {}, p.name), el('td', {}, AMP_MODE_BY_ENUM[p.modeEnum] ?? '?')],
        );
        return tr;
      }),
    );
  }

  store.subscribe((state) => {
    if (state.connected && state.info) {
      infoBody.textContent = `${state.info.ampName} — firmware ${state.info.firmware}`;
    } else if (state.connected) {
      infoBody.textContent = 'Connected — syncing...';
    } else {
      infoBody.textContent = 'Not connected.';
    }
    if (document.activeElement !== nameInput) nameInput.value = state.ampName || '';
    if (document.activeElement !== modeSelect) modeSelect.value = state.ampMode;
    gainValue.textContent = state.gain
      ? `A=${state.gain.gainA.toFixed(1)}dB muteA=${state.gain.muteA}  B=${state.gain.gainB.toFixed(1)}dB muteB=${state.gain.muteB}`
      : '—';
    lockValue.textContent = state.lock == null ? 'unknown until /online is sent' : state.lock ? 'LOCKED' : 'unlocked';

    if (state.syncProgress) {
      const { done, total, key } = state.syncProgress;
      progressWrap.hidden = false;
      progressLabel.hidden = false;
      progressWrap.firstChild.style.width = `${Math.round((done / total) * 100)}%`;
      progressLabel.textContent = `Syncing ${done}/${total} (${key})`;
    } else {
      progressWrap.hidden = true;
      progressLabel.hidden = true;
    }

    renderPresetRows(state);
  });
}
