# inuke-oscd

Reverse-engineered USB/OSC protocol + open client for Behringer iNuke DSP power amps.

Behringer/Music Group's official **iNuke Remote Connect** app is no longer
maintained. This project documents the protocol it uses to control iNuke DSP
power amps over USB, and provides an independent, open-source client that
talks to the amp directly — no vendor app required.

**Try the web app live: [ryanmathewson.github.io/inuke-oscd](https://ryanmathewson.github.io/inuke-oscd/)**
(desktop Chrome, Edge, or Opera — plug the amp in over USB and click Connect).

## Status

**Protocol: well understood and documented. Two independent replacement
clients exist, both with full feature parity against the vendor app's
editable parameters.**

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
- **[`webapp/`](webapp/)** — a browser-based GUI replacement built on
  [WebHID](https://developer.mozilla.org/en-US/docs/Web/API/WebHID_API):
  no install, no server, talks to the amp directly from a Chrome/Edge/Opera
  tab. Covers amp mode/name, 8-band PEQ and crossover per channel, dynamic
  EQ, delay/phase, limiter, live meters, the 20 onboard presets, and
  save/load of the vendor app's own `.arp` preset file format. See
  [`webapp/README.md`](webapp/README.md) for how to run it and its known
  limitations (WebHID is Chromium-only; Lock/Unlock is deliberately not
  implemented).
- **[`cli/`](cli/)** — a cross-platform (Windows/macOS/Linux) Python CLI
  and library (`pip install -e cli/`, installs the `inuke` command) for the
  same parameter set, plus JSON output for scripting, a full-state JSON
  backup/restore that the vendor app never had, and `arp save`/`arp load`
  for real interop with the vendor app's own `.arp` preset files. See
  [`cli/README.md`](cli/README.md).
- [`scripts/inuke_client.py`](scripts/inuke_client.py) is the original
  minimal Python client (via `hidapi`) this was all bootstrapped from —
  kept as-is as a research/debugging tool; `cli/` is the polished,
  typed, tested descendant of it.
- Several supporting scripts exist for analysis and safety, not end-user
  use: [`scripts/parse_osc.py`](scripts/parse_osc.py) /
  [`parse_osc_in.py`](scripts/parse_osc_in.py) decode OSC traffic out of a
  USBPcap capture, [`scripts/verify_arp.py`](scripts/verify_arp.py) is a
  read-only diagnostic that diffs the amp's live state against a saved
  `.arp` preset file (distinct from `cli/`'s `arp save`/`arp load`, which
  actually write and load `.arp` files), and
  [`scripts/poll_meter.py`](scripts/poll_meter.py) streams live meter
  telemetry.
- [`scripts/ui_automation.ps1`](scripts/ui_automation.ps1) is a
  screenshot/click automation harness used to drive the legacy app's UI
  during reverse engineering (it self-paints its controls, so this works by
  pixel coordinates rather than named UI elements). It's a research tool,
  not something an end user needs.

**What's not here yet**: Lock/Unlock in either client (deliberately
untested against real hardware — see PROTOCOL_NOTES.md), and real-world
testing of the web app against actual hardware from someone other than the
person who wrote it (its OSC/protocol logic is unit-tested against captured
packets, and the CLI has been exercised against a real NU3000DSP, but the
WebHID connect flow itself needs a human clicking through the browser's
native device picker to verify end-to-end).

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
