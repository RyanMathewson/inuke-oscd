"""Measure what REW's real sweep level does at the amp, at safe receiver volumes."""
import json, math, sys, time, urllib.request

sys.path.insert(0, r"C:\temp\inuke\cli")
from inuke_cli.protocol import INukeClient
from inuke_cli.onkyo import Onkyo

BASE = "http://127.0.0.1:4735"
H = {"Accept": "application/json", "Content-Type": "application/json"}

def rew(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=H)
    with urllib.request.urlopen(req, timeout=20) as r:
        t = r.read().decode()
    return json.loads(t) if t.strip() else None

def dbfs(x):
    return "-inf" if x <= 0 else f"{20*math.log10(x):+.1f}"

LADDER = [22, 27, 32, 37]   # raw: -60, -55, -50, -45 dB
TONE_HZ, TONE_DBFS = 50.0, -12.0

rew("POST", "/generator/signal", {"signal": "sine"})
rew("POST", "/generator/frequency", {"value": TONE_HZ, "unit": "Hz"})
rew("POST", "/generator/level", {"value": TONE_DBFS, "unit": "dBFS"})
print(f"{TONE_HZ:.0f} Hz sine at {TONE_DBFS:+.0f} dBFS (REW's sweep level)\n")
print(f"{'receiver':>9} {'in A':>8} {'out A':>8} {'out B':>8}   {'in A dBFS':>10} {'out A dBFS':>11}")

amp = INukeClient()
recv = Onkyo("COM3").open()
original = recv.volume_raw()
try:
    for raw in LADDER:
        recv.set_volume_raw(raw)
        amp.meter_heartbeat()
        rew("POST", "/generator/command", {"command": "Play"})
        time.sleep(1.2)
        peaks = [0.0, 0.0, 0.0, 0.0]
        end = time.time() + 2.5
        while time.time() < end:
            for msg in amp.poll(timeout_s=0.5):
                if msg["addr"] == "/meter" and msg["typetags"] == "ffff":
                    peaks = [max(p, v) for p, v in zip(peaks, msg["args"])]
        rew("POST", "/generator/command", {"command": "Stop"})
        time.sleep(0.4)
        print(f"{recv.raw_to_db(raw):>+8.0f}  {peaks[0]:>8.4f} {peaks[2]:>8.4f} {peaks[3]:>8.4f}"
              f"   {dbfs(peaks[0]):>10} {dbfs(peaks[2]):>11}")
finally:
    try:
        rew("POST", "/generator/command", {"command": "Stop"})
    finally:
        if original is not None:
            recv.set_volume_raw(original, allow_above_max=True)
            print(f"\nReceiver restored to {recv.raw_to_db(original):+.0f} dB")
        recv.close()
        amp.close()
