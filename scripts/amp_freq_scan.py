"""Map the amp's sub-band response using its own meters, at a fixed safe volume."""
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
    return float("-inf") if x <= 0 else 20 * math.log10(x)

FREQS = [20, 25, 30, 35, 40, 50, 60, 65, 70, 80, 90, 100]
RECEIVER_RAW, TONE_DBFS = 37, -12.0   # raw 37 = -45 dB

rew("POST", "/generator/signal", {"signal": "sine"})
rew("POST", "/generator/level", {"value": TONE_DBFS, "unit": "dBFS"})

amp = INukeClient()
recv = Onkyo("COM3").open()
original = recv.volume_raw()
rows = []
try:
    recv.set_volume_raw(RECEIVER_RAW)
    print(f"Receiver {recv.raw_to_db(RECEIVER_RAW):+.0f} dB, sine at {TONE_DBFS:+.0f} dBFS\n")
    print(f"{'Hz':>5} {'in A':>11} {'out A':>11} {'out B':>11}   {'inA dB':>9} {'outA dB':>10} {'outB dB':>10}")
    for f in FREQS:
        rew("POST", "/generator/frequency", {"value": float(f), "unit": "Hz"})
        amp.meter_heartbeat()
        rew("POST", "/generator/command", {"command": "Play"})
        time.sleep(1.0)
        peaks = [0.0, 0.0, 0.0, 0.0]
        end = time.time() + 2.0
        while time.time() < end:
            for msg in amp.poll(timeout_s=0.5):
                if msg["addr"] == "/meter" and msg["typetags"] == "ffff":
                    peaks = [max(p, v) for p, v in zip(peaks, msg["args"])]
        rew("POST", "/generator/command", {"command": "Stop"})
        time.sleep(0.3)
        rows.append((f, peaks))
        print(f"{f:>5} {peaks[0]:>11.7f} {peaks[2]:>11.7f} {peaks[3]:>11.7f}"
              f"   {dbfs(peaks[0]):>9.1f} {dbfs(peaks[2]):>10.1f} {dbfs(peaks[3]):>10.1f}")
finally:
    try:
        rew("POST", "/generator/command", {"command": "Stop"})
    finally:
        if original is not None:
            recv.set_volume_raw(original, allow_above_max=True)
            print(f"\nReceiver restored to {recv.raw_to_db(original):+.0f} dB")
        recv.close()
        amp.close()

if rows:
    peak_in = max(rows, key=lambda r: r[1][0])
    peak_out = max(rows, key=lambda r: r[1][2])
    print(f"Hottest input : {peak_in[0]} Hz ({peak_in[1][0]:.7f}, {dbfs(peak_in[1][0]):.1f} dBFS)")
    print(f"Hottest out A : {peak_out[0]} Hz ({peak_out[1][2]:.7f}, {dbfs(peak_out[1][2]):.1f} dBFS)")
