# iNuke Remote Connect — Protocol Reverse Engineering Notes

Goal: document the protocol used by Behringer/Music Group's "iNuke Remote Connect"
app (v1.4) to control iNuke DSP power amps (and, incidentally, the related AX
series) well enough to reimplement it as an open-source replacement.

Status: protocol is well-understood — confirmed via live USBPcap captures and
a working independent client (`scripts/inuke_client.py`) against a real
NU3000DSP, plus a full pass through the legacy app's UI. Two independent
replacement clients are now built on top of it: a browser-based (WebHID) GUI
in `webapp/` and a cross-platform Python CLI in `cli/` — see the root
README's Status section. See "Open questions" near the end for the specific
things that are still genuinely unconfirmed.

**How to read this document**: this section (Quick Reference) is everything
you need to start building a client — the full address table, the framing
rules, and the gotchas that will bite you if you skip them. Everything after
"Hardware / transport" is the supporting evidence and discovery narrative
(capture-by-capture proof for every claim above) — useful for verifying a
claim or understanding *why* something works the way it does, not required
reading to get started. "Open questions" near the end lists everything that
is genuinely still unconfirmed; don't assume anything not in this doc.

## Quick Reference

### Transport (see "CONFIRMED: USB wire protocol" for full detail)

- Device: HID, vendor-defined usage page, `VID_1397 PID_1101` (Behringer/
  Music Group). One interrupt endpoint, `0x81` IN, 64 bytes.
- **No interrupt OUT endpoint on this hardware.** Host->device writes go
  through a HID `SET_REPORT` **control transfer**: `bmRequestType=0x21`,
  `bRequest=0x09`, `wValue=0x0200` (Output, ReportID 0), `wIndex=0x0000`,
  `wLength=0x3F` (63 bytes).
- Every 63-byte report, either direction, is: `byte[0]` = length `N` of an
  embedded OSC 1.0 message, then `N` bytes of that message, then don't-care
  padding (**not guaranteed zero** — truncate at the length byte, never read
  past it).
- The embedded message is standard binary OSC: NUL-padded address string
  (multiple of 4 bytes), NUL-padded `,typetags` string (multiple of 4
  bytes), then big-endian `f`(float32)/`i`(int32) or NUL-padded `s`(string)
  args in order. No bundle wrapper, no checksum, no sequence number.
- **GET is a SET with no arguments**: send the bare address with an empty
  type tag string (zero declared args). The device answers with an
  ordinary-looking report on the same address, now with real args. Same
  format both directions.

### Address table

All addresses below are GET-able (send bare, get a populated reply) and
SET-able (send with real args to change the amp) unless the Notes column
says otherwise. `<N>` = channel, `1` or `2`.

| Address | Typetags | Args (in order) | Notes |
|---|---|---|---|
| `/info` | `ssi` | `amp_name, firmware_version_str, unknown_int` | `amp_name` is the same value `/ampname` sets (not a fixed model string). `unknown_int` observed constant (`5`) across all ampmodes; meaning not determined. GET only — SET not tested/expected. |
| `/ampname` | `s` | `name` | Sets the amp's display name. SET confirmed live; GET not separately tested but presumably works like everything else. |
| `/online` | (empty) | — | **Trigger, not a value.** Marks the session "online": makes the device push `/lock` once. Can also spontaneously trigger the vendor app's "device connected" dialog if it's running concurrently. |
| `/offline` | (empty) | — | **Trigger.** Suspends the device's replies to GET queries until `/online` is sent again. Does not alter or lose any DSP parameter — purely a communication state. **If queries suddenly get no replies, send `/online` again before assuming something is broken** — this has also been observed once with no clear cause. |
| `/lock` | `i` | `0` or `1` (presumed unlocked/locked) | Only ever observed pushed by the device after `/online`; a bare GET on `/lock` itself gets no reply. SET never tested (see Lock/Unlock, deliberately untested). |
| `/gain` | `ffii` | `?, ?, ?, ?` (shape suggests `gainA_dB, gainB_dB, muteA, muteB`) | GET works and returns `[0.0, 0.0, 0, 0]`. **SET does not stick** — wire-verified correct bytes reach the device but a follow-up GET shows no change, and there's no UI control for it anywhere. Treat as read-only; likely reflects a hardware-level (rear-panel trim pot?) state rather than a DSP parameter. |
| `/ampmode` | `s` | `mode` | One of `DUAL`, `STEREO`, `BIAMP1`, `BIAMP2`, `BRIDGED`. Full, closed set — matches all 5 Mode buttons in the UI exactly. |
| `/channel/<N>/peq/<1-8>` | `sfff` | `type, freq_hz, gain_db, Q` | `type` ∈ `PEQ, LS6, LS12, HS6, HS12` (same list for every band) **or** `OFF`. `OFF` is set by the per-band "Filter N" enable toggle in the UI, not by this dropdown — disabling a band puts `OFF` here while the UI's own type dropdown keeps showing whatever shape was last selected (**the wire value and the UI display can diverge — always trust the wire**). `freq_hz` is a plain float, not the `.arp` file's `4k00`-style shorthand. |
| `/channel/<N>/xover/hp` | `sf` | `type, freq_hz` | `type` = `OFF` or `<FAMILY><slope>`, one token, e.g. `BUT24`, `BES12`, `LR12`, `BUT6`, `BUT48`. Families: `BUT`/`BES`/`LR` (Butterworth/Bessel/Linkwitz-Riley). Slopes: `6/12/18/24/48` (dB/oct), **no zero-padding** at any width. |
| `/channel/<N>/xover/lp` | `sf` | `type, freq_hz` | Same encoding as `xover/hp`. |
| `/channel/<N>/xover/gain` | `f` | `gain_db` | |
| `/channel/<N>/deq/<1-2>/comp` | `fff` | `gain_db, threshold_db, ratio` | |
| `/channel/<N>/deq/<1-2>/time` | `ff` | `attack_ms, release_ms` | |
| `/channel/<N>/deq/<1-2>/filt` | `sff` | `type, freq_hz, Q` | `type` ∈ `BP, LP6, LP12, HP6, HP12` or `OFF`. Same "OFF via the 'DEQ N' enable toggle, not this list" pattern as PEQ — same wire-vs-UI-display caveat applies. |
| `/channel/<N>/delay` | `fi` | `time_ms, phase_degrees` | The UI shows delay in ms/m/ft, but those are just three unit-converted *displays* of this one float — there's no separate wire field per unit. The int is **Phase** (`0` or `180`), not a unit selector. |
| `/channel/<N>/limiter` | `fff` | `threshold_Vp, release_ms, hold_ms` | Threshold is in **peak volts**, not dBFS — the UI's dBFS readout is a locally-computed alternate display; dBFS itself is never on the wire. |
| `/meter` | `f` (host->device) / `ffff` (device->host) | `refresh_rate_hz` / `input_A, input_B, output_A, output_B` | Host sends `,f 10.0` roughly every 5s (looks like a keepalive/rate-set for the telemetry stream — not proven by deliberately changing the value). Device pushes `,ffff` unsolicited ~10x/sec regardless. Values are **linear amplitude**, not dB; scale top and peak-vs-RMS not yet confirmed (needs a loud/clipping signal — see Open Questions #5). |
| `/preset/name` | `iis` | `slot(1-20), ?, name` | GET only tested. Unused slots reply with name `"EMPTY"`. 20 onboard slots. |
| `/preset/save` | `iis` | `slot(1-20), ampmode_enum, name` | This is what the Setup tab's "Store" button sends. `ampmode_enum`: `DUAL=0, STEREO=1, BIAMP1=2, BIAMP2=3, BRIDGED=4`. Confirmed the amp snapshots its *entire* current DSP state server-side (both channels) — the message itself doesn't carry the parameter values. |
| `/preset/load` | `iis` | `slot, 0, name` | This is what "Recall" sends. The int and name here look like non-authoritative placeholders (device already knows what's stored); only `slot` matters. Confirmed the amp applies its full stored state internally (one message on the wire, not ~40 individual SETs). |
| `/peaklimit` | — | — | Bare GET: no reply, no observable effect. Untested with real arguments. |
| `/speaker` | — | — | Never observed on the wire for the USB iNuke DSP line. The Configuration tab's "Load" (speaker impedance) dropdown is a **client-side-only** wattage calculation — it sends nothing. May be an AX-series/UDP-only concept, or unused. |
| `/siggen` | — | — | No UI path exists for the iNuke DSP series (no "Utility" tab) — AX-series only. |

### Preset system

20 onboard slots (1-20), each with a name and an ampmode, managed by
`/preset/save` (Store) and `/preset/load` (Recall) above. Loading a `.arp`
file client-side and pushing each line as a SET (what the vendor app does)
is a *different* mechanism from Recall — both end up changing the same live
DSP state, but only Recall touches the amp's own onboard slots.

### Critical gotchas

1. **Truncate every report at its length byte.** Bytes past `1+N` are
   leftover garbage from a previous, differently-sized message in the same
   buffer — not padding you can rely on being zero.
2. **`OFF` for PEQ/DEQ bands comes from a toggle button, not the type
   dropdown**, and the UI's dropdown display can be stale/wrong relative to
   the actual wire value whenever a band is disabled. Query the wire, don't
   trust cached UI state.
3. **`/offline` stops the device from replying to GET queries** until
   `/online` is sent again — this is a communication-state toggle, not data
   loss, but it will look like total failure if you don't know about it.
   This "everything stops replying" state has also been seen once with no
   `/offline` involved, cause unknown — `/online` fixes it either way.
4. **`/gain` looks writable at the wire level but isn't** — don't build a
   gain/mute control on top of it without testing against real hardware
   first (see the address table entry).
5. Frequency, dB, and other numeric fields are plain float32 — don't try to
   parse the `.arp` file's `4k00`-style shorthand as anything other than a
   save-file text convenience; it's never on the wire.

## Hardware / transport

- Device enumerates as: `HID\VID_1397&PID_1101` — a **vendor-defined HID
  device** (Windows shows it as "HID-compliant vendor-defined device" /
  "USB Input Device"). VID `0x1397` = Music Group / Behringer.
- Because the HID usage page is vendor-defined, Windows does not parse the
  reports for us — we need the actual report descriptor (report IDs, and
  input/output/feature report lengths) and/or a raw USB capture to know the
  framing.
- The app links `HID.DLL` (standard Windows HID API), so it's talking to the
  device the normal way (`HidD_*` / `ReadFile`/`WriteFile` on the HID handle),
  not a custom kernel driver.
- Two product families share this one app:
  - **iNuke DSP series** (NU1000DSP, NU3000DSP, NU6000DSP, NU12000DSP) — **USB
    only**, this is our hardware.
  - **AX series** (AX6220, AX6240, AX6220Z, AX6240Z) — **network (UDP)**,
    OSC-over-UDP, has its own signal generator ("Generator (AX Series)") and
    device discovery ("look for AX devices").

## Application-layer protocol: OSC

The app is built around **oscpack** (Ross Bencina's C++ OSC library) —
confirmed by exact-match mangled C++ RTTI names found in the binary:

```
osc::OscCom
osc::MissingArgumentException
osc::ExcessArgumentException
osc::OutOfBufferMemoryException
osc::MessageInProgressException
osc::MessageNotInProgressException
osc::WrongArgumentTypeException
osc::MalformedMessageException
```

...plus oscpack's exact runtime error strings ("message size must be multiple
of four", "unterminated address pattern", "type tags not present", etc.).

This means the actual parameter-change messages are standard binary OSC 1.0
packets: `/address/pattern\0`, padded to 4 bytes, followed by `,typetags\0`
padded to 4 bytes, followed by the argument values in binary (big-endian per
OSC spec). **Confirmed by live capture** — see "CONFIRMED: USB wire protocol"
below for exactly how these get framed inside 64-byte HID reports.

Note: strings that look like a framing header ("header crc mismatch",
"incorrect header check", "unknown compression method"...) are **zlib's own
inflate() error strings**, not evidence of a custom packet header. Don't chase
that as a protocol clue — it's a coincidental neighbor in the string table
(zlib is probably used elsewhere, e.g. for a compressed resource or the
firmware updater).

## OSC address space (from the app's built-in default values + `.arp` files)

`existing_settings.arp` (a settings file saved from the real app against a
real amp) turned out to be a **plain-text dump of the same OSC address/typetag
data**, delimited by literal `BEGIN_OSC_DATA` / `END_OSC_DATA` markers. This
gives us the full persisted-parameter address space directly, no guessing
needed:

```
/ampmode s <MODE>
/channel/<N>/peq/<1-8> sfff <TYPE> <freq> <gain> <Q>
/channel/<N>/xover/hp sf <TYPE> <freq>
/channel/<N>/xover/lp sf <TYPE> <freq>
/channel/<N>/xover/gain f <gain>
/channel/<N>/deq/<1-2>/comp fff <gain> <threshold> <ratio>
/channel/<N>/deq/<1-2>/time ff <attack_ms> <release_ms>
/channel/<N>/deq/<1-2>/filt sff <TYPE> <freq> <Q>
/channel/<N>/delay fi <time_ms> <phase_degrees>
/channel/<N>/limiter fff <threshold_Vp> <release_ms> <hold_ms>
```

Type tag legend: `s` = OSC string, `f` = OSC float32, `i` = OSC int32.

Values seen for `<MODE>` (ampmode): `DUAL`, `STEREO`, `BIAMP1`, `BIAMP2`,
`BRIDGED` (UI labels: Dual Mono / Stereo / Bi-Amp 1 / Bi-Amp 2 / Bridge /
Channel A+B).

Values seen in the `.arp` file for PEQ `<TYPE>`: `OFF`, `PEQ`, `LS12` (low
shelf), `HS12` (high shelf) — full dropdown list (all 8 bands, every band
offers the same options) confirmed later as `PEQ, LS6, LS12, HS6, HS12`, with
"OFF" actually coming from a separate per-band enable toggle, not this list
— see "UI mechanics" below.

Values seen for xover `<TYPE>`: `OFF`, `BUT24` (Butterworth 24 dB/oct).
**Confirmed later**: family is one of `BUT`/`BES`/`LR` (Butterworth/Bessel/
Linkwitz-Riley) and the numeric suffix is slope in dB/octave — see "UI
mechanics" below for the full dropdown lists (only the `12`/`24` slopes have
actually been observed on the wire, though the UI offers `6/12/18/24/48`).

Values seen for DEQ filt `<TYPE>`: `OFF`, `BP` (band-pass) — full dropdown
list confirmed later as `BP, LP6, LP12, HP6, HP12` (same "OFF via toggle,
not dropdown" pattern as PEQ).

Frequency values are sometimes given in a `NkNN` shorthand in the `.arp`
file, e.g. `4k00` = 4000 Hz, `10k00` = 10000 Hz — **confirmed this is purely
a text-format pretty-printer**; the wire always carries a plain float32 Hz
value (see "CONFIRMED: field mappings" below).

Limiter `fff` order: **confirmed** as
`[threshold_Vp, release_ms, hold_ms]` — see "CONFIRMED: field mappings"
below.

DEQ `comp fff` order: **confirmed** as `<gain_db> <threshold_db> <ratio>` —
see "Open questions" below for how (a direct SET with distinguishable test
values, read back off the legacy UI).

### Addresses NOT in the `.arp` file (seen only as string literals — runtime/
session control, not persisted settings)

```
/online
/offline
/preset/name
/meter          -- almost certainly device -> host telemetry (levels/meters)
/peaklimit
/speaker        -- likely speaker impedance selection (release notes mention
                   "wrong speaker impedance" bug fixed in v1.4)
/siggen         -- signal generator (AX series has a full one: sine/pink/
                   white noise, level, scan rate; unclear if iNuke DSP shares
                   this over USB)
/ampname
```

## `.arp` preset file format

Plain ASCII text, CRLF line endings. Structure:

```
\r\nBEGIN_OSC_DATA\r\n
<address> <typetags> <arg> <arg> ...\r\n
... (one line per OSC message)
END_OSC_DATA
```

This is presumably just a straight dump of the sequence of OSC messages that
would be sent to the amp to fully configure it from scratch — i.e. loading a
preset == replaying these lines as OSC messages. Error string `"Not a valid
Preset (.arp) file"` confirms the app validates this format when opening.

## Known hardware models (from UI strings)

- iNuke DSP: NU1000DSP, NU3000DSP, NU6000DSP, NU12000DSP
- AX series: AX6220, AX6240, AX6220Z, AX6240Z

## CONFIRMED: USB wire protocol (from live USBPcap capture)

Captured with Wireshark/USBPcap while connected to a real NU3000DSP, toggling
ampmode and observing the periodic meter heartbeat. See `captures/session1.pcap`.

### Transport summary

- Device: `VID_1397 PID_1101`, USB full-speed, **bMaxPacketSize0 = 64**.
- One HID interface, **one endpoint only**: `0x81` IN, Interrupt, wMaxPacketSize
  64, bInterval 10 (i.e. polled every ~10ms at the USB level, though the
  device only pushes real data roughly every ~100ms in practice).
- There is **no interrupt OUT endpoint**. Host -> device writes are done as a
  **USB control transfer carrying a standard HID `SET_REPORT`**:
  - `bmRequestType = 0x21` (Host-to-device, Class, Interface)
  - `bRequest = 0x09` (SET_REPORT)
  - `wValue = 0x0200` (ReportType = Output(2), ReportID = 0)
  - `wIndex = 0x0000` (Interface 0)
  - `wLength = 0x003F` (63 bytes)
- Device -> host data arrives as HID **Input reports on interrupt endpoint
  0x81** (also effectively 63 bytes of payload).
- HID Report Descriptor is 28 bytes (from the HID descriptor:
  `bDescriptorType=0x22, wDescriptorLength=0x001C`) — not yet dumped verbatim,
  but functionally irrelevant: it's just a vendor-defined opaque byte array,
  and we've reverse-engineered the actual payload framing directly from
  traffic (below), which is what matters for reimplementation.

### Report payload framing (same scheme for IN and OUT)

Every 63-byte HID report (in either direction) is:

```
byte[0]      = N = length of the embedded OSC message, in bytes
byte[1..1+N) = a raw binary OSC 1.0 message (address, typetags, args — see below)
byte[1+N..63)= don't-care padding — NOT necessarily zero!
```

**Important gotcha for anyone implementing a parser**: the app does not clear
its 63-byte buffer between writes, so bytes beyond `1+N` are frequently
leftover garbage from a previous, longer message written into the same
buffer (verified: we saw stale limiter float values trailing behind a
shorter `/ampmode` message that was sent right after a `/channel/1/limiter`
message). **Always truncate at the length byte; never treat trailing bytes
as meaningful.**

The embedded message itself is standard OSC 1.0 binary encoding:
- Address pattern: ASCII string starting with `/`, NUL-terminated, padded
  with additional NUL bytes to a multiple of 4 bytes total.
- Type tag string: `,` followed by one letter per argument (`f`=float32,
  `i`=int32, `s`=string), NUL-terminated, padded to a multiple of 4 bytes.
- Arguments follow in order: `f`/`i` = 4 bytes **big-endian**; `s` = ASCII,
  NUL-terminated, padded to a multiple of 4 bytes.

No OSC bundle wrapper, no checksum, no sequence number — just one message per
report, length-prefixed by 1 byte.

### Confirmed example packets

**Ampmode change (Bi-Amp 1 -> Stereo), OUT/SET_REPORT payload:**
```
18 2f 61 6d 70 6d 6f 64 65 00 00 00 00 2c 73 00 00 53 54 45 52 45 4f 00 00 ...(garbage)
^len=24
   /  a  m  p  m  o  d  e \0 \0 \0 \0  ,  s \0 \0  S  T  E  R  E  O \0 \0
```
= `/ampmode ,s "STEREO"` — matches the `.arp` text format 1:1 (just binary
OSC instead of the pretty-printed text used for file save/load).

**Periodic "meter" heartbeat, sent by the app every ~5s regardless of user
action, OUT/SET_REPORT payload:**
```
10 2f 6d 65 74 65 72 00 00 2c 66 00 00 41 20 00 00
^len=16
   /  m  e  t  e  r \0 \0  ,  f \0 \0  <float 10.0>
```
= `/meter ,f 10.0`. Hypothesis: this both (a) confirms/renews the device's
periodic meter push and (b) sets its refresh rate — **10.0 (Hz) matches the
observed ~100ms cadence of the unsolicited 0x81 IN meter reports**. Needs
confirming with a capture where we change this deliberately (not yet done —
no UI control obviously maps to it, may be hardcoded).

**Limiter change, OUT/SET_REPORT payload:**
```
28 2f 63 68 61 6e 6e 65 6c 2f 31 2f 6c 69 6d 69 74 65 72 00 00 2c 66 66 66 00 00 00 00 <f> <f> <f>
^len=40
   /channel/1/limiter\0\0        ,fff\0\0\0\0   69.9   100.0   50.0
```
Matches `/channel/1/limiter fff 69.9 100.0 50.0` from the `.arp` file exactly
— **confirms the limiter's 3 floats are, in order, whatever was last set as
threshold/release/hold** (values matched the amp's actual current settings
at capture time, in the same order as the `.arp` dump). Still to nail down:
which literal float is threshold vs release vs hold (need an isolated
single-field change).

**Meter telemetry, IN report from device (unsolicited, ~every 100ms):**
```
20 2f 6d 65 74 65 72 00 00 2c 66 66 66 66 00 00 00 <f> <f> <f> <f>
^len=32
   /meter\0\0   ,ffff\0\0\0   <4 float values>
```
= `/meter ,ffff v1 v2 v3 v4` = `[input_A, input_B, output_A, output_B]`,
linear amplitude (0.0-ish at idle, up to ~0.01 observed at moderate playback
in Bi-Amp mode; scale top not yet confirmed) — see the resolved entry under
Open Questions below for how this was pinned down with real audio.

### Enumeration (from `--inject-descriptors`, i.e. Windows' cached descriptors)

- Device descriptor: bcdUSB 2.00, bMaxPacketSize0 64, idVendor 0x1397,
  idProduct 0x1101, 1 configuration.
- Configuration: 1 interface, self-powered (bmAttributes 0xC0).
- Interface 0: class 0x03 (HID), 1 endpoint.
- HID descriptor: bcdHID 1.10, 1 report descriptor, length 28 bytes.
- Endpoint: 0x81, Interrupt IN, wMaxPacketSize 64, bInterval 10.

## CONFIRMED: field mappings (from `captures/session2.pcap`, isolated single-field changes)

Method: made one change at a time in the real app against a real NU3000DSP,
in a known order, then parsed every OUT `SET_REPORT` in the capture with
`scripts/parse_osc.py` (see below) and matched them to the sequence of
changes.

- **PEQ frequency is a plain float32 Hz value on the wire**, not the `.arp`
  file's `4k00`/`30`-style shorthand (that shorthand is purely a text-format
  pretty-printer for the `.arp` save format). Confirms open question #2.
  Also note: entering `30` produced `29.999914169311523`, and the untouched
  default `40.0` read back as `40.000003814697266` — expect small float32
  rounding/DSP-quantization noise; don't expect bit-exact round-trips of
  user-entered values.
- **Limiter `fff` argument order is `[threshold_Vp, release_ms, hold_ms]`**
  — confirmed by three successive isolated changes:
  `[70.7, 100.0, 50.0]` (baseline after only threshold was touched) ->
  `[70.7, 105.0, 50.0]` (release changed 100->105) ->
  `[70.7, 105.0, 55.0]` (hold changed 50->55).
  The UI's "-x.x dBfs" readout is a locally-computed alternate display of the
  same threshold value (sent/stored only as `Vp`, peak volts) — dBFS is never
  on the wire.
- **Crossover filter type codes are `<FAMILY><SLOPE_DB>`, one token**:
  confirmed `BES12` (Bessel, 12 dB/oct) and `LR12` (Linkwitz-Riley, 12 dB/oct),
  alongside the previously-seen default `BUT24` (Butterworth, 24 dB/oct).
  So the family codes are `BUT`/`BES`/`LR` and the numeric suffix is the
  slope in dB/octave (whatever slope values the UI's "High Pass 1-3"/"Low
  Pass 2-4" options expose — likely 6/12/18/24, not all observed yet).

## `scripts/inuke_client.py` — first working independent client

A minimal Python client (`hidapi`-based) that talks to the amp **directly,
with the vendor app completely uninvolved** — this is the first real
milestone toward a replacement app. Confirmed working:
- Opens the device by VID/PID, sends a GET (`/gain`) and reads back the
  device's reply, decoded correctly.
- A raw SET works at the wire level too (verified byte-for-byte against a
  fresh capture of our own traffic) — see the `/gain` writability test
  below, which succeeded in *transmission* even though `/gain` itself turned
  out not to be writable in practice.
- Runs fine **concurrently with the vendor app still connected** — Windows'
  HID class driver arbitrates access fine; our queries/writes did not
  disrupt the app's own connection.

Not yet implemented: chunking/handling for messages that wouldn't fit one
62-byte payload (none of our known messages need this, so untested), and no
write helpers for the higher-level parameters yet (PEQ, xover, etc.) — only
a generic `send(address, typetags, args)` / `poll()` pair so far.

## `scripts/parse_osc.py`

A standalone parser was written to pull every host->device OSC message out
of a USBPcap capture: it locates each HID `SET_REPORT` control transfer
(`21 09` SETUP prefix), reads the `wLength`, reads the 1-byte OSC length
prefix, and decodes the OSC address/typetags/args. See the script for
reuse against future captures (device->host meter reports need the same
core `osc_decode()` but sourced from endpoint `0x81` frames instead of
control-endpoint SETUP-anchored frames).

## CONFIRMED: GET/SET symmetry, and the connect handshake

Captured a full cold start: app closed -> capture started -> app reopened ->
reconnected. Source: `captures/session3_handshake.pcap`, decoded with
`scripts/parse_osc.py` (host->device) plus an endpoint-0x81 variant
(device->host).

**The protocol is fully symmetric: the same address+typetag OSC scheme is
used for both reads and writes.**
- A **GET/query** is just the bare OSC address with an *empty* type tag
  string (`","` padded to 4 bytes, i.e. zero declared arguments) — e.g.
  `/ampmode ,` with no args. This is completely standard, valid OSC; it's
  just that zero args here means "tell me the current value" by convention
  of this app/firmware, not any special framing.
- The device replies with an ordinary HID Input report (endpoint `0x81`)
  containing the *same address*, now with real typetags/args — i.e. an
  ordinary SET-shaped message. Same wire format both directions; only the
  presence of arguments differs.
- Addresses that need a parameter to identify *which* item to read (e.g.
  preset slot index) still pass that parameter as an arg even on GET: e.g.
  `/preset/name ,iis 1 0 "DUMMY"` requests preset slot 1 (the extra int and
  the string `"DUMMY"` look like placeholder/don't-care values in the
  request shape, filled with real data only in the reply).

**Connect/handshake sequence** (in order): `/info` -> `/online` -> `/gain`
-> `/ampmode` -> for channel 1 then channel 2: all 8 PEQ bands, xover
hp/lp/gain, both DEQ bands' comp/time/filt, delay, limiter -> `/preset/name`
for slots 1 through 20. I.e. **connecting = a full GET-all sweep of every
parameter**, followed by normal operation (periodic `/meter ,f 10.0`
heartbeat + continuous meter telemetry). This is presumably what the UI's
"sync to amplifier" checkbox (seen as a string in the binary) refers to.

**New addresses resolved from the handshake:**
- `/info` -> reply typetags `ssi`, e.g. `["NU3000DSP", "(V1.3)", 5]` — device
  model, firmware version string, and an integer (meaning TBD — possibly a
  protocol/capability version).
- `/gain` -> reply typetags `ffii`, e.g. `[0.0, 0.0, 0, 0]`. Not yet mapped
  to a specific UI control, but shape strongly suggests
  `[gainA_dB, gainB_dB, muteA, muteB]` given the UI strings `mutegainA`/
  `mutegainB`/`linkgain` found in the binary. Needs an isolated-change
  capture to confirm.
- `/preset/name` for an **unused** slot replies with the string `"EMPTY"`
  (not `"DUMMY"` — that was only the placeholder used in the *request*).
  Confirms the amp has **20 onboard preset slots** (indices 1-20), each
  independently nameable/queryable — this is the "Amp Presets" list in the
  Setup tab.

**Resolved negative results:**
- Changing the **Load/speaker-impedance dropdown** (Configuration tab, next
  to Peak Limiter) sent **no USB traffic at all** in this capture. It only
  changed a locally-displayed wattage figure. Conclusion: on the iNuke DSP
  (USB) product line, this control is a **client-side-only convenience
  calculation**, not a device parameter — `/speaker` may be an AX-series/UDP
  concept only (or unused entirely). Don't expect to find a `/speaker` SET
  message for this hardware.
- The app has **no "Utility" tab for the iNuke DSP series** (only
  Configuration / Filter-Crossover / Parametric EQ / Dynamic EQ / Setup) —
  confirmed directly against the running app. The signal generator
  (`/siggen`, Test Tone / Pink / White noise) has no UI path on this
  hardware over USB; it's AX-series only.

## Open questions / next steps

Everything not listed here (HID transport/framing, OSC encoding, GET/SET
symmetry, the connect handshake, ampmode/limiter/meter/gain/info/preset
message shapes, limiter field order, PEQ frequency wire encoding, xover
filter type codes, `/speaker`/`/siggen` USB-reachability, Store/Recall/
Rename) is confirmed by live capture or direct wire testing. Genuinely
still open, roughly in priority order:

1. ~~`/online`, `/offline`, `/peaklimit`~~ — **tested directly with
   `inuke_client.py`, mostly resolved.**
   - `/online` is a **session-start trigger, not a queryable value**: sent
     bare (empty typetags) 3 times in a row, it never echoes its own
     address back, but reliably (3/3) makes the device push a **new,
     previously-unseen address** `/lock ,i 0` once. Never appears in any
     prior capture including the full cold-start handshake, so this is a
     side-effect specifically of sending `/online`, not part of the normal
     connect sequence our earlier captures happened to trigger (the vendor
     app's `/online` message may carry different/real arguments we haven't
     tried — ours was a bare empty-arg send).
   - `/lock ,i <0 or 1>` is presumably the write-protection state (`0` =
     unlocked, matching the amp's actual current state) — querying it
     directly with a bare GET gets **no reply** (tested 3x), so it's
     apparently only pushed as a side-effect of `/online`, not independently
     queryable the normal way. Untested: what a SET to `/lock` looks like
     (deliberately not tried — see Lock/Unlock, item 8).
   - **`/offline` genuinely suspends the device's replies — confirmed and
     important.** Sending it (bare) produces no immediate reply, but
     *every* subsequent GET query then also gets no reply at all (verified:
     ran `verify_arp.py` right after and all 39 parameters came back
     "NO REPLY", which looked alarming until sending `/online` again
     immediately restored normal replies — a follow-up `/ampmode` GET
     worked instantly, and a fresh `verify_arp.py` pass showed all 39
     parameters still correct). So `/online`/`/offline` form a real
     session-state toggle: while "offline," the device stops answering
     queries (it may still be accepting SETs and/or streaming `/meter` —
     not separately confirmed), and nothing is lost or changed by this —
     it's purely a communication state, not a data state. **Anyone writing
     a client: if queries stop getting replies, try sending `/online`
     again before assuming something broke.** Caveat: this same
     "everything returns NO REPLY" state was observed a *second* time later
     in testing (during the `/info` ampmode-cycling test below) with no
     `/offline` involved at all — so `/offline` is a confirmed *cause* but
     evidently not the *only* cause. Root cause of that second incident is
     unexplained (a simple heartbeat/idle-timeout theory was tested and
     ruled out — see item 4). `/online` reliably recovered it both times.
   - `/peaklimit` sent bare: no reply, no observable side-effect (tested
     before the `/offline` complication above muddied a clean read on this
     one — worth re-testing in isolation later). Possibly requires real
     arguments to do anything.
2. ~~DEQ `comp fff` field order~~ — **confirmed.** Rather than fight
   imprecise knob-dragging in the legacy UI (and discovering `SendKeys`
   keyboard input to the app is blocked outright — "Access is denied",
   likely a UIPI privilege-level mismatch between our script and the app —
   so text-field typing isn't an option either), sent a SET directly via
   `inuke_client.py` with three distinguishable values,
   `/channel/1/deq/2/comp ,fff 7.0 -13.0 3.0`, and just read the legacy UI's
   display: Gain showed `7.0 dB`, Threshold `-13 dB`, Ratio `1:3.0` — exact
   order match. So `/channel/<N>/deq/<1-2>/comp fff <gain_db> <threshold_db>
   <ratio>`. Restored the original value afterward and confirmed via
   `verify_arp.py`.
3. **`/info`'s third argument** (an int, `5`) — narrowed but not fully
   resolved. **Correction**: `/info`'s first string is not a fixed model
   identifier as originally assumed — after renaming the amp to "MyAmp" via
   `/ampname`, `/info` started returning `["MyAmp", "(V1.3)", 5]` instead of
   `["NU3000DSP", ...]`. So it's actually `[custom_amp_name,
   firmware_version_string, <int>]` (name defaults to the model number until
   renamed). Tested whether the int is ampmode-dependent by cycling through
   Bridge/Dual/back to Bi-Amp 1 and querying `/info` each time — **stayed
   `5` in every mode**, so it's not a per-mode channel/config count. Best
   remaining guess: an internal firmware build/revision number distinct
   from the human-readable `(V1.3)` string. Can't narrow further with only
   one device/firmware version to compare against.
4. **`/meter ,f 10.0` heartbeat's real purpose** — the value happens to
   match the observed ~100ms report cadence (10 Hz), suggesting it sets or
   renews a refresh rate, but this was never tested by deliberately sending
   a different value and watching for a cadence change. **One theory ruled
   out**: while investigating the "all GETs return NO REPLY" incidents
   (see item 1), suspected the device might time out replies without this
   heartbeat (our minimal client never sends it) — tested by sending
   `/online` then querying `/ampmode` after increasing idle gaps (3, 8, 13,
   18, 23, 33s, no heartbeat at all) and it replied correctly every time.
   So it's not a short idle-timeout tied to this heartbeat specifically; the
   actual cause of those reply-dropout incidents (which did happen twice,
   fixed both times by sending `/online`) remains unexplained.
5. **Meter scale top / peak vs RMS — parked, not skipped.** Channel mapping
   and units (linear amplitude) are solid, confirmed with moderate-level
   real audio, but never tested near clipping. Tried a safe approach:
   temporarily set Channel 1's limiter threshold very low (10 Vp, vs. the
   normal 69.9) so limiting would engage even at quiet listening volume,
   channel 2 left alone as a control — but couldn't get playback loud
   enough at the time without disturbing others in the house. Reverted the
   threshold change (`verify_arp.py` confirmed full restoration). Revisit
   when normal-volume-but-still-audible testing is convenient; the
   low-threshold trick should still work fine.
6. ~~Xover slopes 6/18/48 dB/oct on the wire~~ — **confirmed for 6 and 48.**
   Selected each Slope dropdown option in turn (Channel A Low Pass) and
   captured: `6 dB` -> `/channel/1/xover/lp ,sf "BUT6" 65.0` (single digit,
   **no zero-padding** — settles the `BUT6` vs `BUT06` question) and
   `48 dB` -> `"BUT48"`. So the encoding is simply `<FAMILY><integer_slope>`
   with no padding at any digit count, consistent with the already-confirmed
   `BUT24`/`BES12`/`LR12`. `18 dB` (`BUT18`, presumably) wasn't separately
   tested but the pattern is now unambiguous. Restored to `BUT24` afterward,
   verified via `verify_arp.py`.
7. ~~Store's snapshot scope~~ — **confirmed for Channel B.** Using
   `inuke_client.py` directly with the now-known `/preset/save`/
   `/preset/load` formats: set `/channel/2/peq/1` to a distinctive value,
   stored to slot 12 (`/preset/save ,iis 12 2 "ScopeTest"`), then changed
   `/channel/2/peq/1` *again* to a third value, then recalled slot 12
   (`/preset/load ,iis 12 0 "ScopeTest"`) — the channel correctly reverted
   to the value that was live *at store time*, not the intermediate change.
   Confirms Store snapshots (and Recall restores) the full DSP state across
   both channels server-side, not just a partial/Channel-A-only subset.
   Restored the original value afterward, verified via `verify_arp.py`.
8. **Lock/Unlock** — deliberately left untested (risk of locking the amp in
   a state that needs the correct code to undo), not just low-confidence.
9. Two low-priority unexplained oddities: a stray mid-handshake
   `/channel/1/limiter` SET seen once in `session3_handshake.pcap` (not
   understood), and the Configuration tab routing diagram's highlight logic
   for PEQ/DEQ/Delay/Limit (why some appeared lit and others grey,
   independent of actual per-band enabled state — the diagram itself is
   confirmed non-interactive, just its exact highlight rule is unclear).
10. Dump the raw 28-byte HID Report Descriptor for completeness (not
    blocking — the functional framing is already fully known from traffic).

## UI mechanics discovered via screen automation

Wrote `scripts/ui_automation.ps1` (PowerShell + Win32/.NET) to screenshot and
click the legacy app directly, since it's a JUCE app (self-painted controls,
not visible to Windows UI Automation) and pixel-coordinate automation was
the only option. Confirmed working: window capture, clicking tabs/controls,
opening dropdowns (which render as separate JUCE popup windows titled
"menu" — must re-resolve the window handle by process ID afterward, not by
title, to screenshot them), and closing a dropdown safely by clicking its
already-checked entry (a value-preserving no-op) rather than sending Escape
(keyboard input goes to whatever window has OS focus, which is NOT
necessarily the popup — learned this the hard way sending Escape to the
terminal instead).

Findings so far:
- **Crossover filter Type options**: `OFF, Butterworth, Bessel,
  Linkwitz-Riley` (matches wire family codes `BUT`/`BES`/`LR`).
- **Crossover Slope options**: `6, 12, 18, 24, 48` dB/oct — fuller than the
  `12`/`24` we'd observed on the wire so far.
- **PEQ Type dropdown options differ by band position**: Filter 1 (and
  presumably Filter 8, the outer/shelf-capable bands) offer
  `PEQ, LS6, LS12, HS6, HS12` — no "OFF" in that list.
- **Per-band enable is separate from the Type dropdown**: each "Filter N"
  header button is itself a toggle (highlighted = band enabled, grey = band
  off) — clicking it is what actually puts `OFF` on the wire as the type
  argument, independent of whatever type is selected in the dropdown
  underneath (which is preserved for when you re-enable the band). This
  resolves why Filter 1's Type dropdown never listed "OFF" as an option.
  User-confirmed this is a genuine toggle, not just a display selector.
- **Dynamic EQ has the identical pattern**, confirmed both by the UI (user
  verified "DEQ 1"/"DEQ 2" buttons are on/off toggles, not just band
  selectors) and by direct wire query: with DEQ Band 1 toggled off in the
  UI, its Type dropdown displayed a sticky "BP" (last-selected shape), but
  querying `/channel/1/deq/1/filt` live returned `["OFF", 40.0, 1.0]` —
  confirming the UI dropdown display and the actual wire value can and do
  diverge whenever a band is disabled. **Lesson for the replacement client:
  always trust the wire value over any cached/sticky UI state.**
- **DEQ filter Type dropdown options**: `BP, LP6, LP12, HP6, HP12` (band-pass
  or low/high-pass at two slopes) — this is the shape of the DEQ band's
  sidechain/detector filter, separate from the PEQ Type list.
- **Correction: `/channel/<N>/delay`'s int argument is Phase (0 or 180
  degrees), not a delay-unit selector.** Originally guessed as a ms/m/ft
  unit selector from the UI having three delay-time fields — that guess was
  wrong. Found via a coordinate grid-sweep while hunting for the Phase
  button's exact clickable pixels (the automation kept missing it): several
  sweep points landed on the real "Phase" button and the capture showed
  `/channel/1/delay ,fi 0.0 180` / `...0.0 0` alternating. So the UI's ms/m/
  ft fields are just three alternate unit *displays* of the same underlying
  float (client-side conversion, not separate wire fields), and Phase
  (0°/180°) rides along in the same message's int slot rather than having
  its own OSC address.
- **The Configuration tab's routing diagram (XOver/PEQ/DEQ/Delay/Limit
  icons) is a non-interactive status display** — clicking on any of its
  boxes produced zero wire traffic in testing. Its highlight logic (why
  PEQ/Limit appeared lit while DEQ/Delay appeared grey, independent of the
  actual per-band enabled state) is not understood and is low priority.
- **"Channel Link" is host-side only, not a device parameter.** Enabling it
  produced no dedicated "link" OSC message — instead the app immediately
  sent `/channel/2/delay` and `/channel/2/limiter` SETs copying Channel A's
  current values onto Channel B. There's no address for "linked" state on
  the device; the app just mirrors A's edits onto B live while the toggle is
  on. Verified the toggle itself, on and back off, leaves the amp's stored
  values unchanged (via `verify_arp.py`).

## Setup tab: Amp Connection buttons

- **Search**: refreshes the list of available amps (device discovery scan).
- **Connect**: shows a confirmation dialog ("Connect to device and lose
  current settings?"); confirming loads the selected device's actual live
  settings into the app. User-confirmed this UI behavior directly, matching
  what we'd already inferred from `captures/session3_handshake.pcap` (a full
  GET-all sweep of every parameter runs right after connecting) — i.e. this
  dialog exists because connecting is destructive to whatever the app was
  currently showing/editing, not to the device's own state. **Side note**:
  this same dialog popped up spontaneously (titled "iNUKE model connected")
  while the vendor app was already connected, apparently triggered by our
  own client sending `/online` — the vendor app seems to interpret that
  message as a fresh device-arrival event. Harmless either way it's
  dismissed (Connect just re-pulls the device's actual current values,
  which are unchanged; confirmed via `verify_arp.py` afterward), but worth
  knowing a third-party client sending `/online` can surface this UI.
- **Add fixed IP**: AX-series/network-only (manual IP entry for a
  discoverable-by-IP amp) — not applicable to the USB-connected iNuke DSP
  line, not investigated further.

## Setup tab: Amp Presets list

The radio-button-style indicator next to each of the 20 preset rows just
**selects that slot as the target** for the "Recall"/"Store" buttons above
the list — it does not itself recall or change anything on the amp.
Confirmed empirically: clicked preset 20's indicator, then ran
`verify_arp.py` against the live amp — all 39 parameters still matched
`existing_settings.arp` exactly, meaning nothing was actually pushed to the
amp by the indicator click alone.

## Setup tab: remaining buttons

Store, Recall, and Rename Amp were all tested live and confirmed below.
Lock/Unlock was deliberately left untested (risk of locking the amp out).

- **Store**: **confirmed via live capture.** Sends
  `/preset/save ,iis <slot> <ampmode_enum> <name>` — e.g. storing to slot 11
  as "ClaudeTest" sent `/preset/save ,iis 11 2 "ClaudeTest"`. The amp was in
  Bi-Amp 1 mode at the time, and `2` fits an enum ordering of
  `DUAL=0, STEREO=1, BIAMP1=2, BIAMP2=3, BRIDGED=4` (matching the UI's Mode
  button order) — also consistent with every *empty* preset slot reading
  back mode `DUAL` (enum `0`) in earlier `/preset/name` replies. So each
  preset stores at minimum a name and an ampmode alongside whatever
  parameter values were live when stored (the full parameter set presumably
  isn't in this one message — likely the amp itself snapshots its own
  current DSP state server-side upon receiving this command, rather than
  the app uploading every parameter; not yet confirmed which).
- **Recall**: **confirmed via live capture.** Sends
  `/preset/load ,iis <slot> 0 <name>` — e.g. `/preset/load ,iis 11 0
  "ClaudeTest"`. Only one message on the wire (not ~40 individual parameter
  SETs), confirming the amp's firmware applies the stored preset internally
  from its own storage. The middle int was `0` here (vs. `2` for the
  matching Store) and the name field just echoed the app's local cached
  name for that slot — both look like non-authoritative placeholders on the
  request side (the device already knows what's actually stored at that
  slot; c.f. the same placeholder pattern in `/preset/name` GET requests).
  Tested recalling slot 11 (a snapshot of the amp's own then-current state)
  — confirmed via `verify_arp.py` that all 39 live parameters still matched
  `existing_settings.arp` afterward, as expected for a no-op recall.
- **Rename Amp**: **confirmed via live capture.** Sends
  `/ampname ,s <name>` — e.g. `/ampname ,s "MyAmp"`. Single message, exactly
  as predicted from the binary's string literals. Note: amp name is *not*
  part of the `.arp` preset format (it's device identity, not a DSP
  parameter), so `verify_arp.py` doesn't check or restore it.
- **Lock / Unlock** (with the 4-character lock code): **deliberately left
  untested** — risk of locking the amp in a state that needs the correct
  code to undo isn't worth it for documentation purposes. Best guess only:
  engages/disengages a write-protection state on the device, gating further
  parameter changes until unlocked — matches the `unlock` OSC address
  literal found in the binary and the masked "Lock code ****" UI field. If
  the replacement client needs this, it should be investigated fresh with
  a full understanding of the recovery path first.

## Tooling set up in this repo

- Wireshark + USBPcap installed (via `winget`) for raw USB capture.
- Npcap installed (interactively — the free build doesn't support silent
  install) as Wireshark's packet-capture backend.
- USBPcap is registered as a **USB class upper filter**
  (`HKLM\SYSTEM\CurrentControlSet\Control\Class\{36fc9e60-...}`), which only
  attaches to root hubs enumerated *after* the driver was installed — a
  reboot is required before `\\.\USBPcapN` interfaces will actually capture
  traffic on the hubs that were already active.
