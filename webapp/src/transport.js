// WebHID transport for the iNuke amp's USB/HID device.
// See docs/PROTOCOL_NOTES.md "Hardware / transport" and "CONFIRMED: USB wire
// protocol": the device has no interrupt OUT endpoint, so host->device
// writes go over a HID SET_REPORT control transfer -- WebHID's
// device.sendReport() issues that control transfer automatically whenever a
// device has no Output endpoint, per the HID class spec, so no special
// handling is needed here beyond picking report ID 0 (this device declares
// no report IDs).

export const VID = 0x1397;
export const PID = 0x1101;
export const REPORT_LEN = 63;

export class HidTransport extends EventTarget {
  constructor() {
    super();
    this.device = null;
    this._onInputReport = this._onInputReport.bind(this);
  }

  static isSupported() {
    return typeof navigator !== 'undefined' && !!navigator.hid;
  }

  async requestDevice() {
    const devices = await navigator.hid.requestDevice({
      filters: [{ vendorId: VID, productId: PID }],
    });
    if (!devices.length) return null;
    return this._open(devices[0]);
  }

  async reconnectKnownDevice() {
    const devices = await navigator.hid.getDevices();
    const match = devices.find((d) => d.vendorId === VID && d.productId === PID);
    if (!match) return null;
    return this._open(match);
  }

  async _open(device) {
    if (!device.opened) await device.open();
    this.device = device;
    device.addEventListener('inputreport', this._onInputReport);
    this.dispatchEvent(new Event('open'));
    return device;
  }

  async disconnect() {
    if (this.device) {
      this.device.removeEventListener('inputreport', this._onInputReport);
      if (this.device.opened) {
        try {
          await this.device.close();
        } catch {
          // already closed (e.g. device was physically unplugged)
        }
      }
      this.device = null;
      this.dispatchEvent(new Event('close'));
    }
  }

  get isConnected() {
    return !!(this.device && this.device.opened);
  }

  get deviceInfo() {
    if (!this.device) return null;
    return { productName: this.device.productName, vendorId: this.device.vendorId, productId: this.device.productId };
  }

  async sendReport(payloadBytes) {
    if (!this.isConnected) throw new Error('device not connected');
    if (payloadBytes.length > REPORT_LEN) throw new Error('report exceeds 63 bytes');
    const report = new Uint8Array(REPORT_LEN);
    report.set(payloadBytes, 0);
    await this.device.sendReport(0, report);
  }

  _onInputReport(event) {
    const data = new Uint8Array(event.data.buffer, event.data.byteOffset, event.data.byteLength);
    this.dispatchEvent(new CustomEvent('report', { detail: data }));
  }
}
