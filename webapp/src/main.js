import { INukeProtocol } from './protocol.js';
import { createStore, initialState } from './state.js';
import { applyMessageToState } from './sync.js';
import { mountSetup } from './ui/setup.js';
import { mountFile } from './ui/file.js';
import { mountConfiguration } from './ui/configuration.js';
import { mountCrossover } from './ui/crossover.js';
import { mountPeq } from './ui/peq.js';
import { mountDeq } from './ui/deq.js';
import { mountMeters } from './ui/meters.js';

const store = createStore(initialState());
const protocol = new INukeProtocol();

const logEl = document.getElementById('log');
const MAX_LOG_LINES = 200;
function log(message, isError = false) {
  const line = document.createElement('div');
  if (isError) line.className = 'error';
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${message}`;
  logEl.appendChild(line);
  while (logEl.childElementCount > MAX_LOG_LINES) logEl.removeChild(logEl.firstChild);
  logEl.scrollTop = logEl.scrollHeight;
  if (isError) console.error(message);
}

const ctx = { store, protocol, log };

// --- unsupported-browser banner ---
if (!INukeProtocol.isSupported()) {
  document.getElementById('unsupportedBanner').hidden = false;
  store.set({ supported: false });
}

// --- mount UI ---
mountSetup(document.getElementById('panel-setup'), ctx);
mountFile(document.getElementById('panel-setup'), ctx);
mountConfiguration(document.getElementById('panel-configuration'), ctx);
mountCrossover(document.getElementById('panel-crossover'), ctx);
mountPeq(document.getElementById('panel-peq'), ctx);
mountDeq(document.getElementById('panel-deq'), ctx);
mountMeters(document.getElementById('meterbar'), ctx);

// --- tabs ---
const tabButtons = [...document.querySelectorAll('.tab')];
const panels = Object.fromEntries([...document.querySelectorAll('.panel')].map((p) => [p.id, p]));
tabButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    tabButtons.forEach((b) => b.classList.toggle('active', b === btn));
    Object.values(panels).forEach((p) => p.classList.remove('active'));
    panels[`panel-${btn.dataset.tab}`].classList.add('active');
  });
});

// --- connection state -> global message listener ---
protocol.onMessage(null, (msg) => applyMessageToState(store, msg));

// --- connect / disconnect / resync UI ---
const connStatus = document.getElementById('connStatus');
const btnConnect = document.getElementById('btnConnect');
const btnDisconnect = document.getElementById('btnDisconnect');
const btnResync = document.getElementById('btnResync');

function setStatus(cls, text) {
  connStatus.className = `status status-${cls}`;
  connStatus.textContent = text;
}

async function runFullSync() {
  store.set({ syncProgress: { done: 0, total: 1, key: 'starting' } });
  try {
    await protocol.fullSync((done, total, key) => store.set({ syncProgress: { done, total, key } }));
    log('Full sync complete.');
  } catch (err) {
    log(`Sync error: ${err.message}`, true);
  } finally {
    store.set({ syncProgress: null });
  }
}

async function afterConnect() {
  store.set({ connected: true });
  setStatus('connected', 'Connected');
  btnConnect.hidden = true;
  btnDisconnect.hidden = false;
  btnResync.hidden = false;
  protocol.startMeterHeartbeat();
  log('Device connected. Starting full sync...');
  await runFullSync();
}

btnConnect.addEventListener('click', async () => {
  if (!INukeProtocol.isSupported()) {
    log('WebHID is not supported in this browser.', true);
    return;
  }
  setStatus('connecting', 'Connecting...');
  btnConnect.disabled = true;
  try {
    const ok = await protocol.connect();
    btnConnect.disabled = false;
    if (!ok) {
      setStatus('disconnected', 'Disconnected');
      log('No device selected.');
      return;
    }
    await afterConnect();
  } catch (err) {
    btnConnect.disabled = false;
    setStatus('error', 'Connection failed');
    log(`Connect failed: ${err.message}`, true);
  }
});

btnDisconnect.addEventListener('click', async () => {
  await protocol.disconnect();
  store.set({ connected: false, syncProgress: null });
  setStatus('disconnected', 'Disconnected');
  btnConnect.hidden = false;
  btnDisconnect.hidden = true;
  btnResync.hidden = true;
  log('Disconnected.');
});

btnResync.addEventListener('click', () => {
  if (!store.get().connected) return;
  log('Re-syncing...');
  runFullSync();
});

protocol.addEventListener('disconnected', () => {
  store.set({ connected: false, syncProgress: null });
  setStatus('disconnected', 'Disconnected (device unplugged or closed)');
  btnConnect.hidden = false;
  btnDisconnect.hidden = true;
  btnResync.hidden = true;
  log('Device disconnected.', true);
});

// --- detect a physical unplug (distinct from the user clicking Disconnect) ---
if (INukeProtocol.isSupported()) {
  navigator.hid.addEventListener('disconnect', (e) => {
    if (protocol.transport.device && e.device === protocol.transport.device) {
      protocol.disconnect();
    }
  });
}

// --- try to silently resume a previously authorized device on load ---
(async () => {
  if (!INukeProtocol.isSupported()) return;
  try {
    const ok = await protocol.reconnectKnownDevice();
    if (ok) {
      log('Resumed previously authorized device.');
      await afterConnect();
    }
  } catch (err) {
    log(`Auto-reconnect failed: ${err.message}`, true);
  }
})();
