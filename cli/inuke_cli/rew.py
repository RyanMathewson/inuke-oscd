"""Client for Room EQ Wizard's REST API, plus the translation between REW's
EQ filters and the amp's 8 PEQ bands.

REW's API needs REW V5.40 or later, started with the API enabled
(`roomeqwizard.exe -api`, or Preferences -> API). It listens on
http://127.0.0.1:4735 and describes itself at /doc.json. Reading data,
importing responses, and the EQ commands work on a free REW. Starting a
sweep (and a few settings such as measurement naming) needs REW's Pro
upgrade -- those return HTTP 401, which `RewProRequired` reports.

Only the standard library is used, so this adds no dependencies.
"""
from __future__ import annotations

import base64
import json
import math
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

DEFAULT_URL = "http://127.0.0.1:4735"

AMP_BANDS = 8
EQUALISER = {"manufacturer": "Generic", "model": "Generic"}

# REW filter type -> amp PEQ type. REW's Generic "LS"/"HS" are 12 dB/oct.
REW_TO_AMP_TYPE = {
    "PK": "PEQ",
    "LS": "LS12",
    "LS 12dB": "LS12",
    "LS 6dB": "LS6",
    "HS": "HS12",
    "HS 12dB": "HS12",
    "HS 6dB": "HS6",
}
AMP_TO_REW_TYPE = {"PEQ": "PK", "LS12": "LS 12dB", "LS6": "LS 6dB", "HS12": "HS 12dB", "HS6": "HS 6dB"}

# REW's shelves have no Q; the amp's do. 0.707 is the conventional
# (Butterworth) shelf Q, which is what a fixed-slope 12 dB shelf means.
SHELF_Q = 0.707

# REW puts a shelf's frequency at its corner on the shelf side; RBJ-style
# DSP (and filtermath) puts it at the midpoint of the transition. Measured
# against REW 5.40: midpoint = REW frequency * 10^(|gain| / (40 * order))
# for low shelves (divide for high shelves), to within 0.04 dB. Which
# convention the amp uses isn't known yet -- `shelf_midpoint=False` sends
# REW's frequency unchanged.
SHELF_ORDER = {"LS12": 2, "HS12": 2, "LS6": 1, "HS6": 1}


def shelf_midpoint_factor(amp_type: str, gain_db: float) -> float:
    """Multiply a REW shelf frequency by this to get the midpoint one."""
    order = SHELF_ORDER.get(amp_type)
    if order is None:
        return 1.0
    factor = 10 ** (abs(gain_db) / (40 * order))
    return factor if amp_type.startswith("LS") else 1 / factor


# What REW's fitted filters get clamped to before they go to the amp. These
# are not documented device limits (see constants.BOUNDS): the vendor app's
# saved .arp files show gains up to +13 dB and Q from 0.15 up to exactly
# 10.0, which looks like the UI's ceiling, so Q is held to that.
AMP_Q_RANGE = (0.15, 10.0)
AMP_GAIN_RANGE = (-24.0, 24.0)
AMP_FREQ_RANGE = (20.0, 20000.0)

# What an unused band is written as.
OFF_BAND = {"type": "OFF", "freq": 1000.0, "gain": 0.0, "q": 1.0}


class RewError(RuntimeError):
    pass


class RewUnavailable(RewError):
    pass


class RewProRequired(RewError):
    pass


def encode_floats(values: Sequence[float]) -> str:
    """REW transfers arrays as base64 of big-endian float32."""
    return base64.b64encode(struct.pack(f">{len(values)}f", *values)).decode("ascii")


def decode_floats(data: str) -> list[float]:
    raw = base64.b64decode(data)
    return list(struct.unpack(f">{len(raw) // 4}f", raw))


@dataclass
class Response:
    """A magnitude response on a frequency grid (Hz, dB)."""

    freqs: list[float]
    mags: list[float]

    @classmethod
    def from_api(cls, obj: dict) -> "Response":
        mags = decode_floats(obj["magnitude"])
        start = obj["startFreq"]
        if obj.get("ppo"):
            ppo = obj["ppo"]
            freqs = [start * 2 ** (i / ppo) for i in range(len(mags))]
        else:
            step = obj["freqStep"]
            freqs = [start + i * step for i in range(len(mags))]
        return cls(freqs, mags)

    def at(self, f: float) -> Optional[float]:
        """Linear interpolation on log frequency; None outside the data."""
        fs = self.freqs
        if not fs or f < fs[0] or f > fs[-1]:
            return None
        lo, hi = 0, len(fs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if fs[mid] <= f:
                lo = mid
            else:
                hi = mid
        if fs[hi] == fs[lo]:
            return self.mags[lo]
        t = (math.log(f) - math.log(fs[lo])) / (math.log(fs[hi]) - math.log(fs[lo]))
        return self.mags[lo] + t * (self.mags[hi] - self.mags[lo])


@dataclass
class Deviation:
    rms_db: float
    max_db: float
    worst_hz: float


def deviation(actual: Response, reference: Response, lo_hz: float, hi_hz: float, ppo: int = 24) -> Optional[Deviation]:
    """RMS and worst-case gap between two responses over [lo_hz, hi_hz],
    sampled on a log grid so every octave counts equally."""
    diffs: list[tuple[float, float]] = []
    n = int(math.log2(hi_hz / lo_hz) * ppo)
    for i in range(n + 1):
        f = lo_hz * 2 ** (i / ppo)
        a, r = actual.at(f), reference.at(f)
        if a is not None and r is not None:
            diffs.append((f, a - r))
    if not diffs:
        return None
    rms = math.sqrt(sum(d * d for _, d in diffs) / len(diffs))
    worst_f, worst = max(diffs, key=lambda x: abs(x[1]))
    return Deviation(rms, abs(worst), worst_f)


@dataclass
class MappedBands:
    bands: list[dict]
    notes: list[str] = field(default_factory=list)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def rew_filters_to_amp(filters: list[dict], max_q: float = AMP_Q_RANGE[1], shelf_midpoint: bool = True) -> MappedBands:
    """Turn REW's filter list into exactly AMP_BANDS amp bands, sorted by
    frequency, with unused bands OFF. Values outside the amp's range are
    clamped and noted, never silently changed."""
    active = [f for f in filters if f.get("type") not in (None, "None") and f.get("enabled", True)]
    if len(active) > AMP_BANDS:
        raise RewError(f"REW has {len(active)} active filters but the amp only has {AMP_BANDS} PEQ bands")
    notes: list[str] = []
    bands = []
    for f in sorted(active, key=lambda f: f["frequency"]):
        rew_type = f["type"]
        if rew_type not in REW_TO_AMP_TYPE:
            raise RewError(
                f"REW filter {f.get('index')} is type {rew_type!r}, which the amp has no equivalent for "
                f"(supported: {', '.join(REW_TO_AMP_TYPE)})"
            )
        amp_type = REW_TO_AMP_TYPE[rew_type]
        gain = float(f.get("gaindB", 0.0))
        label = f"{rew_type} {float(f['frequency']):.1f} Hz"
        freq = float(f["frequency"]) * (shelf_midpoint_factor(amp_type, gain) if shelf_midpoint else 1.0)
        q = float(f["q"]) if amp_type == "PEQ" else SHELF_Q
        cf = _clamp(freq, *AMP_FREQ_RANGE)
        cg = _clamp(gain, *AMP_GAIN_RANGE)
        cq = _clamp(q, AMP_Q_RANGE[0], max_q)
        if round(cf, 2) != round(freq, 2):
            notes.append(f"{label}: frequency clamped to {cf:g} Hz")
        if round(cg, 2) != round(gain, 2):
            notes.append(f"{label}: gain {gain:+.1f} dB clamped to {cg:+.1f} dB")
        if round(cq, 3) != round(q, 3):
            notes.append(f"{label}: Q {q:.2f} clamped to {cq:.2f}")
        bands.append({"type": amp_type, "freq": round(cf, 1), "gain": round(cg, 1), "q": round(cq, 2)})
    bands += [dict(OFF_BAND) for _ in range(AMP_BANDS - len(bands))]
    return MappedBands(bands, notes)


def amp_bands_to_rew(bands: list[dict], slot_count: int, shelf_midpoint: bool = True) -> list[dict]:
    """The amp's bands as a full REW FilterList (slots beyond the amp's
    band count cleared); all slots manual so REW's auto-EQ leaves them be."""
    out = []
    for i in range(1, slot_count + 1):
        b = bands[i - 1] if i <= len(bands) else None
        if b is None or b["type"] == "OFF":
            out.append({"index": i, "type": "None", "enabled": True, "isAuto": False})
            continue
        if b["type"] not in AMP_TO_REW_TYPE:
            raise RewError(f"amp band {i} has unknown type {b['type']!r}")
        entry = {
            "index": i,
            "type": AMP_TO_REW_TYPE[b["type"]],
            "enabled": True,
            "isAuto": False,
            "frequency": float(b["freq"]) / (shelf_midpoint_factor(b["type"], float(b["gain"])) if shelf_midpoint else 1.0),
            "gaindB": float(b["gain"]),
        }
        if b["type"] == "PEQ":
            entry["q"] = float(b["q"])
        out.append(entry)
    return out


def _message(body: Any) -> str:
    if isinstance(body, dict) and "message" in body:
        return str(body["message"])
    return str(body)


class RewClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout_s: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    # --- transport ---
    def request(self, method: str, path: str, body: Any = None, timeout_s: Optional[float] = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            # REW's API is served by Spark, which routes on the Accept header: without
            # "application/json" every request comes back 404 Not found.
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s or self.timeout_s) as resp:
                text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", errors="replace")
            try:
                detail = _message(json.loads(text))
            except ValueError:
                detail = text.strip()
            if err.code == 401:
                raise RewProRequired(f"{method} {path}: {detail}") from None
            raise RewError(f"{method} {path} failed ({err.code}): {detail}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
            raise RewUnavailable(
                f"can't reach REW's API at {self.base_url} ({err}) -- is REW V5.40+ running with the API "
                f"enabled (roomeqwizard.exe -api, or Preferences -> API)?"
            ) from None
        return json.loads(text) if text.strip() else None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self.request("POST", path, body)

    def put(self, path: str, body: Any) -> Any:
        return self.request("PUT", path, body)

    # --- application ---
    def version(self) -> str:
        return _message(self.get("/version"))

    def enable_blocking(self) -> None:
        """Make long-running commands (sweeps, EQ matching) reply only
        once they've finished, so no polling is needed."""
        self.post("/application/blocking", True)

    def has_pro(self) -> bool:
        """Re-posting the current naming settings is a no-op that REW
        only allows with a Pro licence -- the same gate as sweeps."""
        try:
            self.post("/measure/naming", self.get("/measure/naming"))
        except RewProRequired:
            return False
        return True

    # --- measurements ---
    def measurements(self) -> dict[str, dict]:
        """Index (as a string, from 1) -> MeasurementSummary."""
        return self.get("/measurements") or {}

    def uuids(self) -> set[str]:
        return {m["uuid"] for m in self.measurements().values()}

    def measurement(self, mid: str) -> dict:
        return self.get(f"/measurements/{mid}")

    def rename(self, mid: str, title: str) -> None:
        self.put(f"/measurements/{mid}", {"title": title})

    def frequency_response(self, mid: str, ppo: int = 48, smoothing: Optional[str] = None, equalised: bool = False) -> Response:
        path = f"/measurements/{mid}/{'eq/' if equalised else ''}frequency-response?ppo={ppo}"
        if smoothing:
            path += f"&smoothing={smoothing}"
        return Response.from_api(self.get(path))

    def target_response(self, mid: str, ppo: int = 48) -> Response:
        return Response.from_api(self.get(f"/measurements/{mid}/target-response?ppo={ppo}"))

    def smooth(self, mid: str, smoothing: str = "Var") -> None:
        self.post(f"/measurements/{mid}/command", {"command": "Smooth", "parameters": {"smoothing": smoothing}})

    def import_response(self, title: str, response: Response, ppo: int) -> str:
        """Import a log-spaced magnitude response as a new measurement;
        returns its UUID."""
        before = self.uuids()
        self.post(
            "/import/frequency-response-data",
            {
                "identifier": title,
                "startFreq": response.freqs[0],
                "ppo": ppo,
                "magnitude": encode_floats(response.mags),
            },
        )
        return self._new_uuid(before)

    def db_average(self, uuids: list[str]) -> str:
        before = self.uuids()
        self.post("/measurements/process-measurements", {"processName": "dB average", "measurementUUIDs": uuids})
        return self._new_uuid(before)

    def _new_uuid(self, before: set[str]) -> str:
        new = self.uuids() - before
        if len(new) != 1:
            raise RewError(f"expected REW to add one measurement, found {len(new)}")
        return new.pop()

    def measure_spl(self) -> None:
        """Run a sweep with REW's current measurement settings (Pro only)."""
        self.post("/measure/command", {"command": "SPL"})

    # --- EQ ---
    def filters(self, mid: str) -> list[dict]:
        return self.get(f"/measurements/{mid}/filters")

    def set_filters(self, mid: str, filters: list[dict]) -> None:
        self.post(f"/measurements/{mid}/filters", {"filters": filters})

    def use_amp_equaliser(self, mid: str) -> int:
        """Select REW's Generic equaliser and let its auto-EQ use only the
        first AMP_BANDS slots. Returns the equaliser's total slot count."""
        self.post(f"/measurements/{mid}/equaliser", EQUALISER)
        slots = len(self.filters(mid))
        self.set_filters(
            mid,
            [{"index": i, "type": "None", "enabled": True, "isAuto": i <= AMP_BANDS} for i in range(1, slots + 1)],
        )
        return slots

    def eq_command(self, mid: str, command: str) -> None:
        self.post(f"/measurements/{mid}/eq/command", {"command": command})

    def target_level(self, mid: str) -> float:
        return float(self.get(f"/measurements/{mid}/target-level"))

    def set_target_level(self, mid: str, level_db: float) -> None:
        self.post(f"/measurements/{mid}/target-level", level_db)

    def target_settings(self, mid: str) -> dict:
        return self.get(f"/measurements/{mid}/target-settings")

    def update_target_settings(self, mid: str, settings: dict) -> None:
        if settings:
            self.put(f"/measurements/{mid}/target-settings", settings)

    def update_match_settings(self, settings: dict) -> None:
        if settings:
            self.put("/eq/match-target-settings", settings)

    def match_settings(self) -> dict:
        return self.get("/eq/match-target-settings")

    def set_house_curve(self, path: str) -> None:
        self.post("/eq/house-curve", path)
