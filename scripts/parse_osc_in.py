"""Decode device->host OSC/HID Input reports (endpoint 0x81) from a USBPcap capture.

Usage:
    "C:\\Program Files\\Wireshark\\tshark.exe" -r capture.pcap \\
        -Y "usb.endpoint_address==0x81 && usb.data_len>0" -x > out_hex.txt
    python parse_osc_in.py out_hex.txt

Unlike parse_osc.py (host->device, anchored on the SET_REPORT SETUP packet),
interrupt IN transfers have no SETUP packet, so this just scans each frame's
raw bytes for a length-prefix byte immediately followed by '/' and decodes
the OSC message that follows, per docs/PROTOCOL_NOTES.md.
"""
import re, sys, struct

path = sys.argv[1]
text = open(path, encoding='utf-8', errors='replace').read()
blocks = re.split(r'\n\s*\n', text.strip())

def parse_hexblock(block):
    data = bytearray()
    for line in block.splitlines():
        m = re.match(r'^[0-9a-fA-F]{4,8}\s+((?:[0-9a-fA-F]{2}\s+){1,16})', line)
        if not m:
            continue
        hexpart = m.group(1).split()
        data.extend(int(h, 16) for h in hexpart)
    return bytes(data)

def osc_decode(msg):
    if len(msg) < 4:
        return None
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
            if pos+4 > len(msg):
                args.append('<short>'); break
            val = struct.unpack('>f' if t == 'f' else '>i', msg[pos:pos+4])[0]
            args.append(val); pos += 4
        elif t == 's':
            send = msg.find(b'\x00', pos)
            if send == -1: send = len(msg)
            s = msg[pos:send].decode('ascii', 'replace')
            args.append(s); pos = ((send + 4) // 4) * 4
        else:
            args.append(f'?{t}?')
    return {'addr': addr, 'typetags': typetags, 'args': args}

count = 0
shown = 0
for block in blocks:
    raw = parse_hexblock(block)
    if not raw:
        continue
    # find length-prefix byte immediately followed by '/' (0x2f)
    idx = raw.find(b'/')
    if idx == -1 or idx == 0:
        continue
    n = raw[idx-1]
    msg = raw[idx-1+1: idx-1+1+n]
    decoded = osc_decode(msg)
    if decoded:
        count += 1
        if shown < 15 or count % 20 == 0:
            print(f"[{count}] len={n} -> {decoded}")
            shown += 1

print(f"\ntotal decoded IN meter/report messages: {count}")
