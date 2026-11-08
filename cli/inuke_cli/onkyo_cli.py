"""The ``inuke onkyo`` subcommand: the AV receiver as the measurement level control."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .onkyo import (
    DEFAULT_MAX_RAW,
    MEASUREMENT_MODE,
    MODES,
    SOURCES,
    ZERO_DB_RAW,
    Onkyo,
    OnkyoError,
    Preconditions,
    code_for,
    mode_name,
    source_name,
)

#: Set INUKE_ONKYO_PORT to avoid passing --port every time.
ENV_PORT = "INUKE_ONKYO_PORT"


def default_port() -> Optional[str]:
    return os.environ.get(ENV_PORT)


def add_parser(sub) -> None:
    p = sub.add_parser(
        "onkyo",
        help="AV receiver over RS-232: the measurement level control for the room-EQ loop",
        description=(
            "Control an Onkyo receiver over RS-232. The iNuke's own gain is read-only, so on a "
            "receiver-fed setup this is the only level in the signal path that can be set remotely: "
            "it is what makes a repeatable measurement level possible."
        ),
    )
    p.add_argument(
        "--port",
        default=None,
        help=f"serial port, e.g. COM3 or /dev/ttyUSB0 (default: ${ENV_PORT})",
    )
    p.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for a reply")
    p.add_argument(
        "--zero-db-raw",
        type=int,
        default=ZERO_DB_RAW,
        help=f"raw MVL value the receiver shows as 0 dB (default {ZERO_DB_RAW}, a TX-SR806)",
    )
    p.add_argument(
        "--max-raw",
        type=int,
        default=DEFAULT_MAX_RAW,
        help=f"refuse to command a level above this raw value (default {DEFAULT_MAX_RAW})",
    )
    osub = p.add_subparsers(dest="onkyo_command", metavar="subcommand")

    osub.add_parser("status", help="show power, volume, input and listening mode")

    vol = osub.add_parser("volume", help="get or set the master volume")
    vol.add_argument("level", nargs="?", help="dB (e.g. -40, -32.5) or raw:NN for the raw MVL value")
    vol.add_argument(
        "--force", action="store_true", help="allow a level above --max-raw"
    )

    src = osub.add_parser("input", help="get or set the input")
    src.add_argument("name", nargs="?", help=f"name or two-digit code ({', '.join(sorted(SOURCES.values()))})")

    mode = osub.add_parser("mode", help="get or set the listening mode")
    mode.add_argument("name", nargs="?", help=f"name or two-digit code ({', '.join(sorted(MODES.values()))})")

    chk = osub.add_parser(
        "check",
        help="verify the receiver is fit to measure through, and exit non-zero if not",
        description=(
            "Checks the receiver is on, unmuted, on the expected input and in a listening mode that "
            "does not apply room correction or an upmix. Run this before a sweep so a measurement is "
            "never silently taken through Audyssey or All Channel Stereo."
        ),
    )
    chk.add_argument("--expect-input", default=None, help="required input, by name or code")
    chk.add_argument(
        "--expect-mode",
        default=mode_name(MEASUREMENT_MODE),
        help=f"required listening mode (default {mode_name(MEASUREMENT_MODE)}; 'any' to skip)",
    )
    chk.add_argument("--expect-volume", default=None, help="required level, as dB or raw:NN")


def _parse_level(text: str, amp: Onkyo) -> int:
    """Accept '-40', '-40.0' or 'raw:42' and return a raw MVL value."""
    cleaned = text.strip()
    if cleaned.lower().startswith("raw:"):
        try:
            return int(cleaned[4:], 10)
        except ValueError:
            raise OnkyoError(f"not a raw value: {text!r}") from None
    try:
        return amp.db_to_raw(float(cleaned))
    except ValueError:
        raise OnkyoError(f"not a level: {text!r} (expected dB such as -40, or raw:42)") from None


def _show(amp: Onkyo) -> None:
    state = amp.state()
    if not state["power"]:
        print("Receiver: standby")
        return
    raw, db = state["volume_raw"], state["volume_db"]
    level = "unknown" if raw is None else f"{db:+.0f} dB (raw {raw})"
    print(f"Receiver: on{'  [MUTED]' if state['muted'] else ''}")
    print(f"  volume: {level}")
    print(f"  input:  {source_name(state['source'])}")
    print(f"  mode:   {mode_name(state['mode'])}")


def run(args) -> int:
    port = args.port or default_port()
    if not port:
        print(
            f"No serial port given. Pass --port (e.g. --port COM3) or set {ENV_PORT}.",
            file=sys.stderr,
        )
        return 2
    command = getattr(args, "onkyo_command", None)
    if not command:
        print("Pick a subcommand: status, volume, input, mode, check", file=sys.stderr)
        return 2

    with Onkyo(port, timeout_s=args.timeout, zero_db_raw=args.zero_db_raw, max_raw=args.max_raw) as amp:
        if command == "status":
            _show(amp)
            return 0

        if command == "volume":
            if args.level is None:
                db = amp.volume_db()
                if db is None:
                    print("Volume is unavailable (the receiver is probably in standby).")
                    return 1
                print(f"{db:+.0f} dB (raw {amp.db_to_raw(db)})")
                return 0
            raw = _parse_level(args.level, amp)
            before = amp.volume_raw()
            amp.set_volume_raw(raw, allow_above_max=args.force)
            was = "" if before is None else f" (was {amp.raw_to_db(before):+.0f} dB)"
            print(f"Volume set to {amp.raw_to_db(raw):+.0f} dB (raw {raw}){was}")
            return 0

        if command == "input":
            if args.name is None:
                print(source_name(amp.source()))
                return 0
            code = code_for(args.name, SOURCES)
            amp.set_source(code)
            print(f"Input set to {source_name(code)}")
            return 0

        if command == "mode":
            if args.name is None:
                print(mode_name(amp.mode()))
                return 0
            code = code_for(args.name, MODES)
            amp.set_mode(code)
            print(f"Listening mode set to {mode_name(code)}")
            return 0

        if command == "check":
            expect_source = code_for(args.expect_input, SOURCES) if args.expect_input else None
            if str(args.expect_mode).lower() == "any":
                expect_mode = None
            else:
                expect_mode = code_for(args.expect_mode, MODES)
            expect_volume = _parse_level(args.expect_volume, amp) if args.expect_volume else None
            try:
                amp.check(expect_source, expect_mode, expect_volume)
            except Preconditions as err:
                print("Not ready to measure:", file=sys.stderr)
                for problem in err.problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            print("Receiver is ready to measure.")
            _show(amp)
            return 0

    return 2


def main_error(err: OnkyoError) -> int:
    print(f"Receiver error: {err}", file=sys.stderr)
    return 4
