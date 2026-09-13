"""Full-amp backup/restore as JSON, covering the same persisted-parameter
address space as a vendor .arp file (see docs/PROTOCOL_NOTES.md, "OSC
address space" and "`.arp` preset file format") -- but as JSON instead of
the vendor's ad hoc text format, and restorable from any platform this CLI
runs on. Deliberately excludes read-only/session-state addresses (/gain,
/info, /lock) and the onboard preset slots, which are their own thing
(see `preset` commands) rather than part of the live DSP state.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .protocol import INukeClient


def capture(client: INukeClient, on_progress: Optional[Callable[[int, int, str], None]] = None) -> dict:
    steps: list[tuple[str, Callable[[], Any]]] = [("ampmode", client.get_amp_mode)]
    for ch in (1, 2):
        for b in range(1, 9):
            steps.append((f"ch{ch}.peq{b}", lambda ch=ch, b=b: client.get_peq(ch, b)))
        steps.append((f"ch{ch}.xover.hp", lambda ch=ch: client.get_xover_hp(ch)))
        steps.append((f"ch{ch}.xover.lp", lambda ch=ch: client.get_xover_lp(ch)))
        steps.append((f"ch{ch}.xover.gain", lambda ch=ch: client.get_xover_gain(ch)))
        for b in (1, 2):
            steps.append((f"ch{ch}.deq{b}.comp", lambda ch=ch, b=b: client.get_deq_comp(ch, b)))
            steps.append((f"ch{ch}.deq{b}.time", lambda ch=ch, b=b: client.get_deq_time(ch, b)))
            steps.append((f"ch{ch}.deq{b}.filt", lambda ch=ch, b=b: client.get_deq_filt(ch, b)))
        steps.append((f"ch{ch}.delay", lambda ch=ch: client.get_delay(ch)))
        steps.append((f"ch{ch}.limiter", lambda ch=ch: client.get_limiter(ch)))

    flat: dict[str, Any] = {}
    total = len(steps)
    for i, (key, fn) in enumerate(steps, 1):
        flat[key] = fn()
        if on_progress:
            on_progress(i, total, key)

    channels: dict[str, Any] = {}
    for ch in (1, 2):
        channels[str(ch)] = {
            "peq": [flat[f"ch{ch}.peq{b}"] for b in range(1, 9)],
            "xover": {
                "hp": flat[f"ch{ch}.xover.hp"],
                "lp": flat[f"ch{ch}.xover.lp"],
                "gain": flat[f"ch{ch}.xover.gain"],
            },
            "deq": [flat[f"ch{ch}.deq{b}.comp"] | {"time": flat[f"ch{ch}.deq{b}.time"]} | {"filt": flat[f"ch{ch}.deq{b}.filt"]} for b in (1, 2)],
            "delay": flat[f"ch{ch}.delay"],
            "limiter": flat[f"ch{ch}.limiter"],
        }
    return {"format": "inuke-cli-snapshot", "version": 1, "ampmode": flat["ampmode"], "channels": channels}


def restore(client: INukeClient, data: dict, on_progress: Optional[Callable[[int, int, str], None]] = None) -> None:
    if data.get("format") != "inuke-cli-snapshot":
        raise ValueError("not a recognized inuke-cli snapshot file (missing/wrong 'format' field)")

    steps: list[tuple[str, Callable[[], None]]] = [("ampmode", lambda: client.set_amp_mode(data["ampmode"]))]
    for ch_str, c in data["channels"].items():
        ch = int(ch_str)
        for i, p in enumerate(c["peq"], start=1):
            steps.append((f"ch{ch}.peq{i}", lambda ch=ch, i=i, p=p: client.set_peq(ch, i, p["type"], p["freq"], p["gain"], p["q"])))
        hp, lp, xg = c["xover"]["hp"], c["xover"]["lp"], c["xover"]["gain"]
        steps.append((f"ch{ch}.xover.hp", lambda ch=ch, hp=hp: client.set_xover_hp(ch, hp["type"], hp["freq"])))
        steps.append((f"ch{ch}.xover.lp", lambda ch=ch, lp=lp: client.set_xover_lp(ch, lp["type"], lp["freq"])))
        steps.append((f"ch{ch}.xover.gain", lambda ch=ch, xg=xg: client.set_xover_gain(ch, xg)))
        for i, d in enumerate(c["deq"], start=1):
            steps.append(
                (f"ch{ch}.deq{i}.comp", lambda ch=ch, i=i, d=d: client.set_deq_comp(ch, i, d["gain"], d["threshold"], d["ratio"]))
            )
            steps.append((f"ch{ch}.deq{i}.time", lambda ch=ch, i=i, d=d: client.set_deq_time(ch, i, d["time"]["attack"], d["time"]["release"])))
            steps.append((f"ch{ch}.deq{i}.filt", lambda ch=ch, i=i, d=d: client.set_deq_filt(ch, i, d["filt"]["type"], d["filt"]["freq"], d["filt"]["q"])))
        delay, limiter = c["delay"], c["limiter"]
        steps.append((f"ch{ch}.delay", lambda ch=ch, delay=delay: client.set_delay(ch, delay["time_ms"], delay["phase_deg"])))
        steps.append(
            (
                f"ch{ch}.limiter",
                lambda ch=ch, limiter=limiter: client.set_limiter(ch, limiter["threshold_vp"], limiter["release_ms"], limiter["hold_ms"]),
            )
        )

    total = len(steps)
    for i, (key, fn) in enumerate(steps, 1):
        fn()
        if on_progress:
            on_progress(i, total, key)
