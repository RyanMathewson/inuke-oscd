# inuke-cli

A cross-platform command-line client for Behringer iNuke DSP power amps,
built on the same reverse-engineered USB/HID/OSC protocol as the
[web app](../webapp/) -- see [`../docs/PROTOCOL_NOTES.md`](../docs/PROTOCOL_NOTES.md).
Where the web app is the point-and-click replacement for the vendor's
iNuke Remote Connect GUI, this is for scripting, automation, and
tech-savvy users who'd rather type a command than click through tabs.

Talks to the amp directly via [hidapi](https://pypi.org/project/hidapi/);
works anywhere hidapi does (Windows/macOS/Linux).

## Install

```
cd cli
pip install -e .
```

This installs the `inuke` command. (On Linux you may need a udev rule
granting your user access to the device -- see hidapi's docs -- since
running as root just to talk to a USB amp isn't a good habit.)

## Usage

Every subcommand connects, does one thing, and disconnects -- there's no
persistent session. If a command times out waiting for a reply, send
`/online` first (the amp stops replying to reads until it's told a session
is starting -- see PROTOCOL_NOTES.md, "Critical gotchas" #3):

```
inuke online
```

Get vs. set follows one rule throughout: pass no value arguments to read a
parameter, pass all of them to write it (partial argument lists are
rejected rather than guessed at).

```
inuke info                              # device name + firmware
inuke mode                              # read amp mode
inuke mode bridged                      # set amp mode (case-insensitive)
inuke name "Stage Left"                 # rename the amp

inuke peq 1 3                           # read channel A, PEQ band 3
inuke peq 1 3 LS12 4000 -3.5 0.7        # set it: type freq gain Q

inuke xover hp 1                        # read channel A high-pass
inuke xover hp 1 BUT24 80               # set it: type freq
inuke xover gain 2 -1.5                 # crossover gain, channel B

inuke deq filt 1 1 BP 200 1.0           # DEQ 1 sidechain filter
inuke deq comp 1 1 7.0 -13.0 3.0        # DEQ 1 compressor: gain thresh ratio
inuke deq time 1 1 5 50                 # DEQ 1 timing: attack release

inuke delay 2 1.2 180                   # channel B: 1.2ms, phase 180
inuke limiter 1 69.9 100 50             # threshold(Vp) release(ms) hold(ms)

inuke preset list                       # all 20 onboard slots
inuke preset store 5 "MySound"          # snapshot current state -> slot 5
inuke preset recall 5                   # replace live state with slot 5

inuke gain                              # read-only (SET doesn't stick -- see docs)
inuke status                            # full parameter dump (like a vendor-app connect sweep)
inuke status --json                     # ...as machine-readable JSON

inuke meter                             # stream live meter levels for 10s (Ctrl+C to stop)
inuke monitor                           # print every message the amp sends, unfiltered

inuke raw /ampmode                      # escape hatch: arbitrary GET
inuke raw /ampmode --type s --args STEREO   # escape hatch: arbitrary SET
```

Add `--json` before the subcommand to get machine-readable output from any
read command, for scripting.

### Backup / restore / `.arp` presets

`backup`/`restore` snapshot the full live DSP state (both channels: PEQ,
crossover, dynamic EQ, delay/phase, limiter, amp mode) to a JSON file and
back -- the script-friendly option, easy to diff, edit, or generate:

```
inuke backup my-amp.json
inuke restore my-amp.json      # prompts for confirmation; overwrites live state
inuke restore my-amp.json -y   # skip the prompt
```

`arp save`/`arp load` do the same thing, but read and write the vendor
app's own `.arp` preset file format directly, so files round-trip with the
legacy iNuke Remote Connect app:

```
inuke arp save my-amp.arp
inuke arp load my-amp.arp      # prompts for confirmation; overwrites live state
inuke arp load my-amp.arp -y   # skip the prompt
```

Neither of these is the same thing as the 20 onboard preset slots
(`inuke preset store/recall`), which live on the amp itself -- `backup`/
`arp save` capture to a file on your machine instead.

## Testing

```
python -m unittest discover -v
```

No hardware needed -- tests inject a fake HID transport
(`tests/fake_transport.py`) that speaks the same wire framing a real amp
would. The OSC codec tests assert byte-for-byte against the actual captured
packets quoted in PROTOCOL_NOTES.md.

## Library use

`inuke_cli.protocol.INukeClient` is usable directly from Python, independent
of the CLI:

```python
from inuke_cli.protocol import INukeClient

with INukeClient() as amp:
    amp.go_online()
    print(amp.get_amp_mode())
    amp.set_peq(1, 3, "LS12", 4000.0, -3.5, 0.7)
```
