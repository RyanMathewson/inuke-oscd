"""Magnitude response of the amp's PEQ band types, used to simulate a room
measurement with EQ applied (`inuke rew loop --simulate`) and in tests.

The amp's actual internal filter design isn't known from the reverse
engineering (see docs/PROTOCOL_NOTES.md), so this assumes the conventional
choice: RBJ "Audio EQ Cookbook" biquads at 48 kHz for PEQ and 12 dB/oct
shelves, and first-order shelves with the corner at the geometric midpoint
for the 6 dB/oct ones. Real verification measurements are what tell you
whether the amp agrees -- the loop reports the gap between REW's predicted
and measured response for exactly that reason.
"""
from __future__ import annotations

import cmath
import math
from typing import Iterable

FS = 48000.0


def _biquad_db(b0: float, b1: float, b2: float, a0: float, a1: float, a2: float, f: float) -> float:
    z1 = cmath.exp(-1j * 2 * math.pi * f / FS)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
    return 20 * math.log10(max(abs(h), 1e-12))


def band_db(type_: str, freq: float, gain: float, q: float, f: float) -> float:
    if type_ in ("OFF", "") or not freq or not gain:
        return 0.0
    A = 10 ** (gain / 40)
    if type_ in ("LS6", "HS6"):
        # First-order shelf, |H|^2 = (w^2 + A^4 wc^2) / (w^2 + wc^2) for LS.
        if type_ == "LS6":
            wc = freq / A
            return 10 * math.log10((f * f + A ** 4 * wc * wc) / (f * f + wc * wc))
        wc = freq * A
        return 10 * math.log10((A ** 4 * f * f + wc * wc) / (f * f + wc * wc))
    w0 = 2 * math.pi * freq / FS
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * max(q, 1e-3))
    if type_ == "PEQ":
        return _biquad_db(1 + alpha * A, -2 * cw, 1 - alpha * A, 1 + alpha / A, -2 * cw, 1 - alpha / A, f)
    sa = 2 * math.sqrt(A) * alpha
    if type_ == "LS12":
        return _biquad_db(
            A * ((A + 1) - (A - 1) * cw + sa),
            2 * A * ((A - 1) - (A + 1) * cw),
            A * ((A + 1) - (A - 1) * cw - sa),
            (A + 1) + (A - 1) * cw + sa,
            -2 * ((A - 1) + (A + 1) * cw),
            (A + 1) + (A - 1) * cw - sa,
            f,
        )
    if type_ == "HS12":
        return _biquad_db(
            A * ((A + 1) + (A - 1) * cw + sa),
            -2 * A * ((A - 1) + (A + 1) * cw),
            A * ((A + 1) + (A - 1) * cw - sa),
            (A + 1) - (A - 1) * cw + sa,
            2 * ((A - 1) - (A + 1) * cw),
            (A + 1) - (A - 1) * cw - sa,
            f,
        )
    raise ValueError(f"unknown PEQ type {type_!r}")


def bands_db(bands: Iterable[dict], f: float) -> float:
    return sum(band_db(b["type"], b["freq"], b["gain"], b["q"], f) for b in bands)
