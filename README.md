# inuke-oscd

Reverse-engineered USB/OSC protocol + open client for Behringer iNuke DSP power amps.

Behringer/Music Group's official **iNuke Remote Connect** app is no longer
maintained. This project documents the protocol it uses to control iNuke DSP
power amps over USB, and provides an independent, open-source client that
talks to the amp directly — no vendor app required.

## Status

**Protocol: well understood and documented. Client: early/minimal, not yet a
full replacement app.**

- The full wire protocol is reverse-engineered and confirmed against a real
  NU3000DSP: USB/HID transport and framing, the OSC message encoding, the
  complete parameter address space (amp mode, parametric EQ, crossover,
  dynamic EQ, delay/phase, limiter, meter telemetry, device info, and the
  20 onboard presets), and how reads/writes/session state work.
  **Start with the "Quick Reference" section at the top of
  [`docs/PROTOCOL_NOTES.md`](docs/PROTOCOL_NOTES.md)** for everything
  needed to build a client (transport, framing, the complete address
  table, and the gotchas) — the rest of that document is the supporting
  capture-by-capture evidence and the still-open questions.
- [`scripts/inuke_client.py`](scripts/inuke_client.py) is a minimal working
  Python client (via `hidapi`) that can read and write any parameter
  directly, independent of the vendor app. It's a building block, not a
  finished tool — there's no CLI, no GUI, and no typed/named helpers per
  parameter yet (just a generic `send(address, typetags, args)` / `poll()`).
- Several supporting scripts exist for analysis and safety, not end-user
  use: [`scripts/parse_osc.py`](scripts/parse_osc.py) /
  [`parse_osc_in.py`](scripts/parse_osc_in.py) decode OSC traffic out of a
  USBPcap capture, [`scripts/verify_arp.py`](scripts/verify_arp.py) diffs
  the amp's live state against a saved `.arp` preset file, and
  [`scripts/poll_meter.py`](scripts/poll_meter.py) streams live meter
  telemetry.
- [`scripts/ui_automation.ps1`](scripts/ui_automation.ps1) is a
  screenshot/click automation harness used to drive the legacy app's UI
  during reverse engineering (it self-paints its controls, so this works by
  pixel coordinates rather than named UI elements). It's a research tool,
  not something an end user needs.

**What's not here yet**: a real replacement application (GUI or otherwise)
with the same feature set as the original — mode/EQ/crossover/dynamic-EQ/
limiter editing, preset management, live metering — built on top of the
confirmed protocol. That's the natural next phase.

## Hardware scope

Confirmed against a real **NU3000DSP**; the protocol should apply to the
rest of the USB-connected iNuke DSP line (NU1000DSP, NU6000DSP, NU12000DSP),
since they share the same app and firmware family, but only the 3000 has
actually been tested.

The related **AX series** (AX6220/6240, Z variants) uses the same vendor app
but talks over the network (UDP), not USB — out of scope for this project so
far.

## Evidence

`captures/` contains the raw USBPcap captures and legacy-app screenshots that
back every claim in `docs/PROTOCOL_NOTES.md` — nothing in that document is
asserted without a capture to point to.

## Disclaimer

Not affiliated with, endorsed by, or supported by Behringer / Music Group.
This talks directly to real amplifier hardware over USB; the scripts here
are research/debugging tools, not production software — use at your own
risk, and double-check settings against the amp's actual state (e.g. with
`verify_arp.py`) rather than trusting any single tool's display.

## License

MIT — see [`LICENSE`](LICENSE).
