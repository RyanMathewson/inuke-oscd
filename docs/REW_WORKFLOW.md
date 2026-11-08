# Room EQ with REW

`inuke rew loop` links [Room EQ Wizard](https://www.roomeqwizard.com/) (REW)
to the amp. It measures the room, has REW fit the amp's 8 PEQ bands to your
target, writes them to the amp, measures again to check the result, and
repeats until you're happy.

## Setup

1. **REW V5.40 or later.** The REST API used here is only enabled in 5.40+.
   On 5.31.3 (the last 5.3x release), `-api` just gets the dialog "API not
   supported in this build". REW's built-in updater can install 5.40.
2. **Start REW with the API on:** `"C:\Program Files\REW\roomeqwizard.exe" -api`,
   or Preferences -> API -> start the server. It listens on
   `http://127.0.0.1:4735` (the API's own spec is at `/doc.json`).
3. **Set up measuring in REW** as usual: mic and its calibration file,
   input/output device, sweep level. Pick the output that feeds the amp
   channel you're correcting.
4. **Check the link:** `inuke rew status`.

### REW Pro

REW's free version lets the API read data, import responses, and run the EQ
commands, which is everything here except *starting a sweep*. That, and a
few settings such as measurement naming, return HTTP 401 without the Pro
upgrade. `inuke rew status` tells you which you have.

- **With Pro:** the loop starts each sweep itself after you press Enter.
- **Without Pro:** the loop asks you to click **Measure** in REW and press
  Start. It watches REW's measurement list and continues as soon as the new
  measurement appears. Pick a mode explicitly with `--measure api|manual`.

## The AV receiver (RS-232)

If the amp is fed from an Onkyo receiver with an RS-232 port, `inuke onkyo` can
drive it, and `inuke rew loop` can use it. This matters more than it sounds:
the amp's own `/gain` is read-only on real hardware, and the only level it will
accept is `/channel/N/xover/gain`, which is part of what the loop is fitting.
**The receiver's master volume is the only level in the whole signal path that
can be set remotely.**

```
inuke onkyo --port COM3 status
inuke onkyo --port COM3 mode Direct
inuke onkyo --port COM3 check --expect-input DVD
```

Set `INUKE_ONKYO_PORT` to avoid passing `--port` every time. `check` exits
non-zero and says what is wrong, so it also works as a pre-flight in a script.

In the loop:

```
inuke rew loop --channel 1 --onkyo-port COM3 --onkyo-input DVD --onkyo-level -35
```

Before every sweep the loop then refuses to measure unless the receiver is on,
unmuted, on `--onkyo-input` and in `--onkyo-mode` (default **Direct**). This is
the check worth having: measuring in the wrong mode does not fail, it just
quietly returns the wrong room, and the loop will then fit the amp's PEQ to it.
Pass `--onkyo-mode any` to skip the check.

It earns its keep. On a TX-SR806 the receiver **switches mode by itself** when
the incoming stream changes between stereo and multichannel -- it selected
Theater-Dimensional, a virtual surround mode, the moment the HDMI stream became
7.1. Nothing announces that; the guard caught it.

### Which mode -- it depends on the source

Measured on a TX-SR806 by playing a tone and watching the amp's own input meters
over USB (`inuke meter`):

| Source | Direct | Stereo / All Ch Stereo |
|---|---|---|
| 2-channel | **sub pre-out dead** (`0.0000` at the amp) | signal present |
| multichannel with a real LFE channel | **correct** (0.00005 -> 0.00583) | downmixes |

So **Direct is the default**, because the recommended workflow sends the sweep on
a discrete LFE channel (see below) and Direct then passes it to the sub while
applying no room correction, no upmix and no virtual surround. But for a plain
2-channel measurement Direct is exactly wrong -- with no LFE channel there is
nothing for it to route and the subs go silent. Use `--onkyo-mode Stereo` there.

The ISCP command set has **no Audyssey on/off command**. Direct bypasses room
correction; if you measure in Stereo, turn Audyssey off at the receiver for
accurate runs.

With `--onkyo-level` the loop sets that level for each sweep and puts the
listening level back afterwards, including when it is interrupted, so every
measurement in a run is taken at the same known level. Levels are dB (`-35`) or
`raw:NN`. A cap (`--onkyo-max-raw`, default 70 = -12 dB) stops a typo becoming a
loud sweep; `--force` on `inuke onkyo volume` overrides it.

Notes on the protocol, from a TX-SR806:

- `MVL` carries the volume as **hex, one unit per dB**: raw 82 (`0x52`) is 0 dB,
  so raw 42 (`0x2A`) is -40.0 dB. `--zero-db-raw` sets that reference for
  another model.
- The port is opened exclusively, so this cannot share an adapter with Home
  Assistant's Onkyo Serial integration at the same time.

## Measuring the subs only, via the LFE channel

If the receiver drives mains and a centre as well as the subs, a sweep sent to
L/R measures **all of them**, and fitting the sub amp's PEQ to that response is
wrong -- it uses the subwoofer to correct peaks the mains are making.

Send the sweep on a discrete **LFE** channel instead:

1. Windows: Sound -> Playback -> the receiver -> **Configure** -> **7.1 Surround**,
   with **Subwoofer** ticked. Leave the speakers marked full-range so Windows does
   no bass management of its own -- you want exactly one place doing that, and it
   should be the receiver.
2. **Restart REW.** It caches device capabilities at startup and will keep
   reporting 2 channels until it is restarted.
3. In REW pick the **`EXCL:` version** of the receiver output. The plain entry is
   stock Java Sound, which is limited to 16-bit **and stereo**, so it can never
   offer LFE. The `EXCL:` entry exposes all 8 channels.
4. Set the output channel to **LFE**, and the receiver to **Direct**.

Check it worked by playing a tone well above the subwoofer crossover -- say
500 Hz -- on the LFE channel. If routing is right it is **inaudible**: it reaches
only the sub, whose low-pass removes it. If you hear it from the mains, the
receiver is redistributing LFE and its speaker setup needs looking at.

## Two subwoofers, one per channel

If both channels drive identical subwoofers from the same mono feed, use:

```
inuke rew loop --channel both ...
```

One measurement, one fit, written **identically** to both channels.

This is not a convenience. With two subs fed the same signal and one microphone,
the mic hears their **sum** -- there is nothing in that measurement to attribute
to an individual channel, so "fit channel 1" does not describe anything real
unless you physically silence the other sub. Fitting the sum once and driving
both channels the same is the correct operation for that setup.

Note that no amp mode does this for you. In BIAMP1 the amp distributes one mono
input to both channels -- the amp's own meters show `in A` and `in B` identical
-- but each channel's PEQ stays independent, and BIAMP1's actual purpose is the
opposite (a sub plus a satellite, filtered differently). Symmetry has to be set.

The loop still measures and fits against channel 1; the other channel only
receives the result. `[u]ndo` restores **each** channel to its own original EQ,
not a shared one, and the session log records both channels' starting bands. If
the channels start out mismatched the loop says so before measuring, because the
baseline measurement was then made by two differently-equalised subs.

`inuke scan`-style electrical checks are worth running first here: see
`scripts/amp_freq_scan.py`, which uses the amp's own meters to confirm both
channels behave identically, with no microphone involved.

## The loop

```
inuke rew loop --channel 1 --shape full --lf-cutoff 35 --range 20-500
```

1. Shows the channel's current PEQ. That's what **[u]ndo** restores.
2. **Measurement 1**, taken with whatever EQ is already on the amp.
3. **Fit.** REW's *Match target* fits up to 8 filters. The loop shows them,
   any values it had to clamp, how far the room is from the target now, and
   how far REW predicts it will be with the EQ.
4. **Write** to the amp (`Y`), skip (`n`), or change settings first (`s`).
   Every band is read back after writing, and dropped writes are retried.
5. **Verification measurement**, reported two ways:
   - *measured vs target*: how good the result actually is.
   - *measured vs prediction*: whether the room did what REW expected. A big
     gap here means the mic moved, or the amp's filters don't behave the way
     REW models them (see "Shelves" below).
6. **What next?**
   - `r`: re-fit using all measurements so far.
   - `m`: take another measurement first (move the mic slightly for a more
     robust average), then re-fit.
   - `s`: change the fit settings, then re-fit.
   - `k`: keep the current EQ and finish.
   - `u`: restore the original EQ and finish.

Settings you can type at the `s` prompt (all optional):

```
range=20-300  boost=3  overall-boost=0  flatness=1  shelves=on
shape=full|bass-limited|subwoofer|driver|none  lf=35  q=6  level=80|auto
```

Command-line options with the same meaning: `--range`, `--max-boost`,
`--overall-max-boost`, `--flatness`, `--shelves/--no-shelves`, `--shape`,
`--lf-cutoff`, `--max-q`, `--target-level`, plus `--house-curve FILE`.
Anything you don't set keeps whatever REW's EQ window has, so you can
fine-tune there too. The match range and boost limits are global REW
settings. The target shape is applied to each measurement the loop fits.

`-y` runs one measure/fit/write/verify pass with no prompts. Every step is
logged to `rew-eq-ch<N>-<time>.json` (or `--log FILE`), including the
original bands.

When you're done, `inuke preset store <slot> <name>` saves the result to one
of the amp's onboard presets, and `inuke arp save` saves it to a file.

### How re-fitting works

The amp has only 8 bands, so new filters can't be stacked on old ones. Each
fit therefore works from an estimate of the room **without** EQ:

- Every measurement is taken with some known EQ on the amp.
- The loop sets those bands as the measurement's filters in REW. REW's
  "equalised" response is then measured + EQ, so the uncorrected room is
  `2 * measured - equalised`. That uses REW's own model of the filters.
- Each estimate is imported into REW (`... - EQ removed`). Once there is
  more than one, they're combined with REW's *dB average* (`room estimate
  (avg of N)`), and *Match target* runs on that.

So the EQ never has to be switched off to re-measure, and each extra
measurement makes the fit more robust. All of these measurements stay in
REW, where you can inspect them in its graphs.

The target level is calculated by REW on the first fit and then held fixed,
so results stay comparable between passes. It's recalculated when you change
`shape`/`lf`, or type `level=auto`.

The fit starts from REW's measurements with **Var** smoothing applied, as
REW recommends for EQ.

### Other commands

```
inuke rew fit 3 [--apply --channel 1]   # fit to measurement 3 as-is (treated as the uncorrected room)
inuke rew push 3 --channel 1            # write measurement 3's current REW filters (e.g. hand-tuned) to the amp
inuke rew pull 3 --channel 1            # load the amp's bands into measurement 3's REW filters
```

Measurements can be named by their index in REW's list (from 1) or by UUID.

## How REW filters map to the amp

| REW filter            | amp band | notes |
|-----------------------|----------|-------|
| `PK`                  | `PEQ`    | same shape: REW's PK matches an RBJ-cookbook peaking biquad to within 0.05 dB |
| `LS`, `LS 12dB`       | `LS12`   | sent with Q 0.707 (REW's shelves have no Q) |
| `HS`, `HS 12dB`       | `HS12`   | Q 0.707 |
| `LS 6dB` / `HS 6dB`   | `LS6` / `HS6` | |
| anything else         | —        | refused (the amp has no equivalent) |

REW is set to its **Generic** equaliser, and only slots 1–8 are marked
"auto", so *Match target* never uses more than the amp's 8 bands.

Values are clamped before they're written, and every clamp is reported:
Q to 0.15–10 (change the top with `--max-q`), gain to ±24 dB, frequency to
20 Hz–20 kHz. These are **not** documented device limits. The vendor app's
saved presets show Q values from 0.15 up to exactly 10.0, which looks like
its UI's range. The firmware's real validators haven't been characterised
(see [FIRMWARE_NOTES.md](FIRMWARE_NOTES.md)).

### Shelves: the frequency convention

REW places a shelf's frequency at the corner on the *shelf* side of the
curve. RBJ-cookbook DSP puts it at the *midpoint* of the transition.
Measured against REW 5.40 Beta 135, the two agree to within 0.04 dB when:

- **12 dB shelves:** midpoint = REW frequency × 10^(|gain|/80)
- **6 dB shelves:** midpoint = REW frequency × 10^(|gain|/40)
- **High shelves:** divide instead of multiply.

At ±6 dB that shift is enough to move the curve by about 1 dB.

**Which convention the amp uses is not known yet.** The default
(`--shelf-freq midpoint`) assumes the common RBJ one and converts. Shelves
are off unless you enable them (`--shelves` or REW's own setting). If a
verification measurement with shelves in use shows a large *measured vs
prediction* gap around the shelf, try `--shelf-freq corner`. If that fixes
it, please record the result here.

## Trying it without hardware

`inuke rew loop --channel 1 --simulate` swaps in a simulated amp and room
(room modes, speaker roll-off, and a little random ripple per measurement)
and imports each "measurement" into the real REW. Everything else runs for
real, so it's a good way to learn the loop and REW's settings before
setting up a mic.
