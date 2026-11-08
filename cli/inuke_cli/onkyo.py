"""ISCP over RS-232 for older Onkyo receivers, used as the measurement level control.

The iNuke's own ``/gain`` is read-only on real hardware, and the only level the
amp will accept is ``/channel/N/xover/gain`` -- which is part of what the room-EQ
loop is fitting, so moving it would corrupt the measurement. On a setup where the
amp is fed from an AV receiver, the receiver's master volume is therefore the only
level in the whole signal path that can be set remotely. That makes two things
possible that the loop could not do before:

* take every sweep at the same, exactly known level, so measurements are
  comparable within a run and across sessions, and
* refuse to measure at all unless the receiver is on the expected input and in
  the expected listening mode, instead of silently producing a measurement taken
  through room correction or a multichannel upmix.

Protocol, observed on a TX-SR806 (see also the user's Home Assistant integration
at https://github.com/RyanMathewson/home-assistant-onkyo-serial):

* 9600 8N1. Commands are ``!1`` + a three-letter command + value + CR.
* Replies are terminated by 0x1A alone -- not CRLF -- and a single read can
  return several frames, or half of one.
* ``MVL`` carries the volume as *hex*, one unit per dB. On a TX-SR806 raw 82
  (``0x52``) is 0 dB, so raw 42 (``0x2A``) displays as -40.0 dB.
* In standby the receiver answers ``PWR`` and ``AMT`` but not ``MVL`` or ``SLI``.
* A value of ``N/A`` means "not available right now", not a real value.

The port is opened exclusively, so this cannot share an adapter with Home
Assistant's integration (which also takes an exclusive lock) at the same time.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

TERMINATOR = b"\x1a"

#: Raw ``MVL`` value the receiver displays as 0 dB (TX-SR806).
ZERO_DB_RAW = 82

#: Refuse to command a level above this raw value unless explicitly overridden.
#: 70 raw is -12 dB on a TX-SR806; a measurement sweep needs nothing like it.
DEFAULT_MAX_RAW = 70

#: ``SLI`` code -> name, confirmed on a TX-SR806's display.
SOURCES: Dict[str, str] = {
    "10": "DVD",
    "00": "VCR/DVR",
    "01": "CBL/SAT",
    "02": "GAME/TV",
    "03": "AUX",
    "20": "TAPE",
    "22": "PHONO",
    "23": "CD",
    "24": "FM",
    "25": "AM",
    "30": "MULTI CH",
}

#: ``LMD`` code -> name. Which are available depends on the incoming signal.
MODES: Dict[str, str] = {
    "00": "Stereo",
    "01": "Direct",
    "0C": "All Ch Stereo",
    "0D": "Theater-Dimensional",
    "0F": "Mono",
    "11": "Pure Audio",
    "13": "Full Mono",
    "40": "Dolby Digital",
    "80": "PLII Movie",
    "81": "PLII Music",
    "82": "Neo:6 Cinema",
    "83": "Neo:6 Music",
    "86": "PLII Game",
}

#: The listening mode a measurement should be taken in: no room correction, no
#: upmix, no bass management beyond what the receiver always applies. "Direct"
#: is the lever on a TX-SR806 -- the ISCP set here has no Audyssey on/off command.
MEASUREMENT_MODE = "01"


class OnkyoError(Exception):
    """A receiver command failed."""


class OnkyoUnavailable(OnkyoError):
    """The serial port could not be opened, or the receiver never answered."""


def mode_name(code: Optional[str]) -> str:
    if code is None:
        return "unknown"
    return MODES.get(code.upper(), f"code {code}")


def source_name(code: Optional[str]) -> str:
    if code is None:
        return "unknown"
    return SOURCES.get(code.upper(), f"code {code}")


def code_for(name: str, table: Dict[str, str]) -> str:
    """Resolve a name or a raw two-digit code against ``table``."""
    key = name.strip()
    for code, label in table.items():
        if label.lower() == key.lower():
            return code
    upper = key.upper()
    if len(upper) == 2 and all(c in "0123456789ABCDEF" for c in upper):
        return upper
    options = ", ".join(sorted(table.values()))
    raise OnkyoError(f"unknown value {name!r}; expected a two-digit code or one of: {options}")


class Preconditions(OnkyoError):
    """The receiver is not in a state where a measurement would be valid."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class Onkyo:
    """A synchronous ISCP connection, opened for the duration of a command.

    Unlike the Home Assistant integration this holds no background state: the
    CLI wants one question answered now, not a live entity, and keeping the
    port closed between commands leaves it free for anything else.
    """

    def __init__(
        self,
        port: str,
        timeout_s: float = 2.0,
        zero_db_raw: int = ZERO_DB_RAW,
        max_raw: int = DEFAULT_MAX_RAW,
    ) -> None:
        self.port = port
        self.timeout_s = timeout_s
        self.zero_db_raw = zero_db_raw
        self.max_raw = max_raw
        self._serial = None

    # --- transport ---
    def open(self) -> "Onkyo":
        try:
            import serial  # noqa: PLC0415 - optional dependency, like hidapi
        except ImportError:
            raise OnkyoUnavailable(
                "the 'pyserial' package is required to talk to the receiver (pip install pyserial)"
            ) from None
        try:
            self._serial = serial.Serial(
                self.port, 9600, bytesize=8, parity="N", stopbits=1, timeout=self.timeout_s, exclusive=True
            )
        except Exception as err:  # serial.SerialException and OS-level errors
            raise OnkyoUnavailable(
                f"can't open {self.port} ({err}) -- is the RS-232 adapter plugged in, and is anything "
                f"else (such as Home Assistant) holding the port?"
            ) from None
        return self

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def __enter__(self) -> "Onkyo":
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()

    def _port(self):
        if self._serial is None:
            raise OnkyoError("connection is not open")
        return self._serial

    def send(self, command: str) -> None:
        """Write one command, given without the ``!1`` prefix or terminator."""
        self._port().write(f"!1{command}\r".encode("ascii"))

    def _read_frame(self) -> Optional[str]:
        """Read one 0x1A-terminated frame, or None on timeout."""
        raw = self._port().read_until(TERMINATOR)
        if not raw.endswith(TERMINATOR):
            return None
        text = raw.rstrip(TERMINATOR).decode("ascii", errors="ignore")
        start = text.rfind("!1")
        return text[start + 2 :] if start >= 0 else None

    def query(self, command: str, retries: int = 1) -> Optional[str]:
        """Ask for one value. Returns None if the receiver won't say (e.g. in standby)."""
        name = command[:3].upper()
        for _ in range(retries + 1):
            self._port().reset_input_buffer()
            self.send(f"{name}QSTN")
            deadline = time.monotonic() + self.timeout_s
            # Unsolicited frames can arrive first, so read until ours shows up.
            while time.monotonic() < deadline:
                frame = self._read_frame()
                if frame is None:
                    break
                if frame[:3].upper() == name:
                    value = frame[3:]
                    return None if value == "N/A" else value
        return None

    def set(self, command: str, value: str) -> Optional[str]:
        """Send a set and return the value the receiver echoes back."""
        name = command[:3].upper()
        self._port().reset_input_buffer()
        self.send(f"{name}{value}")
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            frame = self._read_frame()
            if frame is None:
                break
            if frame[:3].upper() == name:
                echoed = frame[3:]
                return None if echoed == "N/A" else echoed
        return None

    # --- volume ---
    def raw_to_db(self, raw: int) -> float:
        return float(raw - self.zero_db_raw)

    def db_to_raw(self, db: float) -> int:
        return int(round(db + self.zero_db_raw))

    def volume_raw(self) -> Optional[int]:
        value = self.query("MVL")
        if value is None:
            return None
        try:
            return int(value, 16)
        except ValueError:
            return None

    def volume_db(self) -> Optional[float]:
        raw = self.volume_raw()
        return None if raw is None else self.raw_to_db(raw)

    def set_volume_raw(self, raw: int, allow_above_max: bool = False) -> int:
        if raw < 0 or raw > 0xFF:
            raise OnkyoError(f"volume raw {raw} is out of range")
        if raw > self.max_raw and not allow_above_max:
            raise OnkyoError(
                f"refusing to set volume raw {raw} ({self.raw_to_db(raw):+.0f} dB): above the cap of "
                f"{self.max_raw} ({self.raw_to_db(self.max_raw):+.0f} dB). Raise --max-raw if you mean it."
            )
        echoed = self.set("MVL", f"{raw:02X}")
        if echoed is None:
            raise OnkyoError("receiver did not acknowledge the volume change")
        got = int(echoed, 16)
        if got != raw:
            raise OnkyoError(f"volume did not take: asked for raw {raw}, receiver reports raw {got}")
        return got

    def set_volume_db(self, db: float, allow_above_max: bool = False) -> float:
        return self.raw_to_db(self.set_volume_raw(self.db_to_raw(db), allow_above_max))

    # --- state ---
    def power(self) -> Optional[bool]:
        value = self.query("PWR")
        return None if value not in ("00", "01") else value == "01"

    def muted(self) -> Optional[bool]:
        value = self.query("AMT")
        return None if value not in ("00", "01") else value == "01"

    def source(self) -> Optional[str]:
        return self.query("SLI")

    def mode(self) -> Optional[str]:
        return self.query("LMD")

    def set_source(self, code: str) -> Optional[str]:
        return self.set("SLI", code)

    def set_mode(self, code: str) -> Optional[str]:
        return self.set("LMD", code)

    def state(self) -> Dict[str, object]:
        """Everything the guard and the status command need, in one pass."""
        power = self.power()
        if power is None:
            raise OnkyoUnavailable(
                f"no reply from the receiver on {self.port} -- check it is powered at the mains, the "
                f"cable is right (a straight-through cable worked on a TX-SR806; otherwise try a "
                f"null-modem adapter), and that the adapter is the RS-232 one"
            )
        if not power:
            return {"power": False, "volume_raw": None, "volume_db": None, "muted": self.muted(),
                    "source": None, "mode": None}
        raw = self.volume_raw()
        return {
            "power": True,
            "volume_raw": raw,
            "volume_db": None if raw is None else self.raw_to_db(raw),
            "muted": self.muted(),
            "source": self.source(),
            "mode": self.mode(),
        }

    # --- the measurement guard ---
    def check(
        self,
        expect_source: Optional[str] = None,
        expect_mode: Optional[str] = MEASUREMENT_MODE,
        expect_volume_raw: Optional[int] = None,
    ) -> Dict[str, object]:
        """Raise Preconditions unless the receiver is fit to measure through.

        Everything is optional so a setup that doesn't need a given check can
        skip it. Returns the state it read, so a caller can log what it saw.
        """
        state = self.state()
        problems = []
        if not state["power"]:
            problems.append("the receiver is in standby")
        if state["muted"]:
            problems.append("the receiver is muted")
        if expect_source is not None and state["source"] != expect_source:
            problems.append(
                f"input is {source_name(state['source'])}, expected {source_name(expect_source)}"
            )
        if expect_mode is not None and state["mode"] != expect_mode:
            problems.append(
                f"listening mode is {mode_name(state['mode'])}, expected {mode_name(expect_mode)} "
                f"(room correction or an upmix would be measured instead of the room)"
            )
        if expect_volume_raw is not None and state["volume_raw"] != expect_volume_raw:
            problems.append(
                f"volume is raw {state['volume_raw']}, expected raw {expect_volume_raw}"
            )
        if problems:
            raise Preconditions(problems)
        return state


class LevelHold:
    """Set the receiver to a measurement level, then put it back.

    Used around a sweep so every measurement is taken at the same level and the
    user's listening volume is restored afterwards -- including when the loop is
    interrupted, which is when a forgotten measurement level is most annoying.
    """

    def __init__(self, onkyo: Onkyo, raw: int, allow_above_max: bool = False) -> None:
        self.onkyo = onkyo
        self.raw = raw
        self.allow_above_max = allow_above_max
        self.previous: Optional[int] = None

    def __enter__(self) -> "LevelHold":
        self.previous = self.onkyo.volume_raw()
        self.onkyo.set_volume_raw(self.raw, self.allow_above_max)
        return self

    def __exit__(self, *_exc) -> None:
        if self.previous is not None and self.previous != self.raw:
            try:
                self.onkyo.set_volume_raw(self.previous, allow_above_max=True)
            except OnkyoError:
                pass
