"""Minimal direct client for the iNuke DSP USB/HID/OSC protocol.

See docs/PROTOCOL_NOTES.md for the full protocol writeup. Summary:
  - Device: VID 0x1397, PID 0x1101 (vendor-defined HID)
  - Host->device: HID SET_REPORT control transfer, ReportID 0, 63-byte report
  - Device->host: HID Input report on endpoint 0x81, 63-byte report
  - Report payload: 1-byte length N, then N bytes of a binary OSC 1.0 message,
    then don't-care padding.
  - A "GET" is the bare address with an empty ("," only) type tag string;
    the device replies on the same address with real args.

This module is read-mostly right now: it can open the device, send a raw OSC
message, and read+decode replies. Treat SETs as live amp commands -- only
send ones you understand.
"""
import hid
import struct
import time

VID = 0x1397
PID = 0x1101
REPORT_LEN = 63


def osc_encode(address, typetags, args):
    def pad4(b):
        pad = (4 - len(b) % 4) % 4
        if pad == 0:
            pad = 4  # OSC always NUL-terminates, even if already aligned
        return b + b'\x00' * pad

    out = pad4(address.encode('ascii'))
    tt_bytes = (',' + typetags).encode('ascii')
    out += pad4(tt_bytes)
    for t, a in zip(typetags, args):
        if t == 'f':
            out += struct.pack('>f', a)
        elif t == 'i':
            out += struct.pack('>i', a)
        elif t == 's':
            out += pad4(a.encode('ascii'))
        else:
            raise ValueError(f'unsupported typetag {t}')
    return out


def osc_decode(msg):
    end = msg.find(b'\x00')
    if end == -1 or msg[0:1] != b'/':
        return None
    addr = msg[:end].decode('ascii', 'replace')
    pos = ((end + 4) // 4) * 4
    if pos >= len(msg) or msg[pos:pos+1] != b',':
        return {'addr': addr, 'raw_tail': msg[pos:].hex()}
    tend = msg.find(b'\x00', pos)
    typetags = msg[pos+1:tend].decode('ascii', 'replace')
    pos = ((tend + 4) // 4) * 4
    args = []
    for t in typetags:
        if t in 'fi':
            val = struct.unpack('>f' if t == 'f' else '>i', msg[pos:pos+4])[0]
            args.append(val)
            pos += 4
        elif t == 's':
            send = msg.find(b'\x00', pos)
            if send == -1:
                send = len(msg)
            args.append(msg[pos:send].decode('ascii', 'replace'))
            pos = ((send + 4) // 4) * 4
        else:
            args.append(f'?{t}?')
    return {'addr': addr, 'typetags': typetags, 'args': args}


class INukeDevice:
    def __init__(self):
        self.dev = hid.device()
        self.dev.open(VID, PID)
        self.dev.set_nonblocking(True)

    def close(self):
        self.dev.close()

    def send(self, address, typetags='', args=()):
        msg = osc_encode(address, typetags, args)
        if len(msg) > REPORT_LEN - 1:
            raise ValueError('message too long for one report (no chunking implemented)')
        report = bytes([len(msg)]) + msg
        report = report.ljust(REPORT_LEN, b'\x00')
        # report ID 0 is not used by this device; hidapi send_feature/write
        # expects the report ID as report[0] for write() on some platforms,
        # but this device's HID SET_REPORT uses ReportID 0 explicitly, so we
        # prepend a 0x00 report-id byte for hidapi's write() call.
        self.dev.write(b'\x00' + report)

    def poll(self, timeout_s=2.0):
        """Read Input reports for up to timeout_s, yielding decoded OSC messages."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            data = self.dev.read(REPORT_LEN, timeout_ms=100)
            if not data:
                continue
            data = bytes(data)
            n = data[0]
            msg = data[1:1+n]
            decoded = osc_decode(msg)
            if decoded:
                yield decoded


if __name__ == '__main__':
    d = INukeDevice()
    try:
        print('Querying /gain ...')
        d.send('/gain')
        for msg in d.poll(timeout_s=3.0):
            print(msg)
            if msg['addr'] == '/gain':
                break
    finally:
        d.close()
