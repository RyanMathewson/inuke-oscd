"""Poll live /meter telemetry from the amp for a few seconds and summarize.

Usage: python poll_meter.py

Confirms /meter ,ffff = [input_A, input_B, output_A, output_B], linear
amplitude -- see docs/PROTOCOL_NOTES.md. Run this while audio is playing
through the amp to see levels move.
"""
import sys, time
sys.path.insert(0, r'C:\temp\inuke\scripts')
from inuke_client import INukeDevice

d = INukeDevice()
samples = []
try:
    deadline = time.time() + 6.0
    while time.time() < deadline:
        for msg in d.poll(timeout_s=0.5):
            if msg['addr'] == '/meter':
                samples.append(msg['args'])
finally:
    d.close()

print(f'collected {len(samples)} meter samples')
if samples:
    n = len(samples[0])
    for i in range(n):
        vals = [s[i] for s in samples]
        print(f'  pos{i}: min={min(vals):.6f} max={max(vals):.6f} avg={sum(vals)/len(vals):.6f}')
    print('\nlast 10 raw samples:')
    for s in samples[-10:]:
        print('   ', [f'{v:.6f}' for v in s])
