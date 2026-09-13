// Estimated peak-volts -> dBFS conversion for the limiter threshold display.
//
// The amp's actual 0dBFS reference voltage was never reverse-engineered --
// there's no wire field for it, and the legacy app's dBFS readout was
// purely a local UI calculation (see docs/PROTOCOL_NOTES.md: "dBFS is
// never on the wire"). The one data point available is a captured
// screenshot of the legacy app (captures/ui_config_tab.png): both channels
// showed their default threshold as 69.9 Vp / -1.7 dBFs. Solving
// dBFS = 20*log10(Vp / Vref) for that single pair gives Vref ~= 85.0V,
// which round-trips to -1.70 dBFS -- a suspiciously clean match, but still
// inferred from one rounded display value on one unit, not confirmed
// against the amp's actual internal calculation. Treat this as a labeled
// estimate, not a precision reproduction of the legacy app's formula.
export const DBFS_REFERENCE_VP = 85.0;

export function vpToDbfsEstimate(vp) {
  if (!(vp > 0)) return -Infinity;
  return 20 * Math.log10(vp / DBFS_REFERENCE_VP);
}

// Peak power into a resistive load, from the limiter threshold's peak
// voltage: P = Vp^2 / (2R). This is the standard formula (peak volts ->
// RMS-equivalent power), and unlike the dBFS estimate above it's a solid
// match, not a guess: the legacy app's Configuration tab showed "305.4 W"
// for 69.9 Vp @ 8 ohms, and this formula reproduces that to the decimal
// (305.3756 -> rounds to 305.4). Also consistent with PROTOCOL_NOTES.md's
// finding that the Load dropdown sends nothing on the wire -- it's a
// client-side-only convenience calculation there too, never read from or
// written to the amp.
export function peakWatts(vp, ohms) {
  if (!(vp > 0) || !(ohms > 0)) return 0;
  return (vp * vp) / (2 * ohms);
}
