"""Measure -> fit -> apply -> verify loop between REW and the amp.

How a pass works:

1. Measure the room with whatever PEQ is currently on the amp channel.
2. Estimate the *uncorrected* room response by removing the applied PEQ
   from that measurement, using REW's own model of those filters (REW's
   equalised response of the measurement is measured + EQ, so
   uncorrected = 2 * measured - equalised). The estimate is imported into
   REW as its own measurement.
3. Average all the estimates so far (REW "dB average"), let REW's
   "Match target" fit up to 8 filters to the average, clamp them to what
   the amp accepts, and write them to the amp.
4. The next measurement both verifies that result (against the target and
   against REW's prediction) and adds another estimate for the next fit.

Refitting always starts from the uncorrected estimate, never stacks new
filters on old ones -- the amp only has 8 bands. Averaging estimates means
every measurement (including extra ones from nearby mic positions) makes
the fit more robust, and nothing ever needs the EQ switched off.
"""
from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from . import filtermath
from .rew import (
    AMP_BANDS,
    AMP_Q_RANGE,
    OFF_BAND,
    Deviation,
    MappedBands,
    Response,
    RewClient,
    RewError,
    amp_bands_to_rew,
    deviation,
    rew_filters_to_amp,
)

PPO = 48

SHAPES = {
    "full": "Full range",
    "bass-limited": "Bass limited",
    "subwoofer": "Subwoofer",
    "driver": "Driver",
    "none": "None",
}


# --------------------------------------------------------------------------
# fit settings


@dataclass
class FitSettings:
    """Overrides for REW's EQ settings. None means "use whatever REW has"
    (set in REW's EQ window), so REW stays the place to fine-tune them."""

    shape: Optional[str] = None
    lf_cutoff_hz: Optional[int] = None
    bm_cutoff_hz: Optional[int] = None
    bm_slope_db: Optional[int] = None
    lo_hz: Optional[int] = None
    hi_hz: Optional[int] = None
    max_boost_db: Optional[int] = None
    overall_max_boost_db: Optional[int] = None
    flatness_db: Optional[int] = None
    shelves: Optional[bool] = None
    target_level_db: Optional[float] = None
    max_q: float = AMP_Q_RANGE[1]
    shelf_midpoint: bool = True

    def target_settings(self) -> dict:
        out: dict = {}
        if self.shape is not None:
            out["shape"] = self.shape
        if self.lf_cutoff_hz is not None:
            out["lowFreqCutoffHz"] = self.lf_cutoff_hz
        if self.bm_cutoff_hz is not None:
            out["bassManagementCutoffHz"] = self.bm_cutoff_hz
        if self.bm_slope_db is not None:
            out["bassManagementSlopedBPerOctave"] = self.bm_slope_db
        return out

    def match_settings(self) -> dict:
        out: dict = {}
        if self.lo_hz is not None:
            out["startFrequency"] = self.lo_hz
        if self.hi_hz is not None:
            out["endFrequency"] = self.hi_hz
        if self.max_boost_db is not None:
            out["individualMaxBoostdB"] = self.max_boost_db
        if self.overall_max_boost_db is not None:
            out["overallMaxBoostdB"] = self.overall_max_boost_db
        if self.flatness_db is not None:
            out["flatnessTargetdB"] = self.flatness_db
        if self.shelves is not None:
            out["allowLowShelf"] = self.shelves
            out["allowHighShelf"] = self.shelves
        return out

    def apply_text(self, text: str) -> bool:
        """Apply `key=value` edits typed at the loop's prompt. Returns
        whether the target level should be recalculated."""
        recalc_level = False
        for token in text.split():
            if "=" not in token:
                raise ValueError(f"expected key=value, got {token!r}")
            key, value = token.split("=", 1)
            key = key.lower()
            if key == "range":
                lo, hi = parse_range(value)
                self.lo_hz, self.hi_hz = lo, hi
            elif key == "boost":
                self.max_boost_db = int(value)
            elif key == "overall-boost":
                self.overall_max_boost_db = int(value)
            elif key == "flatness":
                self.flatness_db = int(value)
            elif key == "shelves":
                self.shelves = parse_on_off(value)
            elif key == "shape":
                self.shape = parse_shape(value)
                recalc_level = True
            elif key == "lf":
                self.lf_cutoff_hz = int(value)
                recalc_level = True
            elif key == "bm":
                self.bm_cutoff_hz = int(value)
                recalc_level = True
            elif key == "bm-slope":
                self.bm_slope_db = int(value)
                recalc_level = True
            elif key == "q":
                self.max_q = float(value)
            elif key == "level":
                if value.lower() == "auto":
                    self.target_level_db = None
                    recalc_level = True
                else:
                    self.target_level_db = float(value)
            else:
                raise ValueError(f"unknown setting {key!r}")
        return recalc_level


SETTINGS_HELP = (
    "range=LO-HI  boost=DB  overall-boost=DB  flatness=DB  shelves=on|off\n"
    f"  shape={'|'.join(SHAPES)}  lf=HZ  bm=HZ  bm-slope=DB  q=MAXQ  level=DB|auto"
)


def parse_range(text: str) -> tuple[int, int]:
    try:
        lo, hi = (int(float(x)) for x in text.split("-", 1))
    except ValueError:
        raise ValueError(f"range must look like 20-500, got {text!r}") from None
    if not 0 < lo < hi:
        raise ValueError(f"range must be LO-HI with 0 < LO < HI, got {text!r}")
    return lo, hi


def parse_on_off(text: str) -> bool:
    t = text.lower()
    if t in ("on", "yes", "true", "1"):
        return True
    if t in ("off", "no", "false", "0"):
        return False
    raise ValueError(f"expected on/off, got {text!r}")


def parse_shape(text: str) -> str:
    key = text.lower()
    if key not in SHAPES:
        raise ValueError(f"shape must be one of {', '.join(SHAPES)}")
    return SHAPES[key]


# --------------------------------------------------------------------------
# amp side


def read_bands(amp, channel: int) -> list[dict]:
    return [amp.get_peq(channel, b) for b in range(1, AMP_BANDS + 1)]


def _band_matches(want: dict, got: dict) -> bool:
    if want["type"] != got["type"]:
        return False
    if want["type"] == "OFF":
        return True
    # The amp stores float32, so allow for rounding.
    return all(abs(float(want[k]) - float(got[k])) <= 0.01 + 0.001 * abs(float(want[k])) for k in ("freq", "gain", "q"))


def write_bands(amp, channel: int, bands: list[dict]) -> None:
    """Write all 8 bands, read them back, and retry any the amp didn't
    take -- bursts of writes have been seen to drop on real hardware
    (see protocol.MIN_SEND_INTERVAL_S)."""
    pending = list(range(1, AMP_BANDS + 1))
    for _attempt in range(3):
        for b in pending:
            band = bands[b - 1]
            amp.set_peq(channel, b, band["type"], band["freq"], band["gain"], band["q"])
        pending = [b for b in pending if not _band_matches(bands[b - 1], amp.get_peq(channel, b))]
        if not pending:
            return
    raise RewError(f"amp didn't accept PEQ band(s) {pending} on channel {channel} after 3 tries")


def dynamic_eq_active(amp, channel: int) -> bool:
    """A DEQ band with 0 dB gain can't change anything, even if enabled."""
    return any(
        amp.get_deq_filt(channel, b)["type"] != "OFF" and amp.get_deq_comp(channel, b)["gain"] != 0 for b in (1, 2)
    )


class SimulatedAmp:
    """Stands in for INukeClient's PEQ/DEQ methods (`--simulate`)."""

    def __init__(self):
        self.peq = {(ch, b): dict(OFF_BAND) for ch in (1, 2) for b in range(1, AMP_BANDS + 1)}

    def get_peq(self, ch: int, band: int) -> dict:
        return dict(self.peq[(ch, band)])

    def set_peq(self, ch: int, band: int, type_: str, freq: float, gain: float, q: float) -> None:
        self.peq[(ch, band)] = {"type": type_, "freq": freq, "gain": gain, "q": q}

    def get_deq_filt(self, ch: int, band: int) -> dict:
        return {"type": "OFF", "freq": 40.0, "q": 1.0}

    def get_deq_comp(self, ch: int, band: int) -> dict:
        return {"gain": 0.0, "threshold": -30.0, "ratio": 5.0}


# --------------------------------------------------------------------------
# measuring


class ManualMeasurer:
    """For a free REW: the user starts the sweep in REW, we notice the new
    measurement appear."""

    def __init__(self, out: Callable[[str], None] = print, timeout_s: float = 900.0, poll_s: float = 1.0):
        self.out = out
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def measure(self, rew: RewClient, title: str) -> str:
        before = rew.uuids()
        self.out("  In REW: click Measure, check the settings, and press Start. Waiting for the new measurement...")
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            time.sleep(self.poll_s)
            new = rew.uuids() - before
            if new:
                uuid = sorted(new)[0]
                if len(new) > 1:
                    self.out(f"  (REW added {len(new)} measurements; using the first)")
                _try_rename(rew, uuid, title)
                return uuid
        raise RewError(f"no new REW measurement appeared within {self.timeout_s:.0f}s")


class ApiMeasurer:
    """REW Pro: start the sweep through the API."""

    def measure(self, rew: RewClient, title: str) -> str:
        before = rew.uuids()
        rew.measure_spl()
        new = rew.uuids() - before
        if not new:
            raise RewError("REW finished the sweep but no new measurement appeared -- check REW for an error dialog")
        uuid = sorted(new)[0]
        _try_rename(rew, uuid, title)
        return uuid


class AutoMeasurer:
    """Use the API if REW has Pro, otherwise fall back to manual."""

    def __init__(self, out: Callable[[str], None] = print):
        self.out = out
        self._impl = None

    def measure(self, rew: RewClient, title: str) -> str:
        if self._impl is None:
            if rew.has_pro():
                self._impl = ApiMeasurer()
            else:
                self.out("  REW has no Pro licence, so sweeps can't be started over the API -- you'll start them in REW.")
                self._impl = ManualMeasurer(self.out)
        return self._impl.measure(rew, title)


def _try_rename(rew: RewClient, uuid: str, title: str) -> None:
    try:
        rew.rename(uuid, title)
    except RewError:
        pass  # cosmetic only


class SimulatedRoom:
    """Fakes a measurement: a room with modes, plus whatever PEQ the
    (simulated) amp has on the channel, plus a little mic-position ripple.
    Imported into REW so the rest of the loop is exercised for real."""

    MODES = [(42, 9, 6), (68, -7, 5), (97, 6, 7), (140, -5, 4), (230, 4, 3), (1500, -2, 1.2), (5000, 2.5, 0.9)]

    def __init__(self, amp, channel: int, seed: int = 1, level_db: float = 82.0):
        self.amp = amp
        self.channel = channel
        self.rng = random.Random(seed)
        self.level_db = level_db

    def response(self, f: float, ripple: list[tuple[float, float, float]]) -> float:
        db = self.level_db
        for fc, g, q in self.MODES + ripple:
            x = f / fc
            db += g / math.sqrt(1 + (q * (x - 1 / x)) ** 2)
        db += -10 * math.log10(1 + (28 / f) ** 8)  # speaker roll-off
        db += -10 * math.log10(1 + (f / 18000) ** 4)
        return db

    def measure(self, rew: RewClient, title: str) -> str:
        bands = read_bands(self.amp, self.channel)
        ripple = [(self.rng.uniform(80, 8000), self.rng.uniform(-1.0, 1.0), self.rng.uniform(1, 4)) for _ in range(6)]
        n = int(math.log2(20000 / 10) * PPO) + 1
        freqs = [10 * 2 ** (i / PPO) for i in range(n)]
        mags = [self.response(f, ripple) + filtermath.bands_db(bands, f) for f in freqs]
        return rew.import_response(f"{title} (simulated)", Response(freqs, mags), PPO)


# --------------------------------------------------------------------------
# the session


@dataclass
class FitResult:
    basis_uuid: str
    basis_count: int
    mapped: MappedBands
    lo_hz: float
    hi_hz: float
    target_level_db: float
    target_desc: str
    before: Optional[Deviation]
    predicted: Optional[Deviation]


@dataclass
class VerifyResult:
    vs_target: Optional[Deviation]
    vs_prediction: Optional[Deviation]


@dataclass
class SessionLog:
    channel: int
    rew_version: str
    original_bands: list[dict]
    started: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    events: list[dict] = field(default_factory=list)


def fit_to_target(rew: RewClient, basis: str, settings: FitSettings, target_level_db: Optional[float] = None) -> FitResult:
    """Have REW fit up to AMP_BANDS filters to measurement `basis` (taken
    as the uncorrected room), clamped to the amp's ranges. The target level
    is settings.target_level_db, else `target_level_db`, else REW's own
    calculation."""
    slots = rew.use_amp_equaliser(basis)
    rew.update_target_settings(basis, settings.target_settings())
    rew.update_match_settings(settings.match_settings())
    level = settings.target_level_db if settings.target_level_db is not None else target_level_db
    if level is None:
        rew.eq_command(basis, "Calculate target level")
        level = rew.target_level(basis)
    else:
        rew.set_target_level(basis, level)
    rew.eq_command(basis, "Match target")
    mapped = rew_filters_to_amp(rew.filters(basis), settings.max_q, settings.shelf_midpoint)
    # Put the clamped values back so REW's prediction (and its graphs)
    # show what the amp will actually do.
    rew.set_filters(basis, amp_bands_to_rew(mapped.bands, slots, settings.shelf_midpoint))

    match = rew.match_settings()
    lo, hi = match["startFrequency"], match["endFrequency"]
    ts = rew.target_settings(basis)
    shape = ts.get("shape")
    if shape == "Subwoofer":
        shape += f", low-pass {ts.get('bassManagementCutoffHz')} Hz {ts.get('bassManagementSlopedBPerOctave')} dB/oct"
    shelves = match.get("allowLowShelf") or match.get("allowHighShelf")
    target_desc = (
        f"target '{shape}' at {level:.1f} dB, match {lo}-{hi} Hz, max boost {match['individualMaxBoostdB']} dB, "
        f"flatness {match['flatnessTargetdB']} dB, shelves {'on' if shelves else 'off'}, max Q {settings.max_q:g}"
    )
    target = rew.target_response(basis, PPO)
    before = deviation(rew.frequency_response(basis, PPO), target, lo, hi)
    predicted = deviation(rew.frequency_response(basis, PPO, equalised=True), target, lo, hi)
    return FitResult(basis, 1, mapped, lo, hi, level, target_desc, before, predicted)


class RoomEqSession:
    def __init__(
        self,
        rew: RewClient,
        amp,
        channel: int,
        measurer,
        settings: FitSettings,
        out: Callable[[str], None] = print,
        log_path: Optional[str] = None,
    ):
        self.rew = rew
        self.amp = amp
        self.channel = channel
        self.measurer = measurer
        self.settings = settings
        self.out = out
        self.log_path = log_path
        self.estimates: list[str] = []
        self.target_level_db: Optional[float] = None
        self.pass_no = 0
        self.original_bands = read_bands(amp, channel)
        self.log = SessionLog(channel, rew.version(), self.original_bands)
        self._save_log()

    # --- log ---
    def _event(self, kind: str, **data) -> None:
        self.log.events.append({"kind": kind, "time": time.strftime("%H:%M:%S"), **data})
        self._save_log()

    def _save_log(self) -> None:
        if self.log_path:
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.log), f, indent=2)

    # --- steps ---
    def measure(self, label: str) -> str:
        """Measure with the current amp EQ and add an uncorrected-room
        estimate. Returns the measurement's UUID."""
        rew, ch = self.rew, self.channel
        applied = read_bands(self.amp, ch)
        uuid = self.measurer.measure(rew, f"iNuke ch{ch} {label}")
        rew.smooth(uuid, "Var")
        slots = rew.use_amp_equaliser(uuid)
        rew.set_filters(uuid, amp_bands_to_rew(applied, slots, self.settings.shelf_midpoint))
        measured = rew.frequency_response(uuid, PPO)
        equalised = rew.frequency_response(uuid, PPO, equalised=True)
        estimate = Response(measured.freqs, [2 * m - e for m, e in zip(measured.mags, equalised.mags)])
        est_uuid = rew.import_response(f"iNuke ch{ch} {label} - EQ removed", estimate, PPO)
        self.estimates.append(est_uuid)
        self._event("measure", label=label, measurement=uuid, estimate=est_uuid, applied_bands=applied)
        return uuid

    def fit(self, recalc_level: bool = False) -> FitResult:
        rew = self.rew
        if len(self.estimates) == 1:
            basis = self.estimates[0]
        else:
            basis = rew.db_average(self.estimates)
            _try_rename(rew, basis, f"iNuke ch{self.channel} room estimate (avg of {len(self.estimates)})")
        if self.settings.target_level_db is not None or recalc_level:
            self.target_level_db = None
        # The first fit settles the target level; later fits reuse it so
        # results stay comparable as measurements are added.
        result = fit_to_target(rew, basis, self.settings, self.target_level_db)
        self.target_level_db = result.target_level_db
        result.basis_count = len(self.estimates)
        self._event(
            "fit",
            basis=basis,
            estimates=len(self.estimates),
            bands=result.mapped.bands,
            notes=result.mapped.notes,
            settings=result.target_desc,
            before=_dev(result.before),
            predicted=_dev(result.predicted),
        )
        return result

    def apply(self, bands: list[dict]) -> None:
        write_bands(self.amp, self.channel, bands)
        self._event("apply", bands=bands)

    def restore_original(self) -> None:
        write_bands(self.amp, self.channel, self.original_bands)
        self._event("restore", bands=self.original_bands)

    def verify(self, measurement_uuid: str, fit: FitResult) -> VerifyResult:
        rew = self.rew
        measured = rew.frequency_response(measurement_uuid, PPO)
        target = rew.target_response(fit.basis_uuid, PPO)
        predicted = rew.frequency_response(fit.basis_uuid, PPO, equalised=True)
        result = VerifyResult(
            deviation(measured, target, fit.lo_hz, fit.hi_hz),
            deviation(measured, predicted, fit.lo_hz, fit.hi_hz),
        )
        self._event("verify", measurement=measurement_uuid, vs_target=_dev(result.vs_target), vs_prediction=_dev(result.vs_prediction))
        return result


def _dev(d: Optional[Deviation]) -> Optional[dict]:
    return None if d is None else {"rms_db": round(d.rms_db, 2), "max_db": round(d.max_db, 2), "worst_hz": round(d.worst_hz, 1)}


# --------------------------------------------------------------------------
# presentation


def format_bands(bands: list[dict]) -> str:
    lines = ["  band  type   freq(Hz)   gain(dB)     Q"]
    for i, b in enumerate(bands, 1):
        if b["type"] == "OFF":
            lines.append(f"  {i:>4}  OFF")
        elif b["type"] == "PEQ":
            lines.append(f"  {i:>4}  {b['type']:<5} {b['freq']:>9.1f}   {b['gain']:>+7.1f}   {b['q']:>6.2f}")
        else:
            lines.append(f"  {i:>4}  {b['type']:<5} {b['freq']:>9.1f}   {b['gain']:>+7.1f}")
    return "\n".join(lines)


def format_dev(d: Optional[Deviation]) -> str:
    if d is None:
        return "n/a (no data in the match range)"
    return f"{d.rms_db:.2f} dB RMS, worst {d.max_db:.1f} dB at {d.worst_hz:.0f} Hz"


LOOP_MENU = """
  What next?
    [r] re-fit using all {n} measurement(s) so far
    [m] take another measurement first (e.g. move the mic a little), then re-fit
    [s] change fit settings, then re-fit
    [k] keep what's on the amp and finish
    [u] undo: put the channel's original EQ back and finish"""


def run_loop(session: RoomEqSession, ask: Callable[[str], str] = input, assume_yes: bool = False) -> int:
    out = session.out
    ch = session.channel
    out(f"Channel {ch}: original PEQ (restorable with [u]):")
    out(format_bands(session.original_bands))
    if dynamic_eq_active(session.amp, ch):
        out("  warning: dynamic EQ is active on this channel; its level-dependent gain will skew measurements.")

    out("\n== Measurement 1 (with the current EQ) ==")
    _wait(ask, assume_yes, "Press Enter to measure")
    session.measure("baseline")

    recalc_level = False
    while True:
        out(f"\n== Fitting EQ to {len(session.estimates)} measurement(s) ==")
        fit = session.fit(recalc_level)
        recalc_level = False
        out(f"  {fit.target_desc}")
        out(format_bands(fit.mapped.bands))
        for note in fit.mapped.notes:
            out(f"  note: {note}")
        out(f"  room vs target, no EQ:   {format_dev(fit.before)}")
        out(f"  predicted with this EQ:  {format_dev(fit.predicted)}")

        answer = "y" if assume_yes else ask("Write this to the amp? [Y/n/s=settings] ").strip().lower()
        if answer in ("s", "settings"):
            recalc_level = _edit_settings(session, ask)
            continue
        if answer not in ("", "y", "yes"):
            out("  Not applied.")
        else:
            session.apply(fit.mapped.bands)
            session.pass_no += 1
            out(f"  Written to channel {ch}.")
            out(f"\n== Measurement {len(session.estimates) + 1} (verifying) ==")
            _wait(ask, assume_yes, "Press Enter to measure")
            uuid = session.measure(f"pass {session.pass_no}")
            v = session.verify(uuid, fit)
            out(f"  measured vs target:      {format_dev(v.vs_target)}")
            out(f"  measured vs prediction:  {format_dev(v.vs_prediction)}")
            if v.vs_prediction and v.vs_prediction.rms_db > 2.0:
                out("  (the room didn't respond as REW predicted -- the mic may have moved, or the amp's filters")
                out("   differ from REW's model; re-fitting with more measurements averages this out)")

        if assume_yes:
            return 0
        while True:
            out(LOOP_MENU.format(n=len(session.estimates)))
            choice = ask("> ").strip().lower()
            if choice == "r":
                break
            if choice == "m":
                out(f"\n== Measurement {len(session.estimates) + 1} ==")
                _wait(ask, assume_yes, "Press Enter to measure")
                session.measure(f"extra {len(session.estimates) + 1}")
                break
            if choice == "s":
                recalc_level = _edit_settings(session, ask)
                break
            if choice == "k":
                out(f"Done. Channel {ch} keeps its current EQ. Session log: {session.log_path or '(not saved)'}")
                out("Tip: `inuke preset store <slot> <name>` saves it to an onboard preset.")
                return 0
            if choice == "u":
                session.restore_original()
                out(f"Channel {ch}'s original EQ is back.")
                return 0
            out("  Please answer r, m, s, k or u.")


def _wait(ask: Callable[[str], str], assume_yes: bool, prompt: str) -> None:
    if not assume_yes:
        ask(f"  {prompt} (Ctrl+C to abort) ")


def _edit_settings(session: RoomEqSession, ask: Callable[[str], str]) -> bool:
    session.out(f"  Settings (blank to keep): {SETTINGS_HELP}")
    while True:
        text = ask("  settings> ").strip()
        if not text:
            return False
        try:
            return session.settings.apply_text(text)
        except ValueError as err:
            session.out(f"  {err}")
