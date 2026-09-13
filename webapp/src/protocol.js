// Typed protocol layer over the raw OSC/HID transport. See
// docs/PROTOCOL_NOTES.md's Quick Reference for the full address table this
// implements.
import { oscEncode, oscDecode } from './osc.js';
import { HidTransport, REPORT_LEN } from './transport.js';
import { CHANNELS, PEQ_BANDS, DEQ_BANDS, PRESET_SLOT_COUNT } from './constants.js';

const DEFAULT_TIMEOUT_MS = 2000;

export class DeviceTimeoutError extends Error {}

export class INukeProtocol extends EventTarget {
  constructor() {
    super();
    this.transport = new HidTransport();
    this._replyQueue = Promise.resolve();
    this._heartbeat = null;
    this.transport.addEventListener('report', (e) => this._handleReport(e.detail));
    this.transport.addEventListener('close', () => {
      this._stopMeterHeartbeat();
      this.dispatchEvent(new Event('disconnected'));
    });
  }

  static isSupported() {
    return HidTransport.isSupported();
  }

  get isConnected() {
    return this.transport.isConnected;
  }

  async connect() {
    const device = await this.transport.requestDevice();
    return !!device;
  }

  async reconnectKnownDevice() {
    const device = await this.transport.reconnectKnownDevice();
    return !!device;
  }

  async disconnect() {
    this._stopMeterHeartbeat();
    await this.transport.disconnect();
  }

  _handleReport(data) {
    const n = data[0];
    const msg = data.subarray(1, 1 + n);
    const decoded = oscDecode(msg);
    if (!decoded) return;
    this.dispatchEvent(new CustomEvent('message', { detail: decoded }));
  }

  /** Fire-and-forget SET (or a bare trigger like /online). No reply is awaited. */
  async send(address, typetags = '', args = []) {
    const msg = oscEncode(address, typetags, args);
    if (msg.length > REPORT_LEN - 1) {
      throw new Error(`message too long for one report (${msg.length} bytes): ${address}`);
    }
    const report = new Uint8Array(1 + msg.length);
    report[0] = msg.length;
    report.set(msg, 1);
    await this.transport.sendReport(report);
  }

  /**
   * GET request/response. Replies carry only the address, not a request id,
   * so concurrent requests to the same address can't be told apart -- this
   * serializes every get() globally (mirrors the sequential sweep the
   * vendor app and scripts/verify_arp.py both use). SETs via send() are not
   * queued since no reply is expected for them.
   */
  get(address, typetags = '', args = [], timeoutMs = DEFAULT_TIMEOUT_MS) {
    const run = () => this._requestOnce(address, typetags, args, timeoutMs);
    const settled = this._replyQueue.then(run, run);
    this._replyQueue = settled.then(
      () => {},
      () => {},
    );
    return settled;
  }

  _requestOnce(address, typetags, args, timeoutMs) {
    return new Promise((resolve, reject) => {
      let done = false;
      const onMessage = (e) => {
        if (done || e.detail.addr !== address) return;
        done = true;
        this.removeEventListener('message', onMessage);
        clearTimeout(timer);
        resolve(e.detail);
      };
      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        this.removeEventListener('message', onMessage);
        reject(new DeviceTimeoutError(`no reply from ${address} within ${timeoutMs}ms`));
      }, timeoutMs);
      this.addEventListener('message', onMessage);
      this.send(address, typetags, args).catch((err) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        this.removeEventListener('message', onMessage);
        reject(err);
      });
    });
  }

  /** Subscribe to every decoded message, or only ones matching an address. Returns an unsubscribe fn. */
  onMessage(address, cb) {
    const handler = (e) => {
      if (!address || e.detail.addr === address) cb(e.detail);
    };
    this.addEventListener('message', handler);
    return () => this.removeEventListener('message', handler);
  }

  // --- session control (docs: "Critical gotchas" #3, "Open questions" #1) ---
  goOnline() {
    return this.send('/online');
  }
  goOffline() {
    return this.send('/offline');
  }

  /** Renews the device's ~10Hz /meter push, per the vendor app's ~5s cadence. */
  startMeterHeartbeat(intervalMs = 5000, rateHz = 10.0) {
    this._stopMeterHeartbeat();
    this.send('/meter', 'f', [rateHz]).catch(() => {});
    this._heartbeat = setInterval(() => {
      this.send('/meter', 'f', [rateHz]).catch(() => {});
    }, intervalMs);
  }
  _stopMeterHeartbeat() {
    if (this._heartbeat) {
      clearInterval(this._heartbeat);
      this._heartbeat = null;
    }
  }

  // --- device info / identity ---
  async getInfo() {
    const m = await this.get('/info');
    return { ampName: m.args[0], firmware: m.args[1], unknown: m.args[2] };
  }
  setAmpName(name) {
    return this.send('/ampname', 's', [name]);
  }

  // --- amp mode ---
  async getAmpMode() {
    const m = await this.get('/ampmode');
    return m.args[0];
  }
  setAmpMode(mode) {
    return this.send('/ampmode', 's', [mode]);
  }

  /** Read-only on real hardware -- see PROTOCOL_NOTES.md, /gain does not stick when SET. */
  async getGain() {
    const m = await this.get('/gain');
    return { gainA: m.args[0], gainB: m.args[1], muteA: m.args[2], muteB: m.args[3] };
  }

  // --- parametric EQ ---
  async getPeq(ch, band) {
    const m = await this.get(`/channel/${ch}/peq/${band}`);
    return { type: m.args[0], freq: m.args[1], gain: m.args[2], q: m.args[3] };
  }
  setPeq(ch, band, type, freq, gain, q) {
    return this.send(`/channel/${ch}/peq/${band}`, 'sfff', [type, freq, gain, q]);
  }

  // --- crossover ---
  async getXoverHp(ch) {
    const m = await this.get(`/channel/${ch}/xover/hp`);
    return { type: m.args[0], freq: m.args[1] };
  }
  setXoverHp(ch, type, freq) {
    return this.send(`/channel/${ch}/xover/hp`, 'sf', [type, freq]);
  }
  async getXoverLp(ch) {
    const m = await this.get(`/channel/${ch}/xover/lp`);
    return { type: m.args[0], freq: m.args[1] };
  }
  setXoverLp(ch, type, freq) {
    return this.send(`/channel/${ch}/xover/lp`, 'sf', [type, freq]);
  }
  async getXoverGain(ch) {
    const m = await this.get(`/channel/${ch}/xover/gain`);
    return m.args[0];
  }
  setXoverGain(ch, gainDb) {
    return this.send(`/channel/${ch}/xover/gain`, 'f', [gainDb]);
  }

  // --- dynamic EQ ---
  async getDeqComp(ch, band) {
    const m = await this.get(`/channel/${ch}/deq/${band}/comp`);
    return { gain: m.args[0], threshold: m.args[1], ratio: m.args[2] };
  }
  setDeqComp(ch, band, gain, threshold, ratio) {
    return this.send(`/channel/${ch}/deq/${band}/comp`, 'fff', [gain, threshold, ratio]);
  }
  async getDeqTime(ch, band) {
    const m = await this.get(`/channel/${ch}/deq/${band}/time`);
    return { attack: m.args[0], release: m.args[1] };
  }
  setDeqTime(ch, band, attack, release) {
    return this.send(`/channel/${ch}/deq/${band}/time`, 'ff', [attack, release]);
  }
  async getDeqFilt(ch, band) {
    const m = await this.get(`/channel/${ch}/deq/${band}/filt`);
    return { type: m.args[0], freq: m.args[1], q: m.args[2] };
  }
  setDeqFilt(ch, band, type, freq, q) {
    return this.send(`/channel/${ch}/deq/${band}/filt`, 'sff', [type, freq, q]);
  }

  // --- delay / phase, limiter ---
  async getDelay(ch) {
    const m = await this.get(`/channel/${ch}/delay`);
    return { timeMs: m.args[0], phaseDeg: m.args[1] };
  }
  setDelay(ch, timeMs, phaseDeg) {
    return this.send(`/channel/${ch}/delay`, 'fi', [timeMs, phaseDeg]);
  }
  async getLimiter(ch) {
    const m = await this.get(`/channel/${ch}/limiter`);
    return { thresholdVp: m.args[0], releaseMs: m.args[1], holdMs: m.args[2] };
  }
  setLimiter(ch, thresholdVp, releaseMs, holdMs) {
    return this.send(`/channel/${ch}/limiter`, 'fff', [thresholdVp, releaseMs, holdMs]);
  }

  // --- presets ---
  async getPresetName(slot) {
    const m = await this.get('/preset/name', 'iis', [slot, 0, 'DUMMY']);
    return { slot: m.args[0], modeEnum: m.args[1], name: m.args[2] };
  }
  savePreset(slot, ampModeEnum, name) {
    return this.send('/preset/save', 'iis', [slot, ampModeEnum, name]);
  }
  loadPreset(slot, name) {
    return this.send('/preset/load', 'iis', [slot, 0, name]);
  }

  /**
   * Full GET-all sweep matching the vendor app's connect handshake (see
   * PROTOCOL_NOTES.md "CONFIRMED: GET/SET symmetry, and the connect
   * handshake"). Calls onProgress(done, total, key) after each step.
   */
  async fullSync(onProgress) {
    const steps = [];
    steps.push(['/info', () => this.getInfo()]);
    steps.push(['/online', () => this.goOnline()]);
    steps.push(['/gain', () => this.getGain()]);
    steps.push(['/ampmode', () => this.getAmpMode()]);
    for (const ch of CHANNELS) {
      for (const b of PEQ_BANDS) steps.push([`peq${ch}.${b}`, () => this.getPeq(ch, b)]);
      steps.push([`xoverHp${ch}`, () => this.getXoverHp(ch)]);
      steps.push([`xoverLp${ch}`, () => this.getXoverLp(ch)]);
      steps.push([`xoverGain${ch}`, () => this.getXoverGain(ch)]);
      for (const b of DEQ_BANDS) {
        steps.push([`deqComp${ch}.${b}`, () => this.getDeqComp(ch, b)]);
        steps.push([`deqTime${ch}.${b}`, () => this.getDeqTime(ch, b)]);
        steps.push([`deqFilt${ch}.${b}`, () => this.getDeqFilt(ch, b)]);
      }
      steps.push([`delay${ch}`, () => this.getDelay(ch)]);
      steps.push([`limiter${ch}`, () => this.getLimiter(ch)]);
    }
    for (let slot = 1; slot <= PRESET_SLOT_COUNT; slot++) {
      steps.push([`preset${slot}`, () => this.getPresetName(slot)]);
    }

    const results = {};
    let i = 0;
    for (const [key, fn] of steps) {
      i++;
      try {
        results[key] = await fn();
      } catch (err) {
        results[key] = { error: String(err) };
      }
      if (onProgress) onProgress(i, steps.length, key);
    }
    return results;
  }
}
