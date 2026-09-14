"""Read/write the vendor app's own `.arp` preset file format.

See docs/PROTOCOL_NOTES.md, "`.arp` preset file format" and "OSC address
space", plus the real sample at ../existing_settings.arp. This is a
plain-text dump of OSC SET messages, delimited by BEGIN_OSC_DATA/
END_OSC_DATA markers -- one line per persisted address. Loading a preset is
just replaying these lines as OSC SETs.

`format_arp`/`parse_arp` operate on the same nested dict shape that
`snapshot.capture()` produces and `snapshot.restore()` consumes, so an
amp's live state can round-trip: capture() -> format_arp() -> (file) ->
parse_arp() -> restore().
"""
from __future__ import annotations

from typing import Any

_CHANNELS = ("1", "2")


class ArpFormatError(ValueError):
    """Raised for text that doesn't look like a valid .arp file, mirroring
    the vendor app's own "Not a valid Preset (.arp) file" error."""


def _empty_channel() -> dict:
    return {
        "peq": [{"type": "OFF", "freq": 0.0, "gain": 0.0, "q": 0.0} for _ in range(8)],
        "xover": {"hp": {"type": "OFF", "freq": 0.0}, "lp": {"type": "OFF", "freq": 0.0}, "gain": 0.0},
        "deq": [
            {"gain": 0.0, "threshold": 0.0, "ratio": 1.0, "time": {"attack": 0.0, "release": 0.0}, "filt": {"type": "OFF", "freq": 0.0, "q": 0.0}}
            for _ in range(2)
        ],
        "delay": {"time_ms": 0.0, "phase_deg": 0},
        "limiter": {"threshold_vp": 0.0, "release_ms": 0.0, "hold_ms": 0.0},
    }


# --- numeric formatting (write side) -----------------------------------
# Byte-exact vendor formatting isn't required -- only structure and values
# need to round-trip, since both the vendor app's parser and ours tokenize
# on whitespace and parse floats. Frequencies do reproduce the vendor's
# "NkNN" shorthand for values >= 1000 Hz, since that's the one piece of
# cosmetic fidelity worth having for files a user might reopen in the
# vendor app.


def _format_num(v: float) -> str:
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    if s in ("", "-", "-0"):
        s = "0"
    return s


def _format_freq(v: float) -> str:
    v = float(v)
    if v < 1000:
        return _format_num(v)
    thousands = v / 1000.0
    whole = int(thousands)
    frac = round((thousands - whole) * 100)
    if frac >= 100:
        whole += 1
        frac = 0
    return f"{whole}k{frac:02d}"


def _parse_freq(tok: str) -> float:
    if "k" in tok:
        left, right = tok.split("k", 1)
        return float(f"{left}.{right}") * 1000.0
    return float(tok)


# --- writer --------------------------------------------------------------


def _peq_line(ch: str, band: int, p: dict) -> str:
    return f"/channel/{ch}/peq/{band} sfff {p['type']} {_format_freq(p['freq'])} {_format_num(p['gain'])} {_format_num(p['q'])}"


def _xover_hp_line(ch: str, hp: dict) -> str:
    return f"/channel/{ch}/xover/hp sf {hp['type']} {_format_freq(hp['freq'])}"


def _xover_lp_line(ch: str, lp: dict) -> str:
    return f"/channel/{ch}/xover/lp sf {lp['type']} {_format_freq(lp['freq'])}"


def _xover_gain_line(ch: str, gain: float) -> str:
    return f"/channel/{ch}/xover/gain f {_format_num(gain)}"


def _deq_comp_line(ch: str, band: int, c: dict) -> str:
    return f"/channel/{ch}/deq/{band}/comp fff {_format_num(c['gain'])} {_format_num(c['threshold'])} {_format_num(c['ratio'])}"


def _deq_time_line(ch: str, band: int, t: dict) -> str:
    return f"/channel/{ch}/deq/{band}/time ff {_format_num(t['attack'])} {_format_num(t['release'])}"


def _deq_filt_line(ch: str, band: int, f: dict) -> str:
    return f"/channel/{ch}/deq/{band}/filt sff {f['type']} {_format_freq(f['freq'])} {_format_num(f['q'])}"


def _delay_line(ch: str, d: dict) -> str:
    return f"/channel/{ch}/delay fi {_format_num(d['time_ms'])} {int(d['phase_deg'])}"


def _limiter_line(ch: str, l: dict) -> str:
    return f"/channel/{ch}/limiter fff {_format_num(l['threshold_vp'])} {_format_num(l['release_ms'])} {_format_num(l['hold_ms'])}"


def format_arp(data: dict) -> str:
    lines = [f"/ampmode s {data['ampmode']}"]
    for ch in _CHANNELS:
        c = data["channels"][ch]
        for i, p in enumerate(c["peq"], start=1):
            lines.append(_peq_line(ch, i, p))
        lines.append(_xover_hp_line(ch, c["xover"]["hp"]))
        lines.append(_xover_lp_line(ch, c["xover"]["lp"]))
        lines.append(_xover_gain_line(ch, c["xover"]["gain"]))
        for i, d in enumerate(c["deq"], start=1):
            lines.append(_deq_comp_line(ch, i, d))
            lines.append(_deq_time_line(ch, i, d["time"]))
            lines.append(_deq_filt_line(ch, i, d["filt"]))
        lines.append(_delay_line(ch, c["delay"]))
        lines.append(_limiter_line(ch, c["limiter"]))
    body = "\r\n".join(lines)
    return f"\r\nBEGIN_OSC_DATA\r\n{body}\r\nEND_OSC_DATA"


# --- reader ----------------------------------------------------------------


def _decode_args(addr: str, typetags: str, raw: list[str]) -> list[Any]:
    if len(raw) != len(typetags):
        raise ArpFormatError(f"malformed line for {addr}: expected {len(typetags)} arg(s) for typetags {typetags!r}, got {len(raw)}")
    out: list[Any] = []
    for t, v in zip(typetags, raw):
        if t == "f":
            out.append(_parse_freq(v))
        elif t == "i":
            out.append(int(v))
        elif t == "s":
            out.append(v)
        else:
            raise ArpFormatError(f"unsupported typetag {t!r} on line for {addr}")
    return out


def parse_arp(text: str) -> dict:
    lines = [l.strip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [l for l in lines if l]
    if "BEGIN_OSC_DATA" not in lines or "END_OSC_DATA" not in lines:
        raise ArpFormatError("not a valid Preset (.arp) file (missing BEGIN_OSC_DATA/END_OSC_DATA markers)")
    begin = lines.index("BEGIN_OSC_DATA")
    end = lines.index("END_OSC_DATA")
    if end < begin:
        raise ArpFormatError("not a valid Preset (.arp) file (END_OSC_DATA precedes BEGIN_OSC_DATA)")

    ampmode = None
    channels = {ch: _empty_channel() for ch in _CHANNELS}

    for line in lines[begin + 1 : end]:
        parts = line.split()
        if len(parts) < 2:
            raise ArpFormatError(f"malformed line: {line!r}")
        addr, typetags, raw = parts[0], parts[1], parts[2:]
        args = _decode_args(addr, typetags, raw)

        if addr == "/ampmode":
            ampmode = args[0]
            continue

        segs = addr.split("/")
        # e.g. ["", "channel", "1", "peq", "3"]
        if len(segs) < 4 or segs[1] != "channel" or segs[2] not in _CHANNELS:
            continue  # not a persisted address we track (e.g. /meter) -- ignore
        ch = segs[2]
        rest = segs[3:]

        if rest[0] == "peq" and len(rest) == 2:
            band = int(rest[1])
            channels[ch]["peq"][band - 1] = {"type": args[0], "freq": args[1], "gain": args[2], "q": args[3]}
        elif rest == ["xover", "hp"]:
            channels[ch]["xover"]["hp"] = {"type": args[0], "freq": args[1]}
        elif rest == ["xover", "lp"]:
            channels[ch]["xover"]["lp"] = {"type": args[0], "freq": args[1]}
        elif rest == ["xover", "gain"]:
            channels[ch]["xover"]["gain"] = args[0]
        elif len(rest) == 3 and rest[0] == "deq" and rest[2] == "comp":
            band = int(rest[1])
            channels[ch]["deq"][band - 1]["gain"] = args[0]
            channels[ch]["deq"][band - 1]["threshold"] = args[1]
            channels[ch]["deq"][band - 1]["ratio"] = args[2]
        elif len(rest) == 3 and rest[0] == "deq" and rest[2] == "time":
            band = int(rest[1])
            channels[ch]["deq"][band - 1]["time"] = {"attack": args[0], "release": args[1]}
        elif len(rest) == 3 and rest[0] == "deq" and rest[2] == "filt":
            band = int(rest[1])
            channels[ch]["deq"][band - 1]["filt"] = {"type": args[0], "freq": args[1], "q": args[2]}
        elif rest == ["delay"]:
            channels[ch]["delay"] = {"time_ms": args[0], "phase_deg": args[1]}
        elif rest == ["limiter"]:
            channels[ch]["limiter"] = {"threshold_vp": args[0], "release_ms": args[1], "hold_ms": args[2]}
        # else: unrecognized channel sub-address -- ignore for forward compat

    if ampmode is None:
        raise ArpFormatError("not a valid Preset (.arp) file (no /ampmode entry found)")

    return {"format": "inuke-cli-snapshot", "version": 1, "ampmode": ampmode, "channels": channels}
