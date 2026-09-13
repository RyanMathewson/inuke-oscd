"""Decode host->device OSC/HID SET_REPORT messages from a USBPcap capture.

Usage:
    "C:\\Program Files\\Wireshark\\tshark.exe" -r capture.pcap \\
        -Y "usb.endpoint_address==0x00 && usb.data_len>0" -x > out_hex.txt
    python parse_osc.py out_hex.txt

Finds each HID SET_REPORT control transfer (SETUP bytes starting `21 09`),
reads wLength, then the 1-byte OSC-length prefix + binary OSC message that
follows, per docs/PROTOCOL_NOTES.md. To decode device->host meter reports
instead, filter on endpoint 0x81 and skip straight to the length-prefixed
payload (no SETUP packet to locate, since those are interrupt IN transfers).
"""
import re, sys, struct

path = sys.argv[1]
text = open(path, encoding='utf-8', errors='replace').read()

# split into per-frame blocks: tshark -x with -Y prints a blank-line separated
# set of blocks, each block optionally preceded by a "Frame N:" style line is
# NOT printed by default -x; instead frames are just concatenated hex dumps
# separated by blank lines, in the same order as -Y matched them.
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
    # address
    end = msg.find(b'\x00')
    if end == -1:
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
                args.append('<short>')
                break
            val = struct.unpack('>f' if t == 'f' else '>i', msg[pos:pos+4])[0]
            args.append(val)
            pos += 4
        elif t == 's':
            send = msg.find(b'\x00', pos)
            if send == -1:
                send = len(msg)
            s = msg[pos:send].decode('ascii', 'replace')
            args.append(s)
            pos = ((send + 4) // 4) * 4
        else:
            args.append(f'?{t}?')
    return {'addr': addr, 'typetags': typetags, 'args': args}

results = []
for block in blocks:
    raw = parse_hexblock(block)
    if not raw:
        continue
    # find the SETUP packet pattern: 21 09 xx xx xx xx LL 00  (SET_REPORT, wLength LL)
    idx = raw.find(b'\x21\x09')
    if idx == -1:
        continue
    setup = raw[idx:idx+8]
    wlength = setup[6] | (setup[7] << 8)
    data = raw[idx+8: idx+8+wlength]
    if not data:
        continue
    n = data[0]
    msg = data[1:1+n]
    decoded = osc_decode(msg)
    results.append((wlength, n, decoded))

for i, (wlength, n, decoded) in enumerate(results):
    print(f"[{i}] wLength={wlength} osclen={n} -> {decoded}")
