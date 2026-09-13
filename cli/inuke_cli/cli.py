"""Command-line interface for controlling an iNuke DSP amp directly over USB.

See docs/PROTOCOL_NOTES.md for the protocol this talks, and README.md (in
this directory) for usage examples. Every subcommand opens the amp, does one
thing, and closes it again -- this is a stateless CLI, not a persistent
session.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from . import constants as C
from .protocol import DeviceNotFoundError, DeviceTimeoutError, INukeClient
from . import snapshot


def _print_progress(i: int, total: int, key: str) -> None:
    sys.stderr.write(f"\r  {i}/{total} {key:<20}")
    sys.stderr.flush()
    if i == total:
        sys.stderr.write("\n")


def _output(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2))
        return
    if isinstance(value, dict):
        for k, v in value.items():
            print(f"{k}: {v}")
    else:
        print(value)


def _amp_mode_type(s: str) -> str:
    s = s.upper()
    if s not in C.AMP_MODES:
        raise argparse.ArgumentTypeError(f"mode must be one of {', '.join(C.AMP_MODES)}")
    return s


def _peq_type(s: str) -> str:
    s = s.upper()
    if s not in C.PEQ_TYPES:
        raise argparse.ArgumentTypeError(f"PEQ type must be one of {', '.join(C.PEQ_TYPES)}")
    return s


def _deq_type(s: str) -> str:
    s = s.upper()
    if s not in C.DEQ_FILT_TYPES:
        raise argparse.ArgumentTypeError(f"DEQ filter type must be one of {', '.join(C.DEQ_FILT_TYPES)}")
    return s


def _xover_type(s: str) -> str:
    s = s.upper()
    if s == "OFF":
        return s
    import re

    m = re.fullmatch(r"([A-Z]+)(\d+)", s)
    if not m or m.group(1) not in C.XOVER_FAMILIES or int(m.group(2)) not in C.XOVER_SLOPES:
        raise argparse.ArgumentTypeError(
            f"crossover type must be OFF or <FAMILY><SLOPE>, e.g. BUT24 "
            f"(families: {'/'.join(C.XOVER_FAMILIES)}; slopes: {'/'.join(map(str, C.XOVER_SLOPES))})"
        )
    return s


def _bounded_float(bound_key: str):
    """Conservative, undocumented-device-limit guesses -- see constants.BOUNDS."""
    lo, hi = C.BOUNDS[bound_key]

    def validator(s: str) -> float:
        try:
            v = float(s)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{s!r} is not a number")
        if not (lo <= v <= hi):
            raise argparse.ArgumentTypeError(f"{bound_key.replace('_', ' ')} must be between {lo} and {hi} (got {v})")
        return v

    return validator


def _max_len_str(maxlen: int):
    def validator(s: str) -> str:
        if len(s) > maxlen:
            raise argparse.ArgumentTypeError(f"{s!r} is too long ({len(s)} chars, max {maxlen})")
        return s

    return validator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inuke", description="Control a Behringer iNuke DSP amp directly over USB.")
    p.add_argument("--json", action="store_true", help="output machine-readable JSON instead of plain text")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show device name and firmware version")
    sub.add_parser("status", help="full parameter dump (like the vendor app's connect sweep)")
    sub.add_parser("gain", help="show gain/mute (read-only -- SET does not stick on real hardware)")
    sub.add_parser("online", help="send /online (also required once before most GETs reply)")
    sub.add_parser("offline", help="send /offline (device stops replying to GETs until /online)")

    mode_p = sub.add_parser("mode", help="get or set amp mode")
    mode_p.add_argument("value", nargs="?", type=_amp_mode_type, help=f"one of {', '.join(C.AMP_MODES)}; omit to just read it")

    name_p = sub.add_parser("name", help="get or set the amp's display name")
    name_p.add_argument("value", nargs="?", type=_max_len_str(C.AMP_NAME_MAX_LEN), help="new name; omit to just read it")

    peq_p = sub.add_parser("peq", help="get or set a parametric EQ band")
    peq_p.add_argument("channel", type=int, choices=C.CHANNELS)
    peq_p.add_argument("band", type=int, choices=list(C.PEQ_BANDS))
    peq_p.add_argument("type", nargs="?", type=_peq_type)
    peq_p.add_argument("freq", nargs="?", type=_bounded_float("freq_hz"))
    peq_p.add_argument("gain", nargs="?", type=_bounded_float("gain_db"))
    peq_p.add_argument("q", nargs="?", type=_bounded_float("q"))

    xover_p = sub.add_parser("xover", help="crossover: high-pass, low-pass, gain")
    xover_sub = xover_p.add_subparsers(dest="xover_command", required=True)
    hp_p = xover_sub.add_parser("hp", help="get or set high-pass filter")
    hp_p.add_argument("channel", type=int, choices=C.CHANNELS)
    hp_p.add_argument("type", nargs="?", type=_xover_type)
    hp_p.add_argument("freq", nargs="?", type=_bounded_float("freq_hz"))
    lp_p = xover_sub.add_parser("lp", help="get or set low-pass filter")
    lp_p.add_argument("channel", type=int, choices=C.CHANNELS)
    lp_p.add_argument("type", nargs="?", type=_xover_type)
    lp_p.add_argument("freq", nargs="?", type=_bounded_float("freq_hz"))
    xg_p = xover_sub.add_parser("gain", help="get or set crossover gain (dB)")
    xg_p.add_argument("channel", type=int, choices=C.CHANNELS)
    xg_p.add_argument("db", nargs="?", type=_bounded_float("gain_db"))

    deq_p = sub.add_parser("deq", help="dynamic EQ: sidechain filter, compressor, timing")
    deq_sub = deq_p.add_subparsers(dest="deq_command", required=True)
    filt_p = deq_sub.add_parser("filt", help="get or set the sidechain filter")
    filt_p.add_argument("channel", type=int, choices=C.CHANNELS)
    filt_p.add_argument("band", type=int, choices=list(C.DEQ_BANDS))
    filt_p.add_argument("type", nargs="?", type=_deq_type)
    filt_p.add_argument("freq", nargs="?", type=_bounded_float("freq_hz"))
    filt_p.add_argument("q", nargs="?", type=_bounded_float("q"))
    comp_p = deq_sub.add_parser("comp", help="get or set the compressor")
    comp_p.add_argument("channel", type=int, choices=C.CHANNELS)
    comp_p.add_argument("band", type=int, choices=list(C.DEQ_BANDS))
    comp_p.add_argument("gain", nargs="?", type=_bounded_float("gain_db"))
    comp_p.add_argument("threshold", nargs="?", type=_bounded_float("threshold_db"))
    comp_p.add_argument("ratio", nargs="?", type=_bounded_float("ratio"))
    time_p = deq_sub.add_parser("time", help="get or set attack/release timing")
    time_p.add_argument("channel", type=int, choices=C.CHANNELS)
    time_p.add_argument("band", type=int, choices=list(C.DEQ_BANDS))
    time_p.add_argument("attack", nargs="?", type=_bounded_float("time_ms"))
    time_p.add_argument("release", nargs="?", type=_bounded_float("time_ms"))

    delay_p = sub.add_parser("delay", help="get or set delay time and phase")
    delay_p.add_argument("channel", type=int, choices=C.CHANNELS)
    delay_p.add_argument("ms", nargs="?", type=_bounded_float("delay_ms"))
    delay_p.add_argument("phase", nargs="?", type=int, choices=[0, 180])

    lim_p = sub.add_parser("limiter", help="get or set the limiter")
    lim_p.add_argument("channel", type=int, choices=C.CHANNELS)
    lim_p.add_argument("threshold_vp", nargs="?", type=_bounded_float("limiter_threshold_vp"), help="threshold in peak volts, not dBFS")
    lim_p.add_argument("release_ms", nargs="?", type=_bounded_float("time_ms"))
    lim_p.add_argument("hold_ms", nargs="?", type=_bounded_float("time_ms"))

    preset_p = sub.add_parser("preset", help="the amp's 20 onboard preset slots")
    preset_sub = preset_p.add_subparsers(dest="preset_command", required=True)
    preset_sub.add_parser("list", help="list all 20 slots")
    store_p = preset_sub.add_parser("store", help="snapshot the amp's current full state into a slot")
    store_p.add_argument("slot", type=int, choices=range(1, C.PRESET_SLOT_COUNT + 1))
    store_p.add_argument("name", type=_max_len_str(C.PRESET_NAME_MAX_LEN))
    store_p.add_argument("--mode", type=_amp_mode_type, help="ampmode to record with the preset (default: current mode)")
    store_p.add_argument("-y", "--yes", action="store_true", help="don't prompt for confirmation")
    recall_p = preset_sub.add_parser("recall", help="replace the amp's entire live state with a stored slot")
    recall_p.add_argument("slot", type=int, choices=range(1, C.PRESET_SLOT_COUNT + 1))
    recall_p.add_argument("-y", "--yes", action="store_true", help="don't prompt for confirmation")

    meter_p = sub.add_parser("meter", help="stream live meter telemetry")
    meter_p.add_argument("--seconds", type=float, default=10.0)

    monitor_p = sub.add_parser("monitor", help="passively print every message the amp sends (debugging)")
    monitor_p.add_argument("--seconds", type=float, default=30.0)

    backup_p = sub.add_parser("backup", help="save the amp's full live DSP state to a JSON file")
    backup_p.add_argument("file")

    restore_p = sub.add_parser("restore", help="push a JSON snapshot back onto the amp (overwrites live state)")
    restore_p.add_argument("file")
    restore_p.add_argument("-y", "--yes", action="store_true", help="don't prompt for confirmation")

    raw_p = sub.add_parser("raw", help="escape hatch: send an arbitrary OSC address")
    raw_p.add_argument("address")
    raw_p.add_argument("--type", default="", dest="typetags", help="OSC typetags, e.g. sfff (empty = GET)")
    raw_p.add_argument("--args", nargs="*", default=[], help="args matching --type, in order")
    raw_p.add_argument("--timeout", type=float, default=2.0)

    return p


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    reply = input(f"{prompt} [y/N] ")
    return reply.strip().lower() in ("y", "yes")


def _coerce_raw_args(typetags: str, raw_args: list[str]) -> list:
    if len(raw_args) != len(typetags):
        raise SystemExit(f"--args has {len(raw_args)} value(s) but --type {typetags!r} declares {len(typetags)}")
    out = []
    for t, v in zip(typetags, raw_args):
        if t == "f":
            out.append(float(v))
        elif t == "i":
            out.append(int(v))
        elif t == "s":
            out.append(v)
        else:
            raise SystemExit(f"unsupported typetag {t!r}")
    return out


def run(args: argparse.Namespace) -> int:
    as_json = args.json

    if args.command == "backup":
        with INukeClient() as client:
            data = snapshot.capture(client, on_progress=_print_progress)
        with open(args.file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote snapshot to {args.file}")
        return 0

    if args.command == "restore":
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not _confirm(f"Restore {args.file} onto the amp? This overwrites the amp's entire live DSP state.", args.yes):
            print("Aborted.")
            return 1
        with INukeClient() as client:
            snapshot.restore(client, data, on_progress=_print_progress)
        print("Restore complete.")
        return 0

    with INukeClient() as client:
        if args.command == "info":
            _output(client.get_info(), as_json)

        elif args.command == "status":
            data = client.full_sync(on_progress=_print_progress)
            _output(data, as_json)

        elif args.command == "gain":
            _output(client.get_gain(), as_json)

        elif args.command == "online":
            client.go_online()
            print("Sent /online")

        elif args.command == "offline":
            client.go_offline()
            print("Sent /offline (GETs will stop replying until /online)")

        elif args.command == "mode":
            if args.value is None:
                _output(client.get_amp_mode(), as_json)
            else:
                client.set_amp_mode(args.value)
                print(f"Amp mode -> {args.value}")

        elif args.command == "name":
            if args.value is None:
                _output(client.get_info()["amp_name"], as_json)
            else:
                client.set_amp_name(args.value)
                print(f'Amp name -> "{args.value}"')

        elif args.command == "peq":
            fields = (args.type, args.freq, args.gain, args.q)
            if all(v is None for v in fields):
                _output(client.get_peq(args.channel, args.band), as_json)
            elif any(v is None for v in fields):
                raise SystemExit("peq: provide all four of type freq gain q to set a band, or none to read it")
            else:
                client.set_peq(args.channel, args.band, args.type, args.freq, args.gain, args.q)
                print(f"Ch{args.channel} PEQ{args.band} -> {args.type} {args.freq}Hz {args.gain}dB Q{args.q}")

        elif args.command == "xover":
            if args.xover_command in ("hp", "lp"):
                getter = client.get_xover_hp if args.xover_command == "hp" else client.get_xover_lp
                setter = client.set_xover_hp if args.xover_command == "hp" else client.set_xover_lp
                if args.type is None and args.freq is None:
                    _output(getter(args.channel), as_json)
                elif args.type is None or args.freq is None:
                    raise SystemExit(f"xover {args.xover_command}: provide both type and freq to set, or neither to read")
                else:
                    setter(args.channel, args.type, args.freq)
                    print(f"Ch{args.channel} {args.xover_command.upper()} -> {args.type} @ {args.freq}Hz")
            elif args.xover_command == "gain":
                if args.db is None:
                    _output(client.get_xover_gain(args.channel), as_json)
                else:
                    client.set_xover_gain(args.channel, args.db)
                    print(f"Ch{args.channel} xover gain -> {args.db}dB")

        elif args.command == "deq":
            if args.deq_command == "filt":
                if args.type is None and args.freq is None and args.q is None:
                    _output(client.get_deq_filt(args.channel, args.band), as_json)
                elif None in (args.type, args.freq, args.q):
                    raise SystemExit("deq filt: provide type freq q to set, or none to read")
                else:
                    client.set_deq_filt(args.channel, args.band, args.type, args.freq, args.q)
                    print(f"Ch{args.channel} DEQ{args.band} filt -> {args.type} {args.freq}Hz Q{args.q}")
            elif args.deq_command == "comp":
                if args.gain is None and args.threshold is None and args.ratio is None:
                    _output(client.get_deq_comp(args.channel, args.band), as_json)
                elif None in (args.gain, args.threshold, args.ratio):
                    raise SystemExit("deq comp: provide gain threshold ratio to set, or none to read")
                else:
                    client.set_deq_comp(args.channel, args.band, args.gain, args.threshold, args.ratio)
                    print(f"Ch{args.channel} DEQ{args.band} comp -> gain={args.gain}dB thr={args.threshold}dB ratio=1:{args.ratio}")
            elif args.deq_command == "time":
                if args.attack is None and args.release is None:
                    _output(client.get_deq_time(args.channel, args.band), as_json)
                elif None in (args.attack, args.release):
                    raise SystemExit("deq time: provide attack and release to set, or neither to read")
                else:
                    client.set_deq_time(args.channel, args.band, args.attack, args.release)
                    print(f"Ch{args.channel} DEQ{args.band} time -> atk={args.attack}ms rel={args.release}ms")

        elif args.command == "delay":
            if args.ms is None and args.phase is None:
                _output(client.get_delay(args.channel), as_json)
            elif args.ms is None or args.phase is None:
                raise SystemExit("delay: provide both ms and phase to set, or neither to read")
            else:
                client.set_delay(args.channel, args.ms, args.phase)
                print(f"Ch{args.channel} delay -> {args.ms}ms @ {args.phase}deg")

        elif args.command == "limiter":
            fields = (args.threshold_vp, args.release_ms, args.hold_ms)
            if all(v is None for v in fields):
                _output(client.get_limiter(args.channel), as_json)
            elif any(v is None for v in fields):
                raise SystemExit("limiter: provide threshold_vp release_ms hold_ms to set, or none to read")
            else:
                client.set_limiter(args.channel, args.threshold_vp, args.release_ms, args.hold_ms)
                print(f"Ch{args.channel} limiter -> thr={args.threshold_vp}Vp rel={args.release_ms}ms hold={args.hold_ms}ms")

        elif args.command == "preset":
            if args.preset_command == "list":
                rows = [client.get_preset_name(slot) for slot in range(1, C.PRESET_SLOT_COUNT + 1)]
                if as_json:
                    _output(rows, True)
                else:
                    for r in rows:
                        mode = C.AMP_MODE_BY_ENUM[r["mode_enum"]] if r["mode_enum"] < len(C.AMP_MODE_BY_ENUM) else "?"
                        print(f"{r['slot']:>2}  {r['name']:<20} {mode}")
            elif args.preset_command == "store":
                mode_enum = C.AMP_MODE_ENUM[args.mode] if args.mode else C.AMP_MODE_ENUM[client.get_amp_mode()]
                if not _confirm(f'Store current state to slot {args.slot} as "{args.name}"? This overwrites what\'s there.', args.yes):
                    print("Aborted.")
                    return 1
                client.save_preset(args.slot, mode_enum, args.name)
                print(f'Stored slot {args.slot} as "{args.name}"')
            elif args.preset_command == "recall":
                row = client.get_preset_name(args.slot)
                if not _confirm(f'Recall slot {args.slot} ("{row["name"]}")? This replaces the amp\'s entire live state.', args.yes):
                    print("Aborted.")
                    return 1
                client.load_preset(args.slot, row["name"])
                print(f"Recalled slot {args.slot}")

        elif args.command == "meter":
            client.meter_heartbeat()
            print("Streaming /meter (Ctrl+C to stop)...", file=sys.stderr)
            try:
                import time as _time

                end = _time.time() + args.seconds
                while _time.time() < end:
                    for msg in client.poll(timeout_s=0.5):
                        if msg["addr"] == "/meter" and msg["typetags"] == "ffff":
                            a = msg["args"]
                            if as_json:
                                print(json.dumps({"inputA": a[0], "inputB": a[1], "outputA": a[2], "outputB": a[3]}))
                            else:
                                print(f"in A={a[0]:.4f} B={a[1]:.4f}   out A={a[2]:.4f} B={a[3]:.4f}")
            except KeyboardInterrupt:
                pass

        elif args.command == "monitor":
            print("Listening for all incoming messages (Ctrl+C to stop)...", file=sys.stderr)
            try:
                for msg in client.poll(timeout_s=args.seconds):
                    if as_json:
                        print(json.dumps(msg))
                    else:
                        print(f"{msg['addr']} {msg['typetags']} {msg['args']}")
            except KeyboardInterrupt:
                pass

        elif args.command == "raw":
            coerced = _coerce_raw_args(args.typetags, args.args)
            if args.typetags == "":
                _output(client.get(args.address, timeout_s=args.timeout), as_json)
            else:
                client.send(args.address, args.typetags, coerced)
                print(f"Sent {args.address} ,{args.typetags} {coerced}")

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except DeviceNotFoundError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except DeviceTimeoutError as err:
        print(f"error: {err}", file=sys.stderr)
        print("hint: try `inuke online` first -- see PROTOCOL_NOTES.md, Critical gotcha #3", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
