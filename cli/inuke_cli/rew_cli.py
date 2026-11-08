"""`inuke rew ...`: the Room EQ Wizard integration commands. See
room_eq.py for how the measure/fit/apply loop works."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import constants as C
from .protocol import INukeClient
from .rew import AMP_BANDS, DEFAULT_URL, EQUALISER, RewClient, RewError, amp_bands_to_rew, rew_filters_to_amp
from . import room_eq
from . import onkyo
from . import onkyo_cli
from .room_eq import FitSettings


def _range_type(s: str) -> tuple[int, int]:
    try:
        return room_eq.parse_range(s)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err))


def _shape_type(s: str) -> str:
    try:
        return room_eq.parse_shape(s)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err))


def _add_shelf_option(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--shelf-freq",
        choices=["midpoint", "corner"],
        default="midpoint",
        help="how the amp defines a shelf's frequency: midpoint (RBJ-style, default) or corner (as REW does)",
    )


def _add_fit_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("fit settings (default: whatever REW's EQ window has)")
    g.add_argument("--range", type=_range_type, metavar="LO-HI", help="frequency range to correct, e.g. 20-300")
    g.add_argument("--max-boost", type=int, metavar="DB", help="max boost per filter")
    g.add_argument("--overall-max-boost", type=int, metavar="DB", help="max total boost")
    g.add_argument("--flatness", type=int, metavar="DB", help="stop adding filters once within this many dB (1-6)")
    g.add_argument("--shelves", action=argparse.BooleanOptionalAction, default=None, help="let REW use shelf filters")
    g.add_argument("--shape", type=_shape_type, metavar="SHAPE", help=f"target shape: {', '.join(room_eq.SHAPES)}")
    g.add_argument("--lf-cutoff", type=int, metavar="HZ", help="target's low-frequency cutoff")
    g.add_argument("--bm-cutoff", type=int, metavar="HZ", help="subwoofer target's low-pass frequency (match the amp's crossover)")
    g.add_argument("--bm-slope", type=int, choices=[6, 12, 18, 24, 30, 36, 42, 48], metavar="DB", help="subwoofer target's low-pass slope, dB/oct")
    g.add_argument("--target-level", type=float, metavar="DB", help="target level in dB SPL (default: REW calculates it)")
    g.add_argument("--max-q", type=float, default=room_eq.AMP_Q_RANGE[1], metavar="Q", help="clamp filter Q to this (default %(default)s)")
    g.add_argument("--house-curve", metavar="FILE", help="set REW's house curve file (applies to REW globally)")
    _add_shelf_option(g)


def _settings_from_args(args: argparse.Namespace) -> FitSettings:
    lo, hi = args.range if args.range else (None, None)
    return FitSettings(
        shape=args.shape,
        lf_cutoff_hz=args.lf_cutoff,
        bm_cutoff_hz=args.bm_cutoff,
        bm_slope_db=args.bm_slope,
        lo_hz=lo,
        hi_hz=hi,
        max_boost_db=args.max_boost,
        overall_max_boost_db=args.overall_max_boost,
        flatness_db=args.flatness,
        shelves=args.shelves,
        target_level_db=args.target_level,
        max_q=args.max_q,
        shelf_midpoint=args.shelf_freq == "midpoint",
    )


def _add_onkyo_options(p: argparse.ArgumentParser) -> None:
    """Drive the AV receiver that feeds the amp, if there is one on RS-232.

    The amp's own gain is read-only, so the receiver's master volume is the only
    level in the path that can be set remotely -- which is what makes a
    repeatable measurement level possible.
    """
    g = p.add_argument_group("AV receiver (RS-232)")
    g.add_argument(
        "--onkyo-port",
        metavar="PORT",
        default=None,
        help=f"serial port of an Onkyo receiver, e.g. COM3 (default: ${onkyo_cli.ENV_PORT}). "
        f"Without this the receiver is not touched and you set the level by hand.",
    )
    g.add_argument(
        "--onkyo-level",
        metavar="LEVEL",
        default=None,
        help="measurement level, as dB (e.g. -35) or raw:NN; set before each sweep and restored after",
    )
    g.add_argument("--onkyo-input", metavar="NAME", default=None, help="require this input, e.g. DVD")
    g.add_argument(
        "--onkyo-mode",
        metavar="NAME",
        default=onkyo.mode_name(onkyo.MEASUREMENT_MODE),
        help="require this listening mode (default %(default)s; 'any' to skip the check)",
    )
    g.add_argument(
        "--onkyo-max-raw",
        type=int,
        default=onkyo.DEFAULT_MAX_RAW,
        help="refuse to command a level above this raw value (default %(default)s)",
    )


def _guarded(measurer, args):
    """Wrap `measurer` so the receiver is checked and the level held, if asked."""
    port = getattr(args, "onkyo_port", None) or onkyo_cli.default_port()
    if not port:
        return measurer, None
    receiver = onkyo.Onkyo(port, max_raw=args.onkyo_max_raw).open()
    mode = None if str(args.onkyo_mode).lower() == "any" else onkyo.code_for(args.onkyo_mode, onkyo.MODES)
    source = onkyo.code_for(args.onkyo_input, onkyo.SOURCES) if args.onkyo_input else None
    level = None
    if args.onkyo_level:
        text = str(args.onkyo_level).strip()
        level = int(text[4:], 10) if text.lower().startswith("raw:") else receiver.db_to_raw(float(text))
    print(f"Receiver on {port}: preconditions enforced before every sweep.")
    return room_eq.ReceiverGuarded(measurer, receiver, level, source, mode), receiver


def add_parser(sub) -> None:
    rew_p = sub.add_parser("rew", help="Room EQ Wizard integration: measure, fit EQ, apply to the amp")
    rew_p.add_argument("--url", default=DEFAULT_URL, help="REW API address (default %(default)s)")
    rew_sub = rew_p.add_subparsers(dest="rew_command", required=True)

    rew_sub.add_parser("status", help="check REW's API and list its measurements")

    loop_p = rew_sub.add_parser("loop", help="interactive measure -> fit -> apply -> verify loop for one channel")
    loop_p.add_argument("--channel", type=int, choices=C.CHANNELS, required=True)
    loop_p.add_argument(
        "--measure",
        choices=["auto", "api", "manual"],
        default="auto",
        help="start sweeps over the API (needs REW Pro), or click Measure in REW yourself; auto picks (default)",
    )
    loop_p.add_argument("--log", metavar="FILE", help="session log (default: rew-eq-ch<N>-<time>.json)")
    loop_p.add_argument("--simulate", action="store_true", help="use a simulated amp and room (REW is still real)")
    loop_p.add_argument("-y", "--yes", action="store_true", help="no prompts: one measure/fit/apply/verify pass, then stop")
    _add_onkyo_options(loop_p)
    _add_fit_options(loop_p)

    fit_p = rew_sub.add_parser("fit", help="fit EQ to an existing REW measurement (taken as the uncorrected room)")
    fit_p.add_argument("measurement", help="REW measurement index (from 1) or UUID")
    fit_p.add_argument("--channel", type=int, choices=C.CHANNELS, help="with --apply: channel to write to")
    fit_p.add_argument("--apply", action="store_true", help="write the result to the amp")
    fit_p.add_argument("-y", "--yes", action="store_true", help="don't prompt before writing")
    _add_fit_options(fit_p)

    push_p = rew_sub.add_parser("push", help="write a REW measurement's current EQ filters to the amp")
    push_p.add_argument("measurement", help="REW measurement index (from 1) or UUID")
    push_p.add_argument("--channel", type=int, choices=C.CHANNELS, required=True)
    push_p.add_argument("--max-q", type=float, default=room_eq.AMP_Q_RANGE[1], metavar="Q")
    _add_shelf_option(push_p)
    push_p.add_argument("-y", "--yes", action="store_true", help="don't prompt before writing")

    pull_p = rew_sub.add_parser("pull", help="copy the amp's PEQ into a REW measurement's EQ filters")
    pull_p.add_argument("measurement", help="REW measurement index (from 1) or UUID")
    pull_p.add_argument("--channel", type=int, choices=C.CHANNELS, required=True)
    _add_shelf_option(pull_p)


def _open_amp():
    client = INukeClient()
    client.go_online()
    return client


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def run(args: argparse.Namespace) -> int:
    rew = RewClient(args.url)
    cmd = args.rew_command

    if cmd == "status":
        return _status(rew, args.json)

    rew.version()  # fail early with a clear message if REW isn't reachable
    rew.enable_blocking()
    if getattr(args, "house_curve", None):
        rew.set_house_curve(args.house_curve)

    if cmd == "loop":
        return _loop(rew, args)
    if cmd == "fit":
        return _fit(rew, args)
    if cmd == "push":
        return _push(rew, args)
    if cmd == "pull":
        return _pull(rew, args)
    raise AssertionError(cmd)


def _status(rew: RewClient, as_json: bool) -> int:
    info = {"url": rew.base_url, "version": rew.version(), "pro": rew.has_pro()}
    ms = rew.measurements()
    if as_json:
        info["measurements"] = ms
        print(json.dumps(info, indent=2))
        return 0
    print(f"REW API at {info['url']}: {info['version']}")
    print(f"Pro licence (needed to start sweeps from here): {'yes' if info['pro'] else 'no'}")
    print(f"{len(ms)} measurement(s)" + (":" if ms else ""))
    for idx, m in sorted(ms.items(), key=lambda kv: int(kv[0])):
        print(f"  {idx:>3}  {m['title']:<45} {m['uuid']}")
    return 0


def _loop(rew: RewClient, args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    log_path = args.log or f"rew-eq-ch{args.channel}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    if args.simulate:
        amp = room_eq.SimulatedAmp()
        measurer = room_eq.SimulatedRoom(amp, args.channel)
        print("Simulating the amp and the room; results go into REW as imported measurements.")
    else:
        amp = _open_amp()
        measurer = {
            "auto": room_eq.AutoMeasurer,
            "api": room_eq.ApiMeasurer,
            "manual": room_eq.ManualMeasurer,
        }[args.measure]()
    receiver = None
    try:
        measurer, receiver = _guarded(measurer, args)
        session = room_eq.RoomEqSession(rew, amp, args.channel, measurer, settings, log_path=log_path)
        print(f"REW {session.log.rew_version}; session log: {log_path}")
        return room_eq.run_loop(session, assume_yes=args.yes)
    finally:
        if receiver is not None:
            receiver.close()
        if not args.simulate:
            amp.close()


def _fit(rew: RewClient, args: argparse.Namespace) -> int:
    if args.apply and args.channel is None:
        raise SystemExit("rew fit: --apply needs --channel")
    result = room_eq.fit_to_target(rew, args.measurement, _settings_from_args(args))
    if args.json:
        print(json.dumps({
            "bands": result.mapped.bands,
            "notes": result.mapped.notes,
            "settings": result.target_desc,
            "before": room_eq._dev(result.before),
            "predicted": room_eq._dev(result.predicted),
        }, indent=2))
    else:
        print(result.target_desc)
        print(room_eq.format_bands(result.mapped.bands))
        for note in result.mapped.notes:
            print(f"note: {note}")
        print(f"room vs target, no EQ:   {room_eq.format_dev(result.before)}")
        print(f"predicted with this EQ:  {room_eq.format_dev(result.predicted)}")
    if args.apply:
        return _write(args.channel, result.mapped.bands, args.yes)
    return 0


def _push(rew: RewClient, args: argparse.Namespace) -> int:
    mapped = rew_filters_to_amp(rew.filters(args.measurement), args.max_q, args.shelf_freq == "midpoint")
    print(room_eq.format_bands(mapped.bands))
    for note in mapped.notes:
        print(f"note: {note}")
    return _write(args.channel, mapped.bands, args.yes)


def _write(channel: int, bands: list, assume_yes: bool) -> int:
    if not _confirm(f"Write these to channel {channel}'s PEQ? This replaces all {AMP_BANDS} bands.", assume_yes):
        print("Aborted.")
        return 1
    with _open_amp() as amp:
        room_eq.write_bands(amp, channel, bands)
    print(f"Written to channel {channel}.")
    return 0


def _pull(rew: RewClient, args: argparse.Namespace) -> int:
    with _open_amp() as amp:
        bands = room_eq.read_bands(amp, args.channel)
    print(room_eq.format_bands(bands))
    rew.post(f"/measurements/{args.measurement}/equaliser", EQUALISER)
    slots = len(rew.filters(args.measurement))
    rew.set_filters(args.measurement, amp_bands_to_rew(bands, slots, args.shelf_freq == "midpoint"))
    print(f"Copied into REW measurement {args.measurement}'s EQ (see REW's EQ window for the predicted response).")
    return 0


def main_error(err: RewError) -> int:
    print(f"error: {err}", file=sys.stderr)
    return 4
