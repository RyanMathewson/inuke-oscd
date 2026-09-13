"""Verify a .arp preset file's values against the amp's actual live state.

Usage: python verify_arp.py

Parses a .arp save file (plain-text OSC dump, see docs/PROTOCOL_NOTES.md),
queries the amp directly for the current value at each address, and reports
any mismatches. Handles the .arp file's "4k00"-style frequency shorthand
(NkNN -> N.NN * 1000).
"""
import sys, re, time
sys.path.insert(0, r'C:\temp\inuke\scripts')
from inuke_client import INukeDevice

def parse_freq(s):
    if 'k' in s:
        l, r = s.split('k', 1)
        return float(f'{l}.{r}') * 1000.0
    return float(s)

def parse_arp(path):
    lines = open(path, encoding='ascii', errors='replace').read().splitlines()
    out = []
    for line in lines:
        line = line.strip()
        if not line or line in ('BEGIN_OSC_DATA', 'END_OSC_DATA'):
            continue
        parts = line.split()
        addr = parts[0]
        typetags = parts[1]
        raw_args = parts[2:]
        args = []
        ai = 0
        for t in typetags:
            if t == 's':
                args.append(raw_args[ai])
            elif t == 'f':
                args.append(parse_freq(raw_args[ai]))
            elif t == 'i':
                args.append(int(raw_args[ai]))
            ai += 1
        out.append((addr, typetags, args))
    return out

entries = parse_arp(r'C:\temp\inuke\existing_settings.arp')
print(f'Parsed {len(entries)} entries from existing_settings.arp')

d = INukeDevice()
mismatches = []
matches = 0
try:
    for addr, typetags, args in entries:
        d.send(addr)
        got = None
        for msg in d.poll(timeout_s=1.5):
            if msg['addr'] == addr:
                got = msg
                break
        if got is None:
            mismatches.append((addr, 'NO REPLY', args, None))
            continue
        ok = True
        if got['typetags'] != typetags:
            ok = False
        else:
            for a, b in zip(args, got['args']):
                if isinstance(a, float):
                    if abs(a - b) > 0.5:
                        ok = False
                elif a != b:
                    ok = False
        if ok:
            matches += 1
        else:
            mismatches.append((addr, 'MISMATCH', args, got['args']))
        time.sleep(0.05)
finally:
    d.close()

print(f'\n{matches}/{len(entries)} matched the .arp file exactly (within float tolerance)')
if mismatches:
    print(f'\n{len(mismatches)} mismatches:')
    for addr, kind, expected, actual in mismatches:
        print(f'  {addr}: {kind} expected={expected} actual={actual}')
else:
    print('\nALL PARAMETERS MATCH -- the amp'"'"'s live state matches the saved preset file.')
