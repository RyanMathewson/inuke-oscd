"""Protocol constants from docs/PROTOCOL_NOTES.md's Quick Reference / address table."""

AMP_MODES = ["DUAL", "STEREO", "BIAMP1", "BIAMP2", "BRIDGED"]

AMP_MODE_LABELS = {
    "DUAL": "Dual Mono",
    "STEREO": "Stereo",
    "BIAMP1": "Bi-Amp 1",
    "BIAMP2": "Bi-Amp 2",
    "BRIDGED": "Bridge (Channel A+B)",
}

# Enum order used by /preset/save's ampmode_enum arg (matches the UI's Mode
# button order and the amp's own empty-slot default of DUAL=0).
AMP_MODE_ENUM = {"DUAL": 0, "STEREO": 1, "BIAMP1": 2, "BIAMP2": 3, "BRIDGED": 4}
AMP_MODE_BY_ENUM = ["DUAL", "STEREO", "BIAMP1", "BIAMP2", "BRIDGED"]

# PEQ type "OFF" is applied via the band's enable toggle in the vendor UI,
# not a dropdown entry -- see PROTOCOL_NOTES.md "Critical gotchas" #2. The
# CLI exposes OFF as a settable type directly since it has no separate
# enable control.
PEQ_TYPES = ["OFF", "PEQ", "LS6", "LS12", "HS6", "HS12"]

XOVER_FAMILIES = ["BUT", "BES", "LR"]
XOVER_SLOPES = [6, 12, 18, 24, 48]

DEQ_FILT_TYPES = ["OFF", "BP", "LP6", "LP12", "HP6", "HP12"]

PRESET_SLOT_COUNT = 20
CHANNELS = (1, 2)
PEQ_BANDS = range(1, 9)
DEQ_BANDS = (1, 2)
