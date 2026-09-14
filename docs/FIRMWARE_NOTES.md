# iNuke Firmware Notes (device-side)

Companion to [`PROTOCOL_NOTES.md`](PROTOCOL_NOTES.md). That document describes
the OSC-over-USB **wire** protocol as seen from the host; this one describes
the **device firmware** itself, reverse-engineered from the image that the
vendor's USB updater turns out to embed. Where the two disagree, this document
wins for device-side facts (it is read straight out of the firmware), and the
"Corrections to PROTOCOL_NOTES" section lists the specific points it overturns.

The investigation that produced this was: *"is there any way to remotely read
or set the volume?"* (past write tests were silently ignored). Short answer up
front, evidence below.

## TL;DR — remote volume / gain

- **There is no remote master-volume control, and there never can be over this
  protocol.** The rear-panel level knobs are analog and have **no OSC address
  of any kind**. No `/volume`, `/master`, `/level`, `/attenuation`, or `/mute`
  string exists anywhere in the firmware (or the app).
- **`/gain` is read-only by firmware design.** The firmware contains a gain
  *reporter* but no gain *setter*, so a `/gain` write is accepted at the USB
  layer and silently discarded. This is exactly why past write tests failed —
  it was never going to work, on any host. `/gain` reads `[0.0, 0.0, 0, 0]` on
  the NU3000DSP (0 dB, unmuted) and its `ffii` shape is confirmed as
  `[gainA_dB, gainB_dB, muteA, muteB]`.
- **The only remotely-settable level control is `/channel/<N>/xover/gain`**
  (per-channel dB trim in the DSP path). It has a real firmware setter. Drive
  channel 1 and channel 2 together for a master-like remote "volume". The
  limiter threshold and PEQ/DEQ band gains also move level but are not a clean
  volume. The CLI already exposes this as `set_xover_gain`.

Full evidence for each of these is in "Gain / volume: the evidence" below.

## Where the firmware came from

`iNukeUsbUpdate_V1.3/iNukeUsbUpdate_V1.3.exe` — the vendor's USB firmware
updater — **embeds the amp's entire device firmware image, uncompressed**, in
its `.rdata` section. Everything in this document is read out of that image.

The updater itself is a tiny GNU/mingw **console** app (PE32, i386; only a few
KB of actual code). What it does:

- Imports just `hid.dll` (`HidD_GetAttributes`, `HidD_GetHidGuid`,
  `HidD_GetIndexedString`, `HidD_GetSerialNumberString`), `setupapi.dll`
  (`SetupDiGetClassDevsA` / `…EnumDeviceInterfaces` / `…GetDeviceInterfaceDetailA`
  / `…DestroyDeviceInfoList`) for device discovery, and `kernel32`
  (`CreateFileA` / `ReadFile` / `WriteFile` / `CreateEventA` /
  `WaitForSingleObject`). Source file name left in the binary: `iNUKEfwupd.c`;
  helpers `_connectToUSBHIDDevice` / `_connectToIthUSBHIDDevice`.
- Talks to the amp in a **bootloader / "USB uploader" mode**, which is a
  *different* device state from the normal OSC HID interface. Its user-facing
  strings: `No iNUKE device with active USB uploader found.`,
  `Found iNUKE device serial #`, `Firmware file too big`,
  `Cannot upload firmware to device`.

So the updater is the flashing path (bootloader), and the OSC interface this
project drives is what the **flashed firmware** runs. The two do not overlap at
runtime; we just get the firmware image for free because the updater carries it
inline.

The embedded image is **not compressed** (whole-`.rdata` entropy ≈ 3.5, no
high-entropy windows), so its code and strings are directly readable. The
firmware strings sit at file offsets ≈ `0x15ac0`–`0x176a0` inside the updater
exe.

## Device architecture

**ARM Cortex-M / STM32-family MCU.** Evidence, from pointer values throughout
the embedded image:

| Region | Address range in image | Meaning |
|---|---|---|
| Flash | pointers span `0x08000000` … `0x0807f1a8` | STM32 flash aperture; span is consistent with a 512 KB-flash part |
| SRAM | pointers span `0x20000000` … `0x2003f84c` | STM32 SRAM aperture |
| Reset | a Thumb (odd) entry `0x0800f40d` | reset handler; Thumb bit set ⇒ Cortex-M Thumb-2 |

`0x08000000` flash + `0x20000000` SRAM is the STM32 signature specifically (not
generic Cortex-M, which would use `0x00000000` flash). The exact vector-table
location / load base was **not** pinned (see "Limits" below), but the memory
map itself is unambiguous.

This one MCU runs everything, per the firmware's own boot/diagnostic strings:

- **Boot**: `iNuke startup...`
- **Front panel**: `TURN ENCODER L/R` (rotary encoder + LCD UI), plus a button
  subsystem (`APP: BTN mbox rx overflow`, `APP: BTN mpool full`).
- **USB stack** with a mailbox/mempool design: `APP: USB mbox rx overflow`,
  `APP: USB mpool full`, and an `osc_send: usb_tx returns %d` transmit path.
- **Flash/config errors**: `READ ONLY!`, `FLASH ERROR!`, `GENERAL ERROR!`,
  `UNKNOWN ERROR!`.
- **Model identity strings** (the firmware is shared across the DSP line):
  `NU1000DSP`, `NU3000DSP`, `NU6000DSP`, `NU12000DSP`. (`/info`'s first field
  defaults to the model string until the amp is renamed via `/ampname`.)

## Device-side OSC implementation

The firmware has its **own** OSC + USB-mailbox stack (distinct from the app's
`oscpack`): `OscCreateRecv` / `OscCreateSend` / `OscGetMsg` / `OscSendMsg` /
`OscFormatMsg`, with `OSC: Start` / `OSC: Stop` lifecycle logs and a per-command
handler layer. Each OSC command maps to a named handler, and the handlers
follow a very regular naming/logging convention that makes the whole command
surface legible from strings alone:

- a **reporter** helper `osc_send_<thing>` (builds the reply),
- for settable commands, an `OSC: set <Thing>` **success log**, and
- one or more `<thing> got an incorrect <field> value` **validators**.

That convention is the key to classifying every command as settable vs
read-only without a disassembler (next section).

## Complete OSC address inventory (the closed set)

Every OSC address the firmware recognizes is present as a string literal. This
is the authoritative, **closed** set — an address not in this list is not
handled by the device:

```
/info /ampname /ampmode /online /offline /lock /unlock /protect /peaklimit
/meter /siggen
/preset/  /preset/name  /preset/load  /preset/save
/channel/1  /channel/2
  …and per channel, the fully-expanded paths:
  /channel/<N>/peq/1 … /peq/8
  /channel/<N>/xover/hp   /xover/lp   /xover/gain
  /channel/<N>/deq/1/comp /deq/1/time /deq/1/filt
  /channel/<N>/deq/2/comp /deq/2/time /deq/2/filt
  /channel/<N>/limiter
  /channel/<N>/delay
```

Two structural notes:

- The firmware also stores **template** fragments with a `0` placeholder
  (`/peq/0`, `/deq/0/comp`, `/deq/0/time`, `/deq/0/filt`, `/delay`, `/limiter`,
  `/xover/gain`, `/xover/hp`, `/xover/lp`) alongside the 64 fully-expanded
  per-channel/per-band paths it uses as reply addresses.
- **There is no standalone `/gain` string.** The `/gain` the app queries is the
  compiler-merged *suffix* of `/xover/gain` — the bytes `"/gain\0"` physically
  overlap the tail of `"/xover/gain\0"` in the image (GCC string pooling). So
  `/gain` is a real, handled read address, but it is **not** a parameter with
  its own storage or setter.

## Settable vs read-only (from the handler fingerprints)

Applying the naming convention above to the firmware string table:

| OSC command | Reporter (`osc_send_*`) | `OSC: set` log | Validators present | Verdict |
|---|:--:|:--:|---|---|
| `/ampmode` | (inline) | ✅ set AmpMode | mode value | **settable** |
| `/ampname` | (inline) | ✅ set AmpName | (reports) | **settable** |
| `/channel/<N>/peq/<1-8>` | ✅ peq | ✅ set PEQ | channel, number, freq, gain, qual, type | **settable** |
| `/channel/<N>/xover/hp`,`/lp` | ✅ xeq | ✅ set Xover | channel, freq, type | **settable** |
| `/channel/<N>/xover/gain` | ✅ xeq | ✅ set Xgain | channel, value | **settable** |
| `/channel/<N>/deq/<n>/comp` | ✅ deq_compressor | ✅ set DEQcomp | channel, number, mgain, thresh, ratio | **settable** |
| `/channel/<N>/deq/<n>/time` | ✅ deq_time | ✅ set DEQtime | channel, number, attack, release | **settable** |
| `/channel/<N>/deq/<n>/filt` | ✅ deq_filter | ✅ set DEQfilt | channel, number, freq, qual, gain | **settable** |
| `/channel/<N>/delay` | ✅ delay | ✅ set Delay | channel, phase, delay time | **settable** |
| `/channel/<N>/limiter` | ✅ limiter | ✅ set Limiter | channel, Rtime, Htime, thresh voltage | **settable** |
| `/preset/save`,`/load`,`/name` | ✅ preset | (`OSC: Preset`) | name size, number, ampmode | **settable** |
| `/meter` | — | — | time value | rate/keepalive setter |
| `/info` | (inline) | (`OSC: Info`) | — | **read-only** (identity) |
| `/lock`,`/unlock` | — | — | (`lock_handler reports`) | control (see below) |
| **`/gain`** | **✅ gain** | **❌ none** | **❌ none** | **READ-ONLY** |

`/gain` is the **only** command with a reporter but no setter log and no
validators. Every genuinely settable parameter has all three fingerprints;
gain has just the reporter. That asymmetry is the firmware-level proof that the
`/gain` handler only ever *reports* — it has no code path to parse or apply an
incoming gain argument.

## Gain / volume: the evidence

Three independent lines of evidence, all agreeing:

1. **No address.** No standalone `/gain` (it is the merged tail of
   `/xover/gain`), and no `/volume` / `/master` / `/level` / `/attenuation` /
   `/mute` string anywhere in the firmware or the app binary.
2. **Reporter only, no setter** (the table above): `osc_send_gain` exists;
   there is no `OSC: set Gain` and no `gain got an incorrect value` validator,
   unlike every settable parameter.
3. **Wire capture, with transfer direction** (`captures/session4_gaintest.pcap`):

   ```
   rec 96  OUT host→dev  /gain ,ffii [-3.0, 0.0, 0, 0]   ← host writes gainA = -3 dB
   rec 98  IN  dev→host  /gain ,ffii [ 0.0, 0.0, 0, 0]   ← device still reports 0
   rec106  OUT host→dev  /gain ,                          ← GET (query)
   rec108  IN  dev→host  /gain ,ffii [ 0.0, 0.0, 0, 0]   ← unchanged
   ```

   The `-3.0` write reaches the device and is discarded; the reported value
   never moves off `0.0`.

Interpretation: `/gain` (`[gainA_dB, gainB_dB, muteA, muteB]`) is a DSP-domain
input-gain/mute **report** that reads a fixed `[0, 0, 0, 0]` on the iNuke DSP.
The app binary carries `mutegainA` / `mutegainB` / `linkgain` UI strings, but
the iNuke DSP app exposes no such control — that gain/mute UI is almost
certainly AX-series-only. The actual listening level is the **analog
rear-panel level pots**, which are outside the DSP/OSC domain entirely and
cannot be read or set remotely by any means.

## Remote level control: `/channel/<N>/xover/gain`

This is the practical answer to "set the volume remotely". It is a per-channel
gain trim (`f`, dB) in the DSP output path, with a genuine firmware setter
(`OSC: set Xgain`, validators `xeq_gain got an incorrect channel value` /
`… got an incorrect value`). The vendor app both reads and writes it, and it is
already implemented in both clients.

- Set channel 1 and channel 2 together for a master-like level (the app's
  "Channel Link" is just host-side mirroring of one channel's edits onto the
  other; there is no device-side link parameter).
- Live baseline read at investigation time: both channels `0.0 dB`.
- A live write-and-read-back to demonstrate that it *sticks* has **not** been
  run here (it changes real amp output and should be a deliberate, supervised
  test). The static + capture evidence that it is settable is strong regardless.
- Related-but-not-volume levers: `/channel/<N>/limiter` threshold (peak volts)
  sets an output *ceiling*; PEQ/DEQ band gains shift level per band.

## Other addresses clarified by the firmware

- **`/siggen`** — the iNuke DSP firmware **does** handle this (it is a real
  address literal). A live bare GET replied `/siggen ,if [0, 1000.0]`
  (looks like `[enabled/type=0, freq=1000 Hz]`; the app also has "sine wave
  level" strings, so a level argument likely exists too). It is simply not
  wired to any control in the iNuke DSP app (no "Utility" tab). It is a
  test-tone generator, **not** a program-volume control — do not enable it
  blind against connected speakers.
- **`/protect`** — a real firmware address with an error/reporting path, but a
  bare GET gets no reply from the live amp. Like `/lock`, it is most likely
  **pushed by the device** as an asynchronous protection-status report
  (thermal / DC / clip / short), not independently queryable. Not a control.
- **`/peaklimit`** — present in firmware; bare GET still gets no reply. Likely
  requires real arguments (matches the earlier capture-side finding).
- **`/lock` / `/unlock`** — a `lock_handler` exists; `/lock` is pushed once
  after `/online`. Write-protection state. Still deliberately untested against
  hardware (risk of locking the amp) — see PROTOCOL_NOTES.

## Corrections to PROTOCOL_NOTES.md

The firmware evidence overturns two statements in `PROTOCOL_NOTES.md`:

1. The `/gain` address-table entry / gotcha #4 guess that it "likely reflects a
   hardware-level (rear-panel trim pot?) state" — it is more precisely a
   **DSP-domain gain/mute report that is read-only by firmware design** (no
   setter exists). The rear-panel pots are a *separate*, analog, non-protocol
   thing. Practical upshot is the same (don't build a gain control on `/gain`),
   but the reason is now firmware-confirmed, not inferred.
2. The `/siggen` claim that it is "AX-series only" with "no UI path" — the
   **no-UI-path** part is correct, but `/siggen` itself **is handled by the
   iNuke DSP firmware** (confirmed by the address literal and a live reply).

## Confidence and open questions

**High confidence (firmware image + captures + live reads):** the architecture
family and memory map; the complete OSC address inventory; the settable-vs-
read-only classification; `/gain` read-only; `/siggen` handled; no
volume/master/mute address exists.

**Still open:**

- Whether `/gain`'s reported `[0,0,0,0]` is a live DSP-input-gain/ADC readback
  or a hardwired constant — needs a function-level look at `osc_send_gain`.
- `/info`'s third int (`5`) — unchanged across ampmodes; best guess an internal
  build/revision number.
- `/protect` payload shape and what event pushes it.
- `/siggen`'s full argument set (a level argument in particular) — untested,
  and enabling it is intentionally avoided.
- The bootloader / "USB uploader" flashing protocol (the updater's actual
  read/write exchange) — not reverse-engineered; out of scope for runtime
  control.

## How this was reproduced / limits

Reproduction is a plain PE parse + string/pointer scan of
`iNukeUsbUpdate_V1.3.exe` (no special tooling): dump `.rdata`, regex the ASCII
strings, and read the little-endian flash (`0x0800xxxx`) and SRAM
(`0x2000xxxx`) pointer values for the memory map. The classification comes
entirely from the handler string convention.

**Function-level disassembly was not completed** and would need Ghidra: GCC
built the image with LDR-literal-pool constants and merged string suffixes, and
the OSC dispatch is `strcmp`/token-based rather than a flat pointer table, so a
plain `capstone` Thumb sweep could not recover the exact load base or map
handler bodies. None of that is needed for the results above — the address
inventory and the gain read-only conclusion stand on the strings and the wire
captures — but it is the next step for anyone wanting the `osc_send_gain`
internals or a full annotated disassembly.
