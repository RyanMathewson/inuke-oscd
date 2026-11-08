# Audio diagnostics

Written 2026-11-08 while chasing why REW could not open the Scarlett Solo.

## `rew_audio_diag.ps1`

Restarts REW with its **native WASAPI library trace log** enabled, selects the
`EXCL:` input, and prints the result plus any native error.

Two non-obvious things make this necessary:

- REW's own `rew_output.txt` does **not** record why the WASAPI exclusive path
  fails -- it logs nothing at all. The real error only appears in
  `C:\Users\<you>\REW\csjsound-lib.log`, which exists only when the native
  library's log level is raised.
- The log level is a JVM system property, and REW is an install4j launcher, so
  it can be set via the **`INSTALL4J_ADD_VM_PARAMS`** environment variable --
  no admin rights and no editing `C:\Program Files\REW\roomeqwizard.vmoptions`.
  (`-DcsjsoundLibLogFile=<path>` did *not* take effect; the log goes to the
  default location regardless.)
- **REW only attempts to open the device on the first `EXCL:` selection after a
  restart.** Re-selecting it over the API logs nothing, so every attempt needs
  a fresh REW process. That is why this script restarts REW each time.

    powershell -ExecutionPolicy Bypass -File scripts/rew_audio_diag.ps1 -Rate 48000

## `amp_freq_scan.py`

Plays a sine at each of a set of frequencies through REW's signal generator and
records the iNuke's own input/output meters over USB, at a fixed receiver
volume. This is an **electrical** check of the whole chain that needs no
microphone: it verifies signal is reaching the amp and that the amp's DSP is
doing what its settings say (the two channels' outputs should differ by exactly
the difference between their PEQ curves).

Note `inuke meter` prints `%.4f`, which truncates badly at low levels -- the OSC
payload is full-precision float, so this script prints more digits.

## `amp_level_ladder.py`

Sweeps the receiver's volume at REW's real sweep level and reports what the amp
sees, to pick a safe measurement level. On this system the relationship came out
as roughly `amp input dBFS = receiver dB - 19`.

Both Python scripts assume the receiver is on COM3 and import `inuke_cli`
directly; they are diagnostics, not part of the CLI.
