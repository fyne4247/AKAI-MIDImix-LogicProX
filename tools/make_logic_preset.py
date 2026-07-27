#!/usr/bin/env python3
"""Generate a corrected Logic-mode preset for the AKAI MIDI Mix.

Why this exists
---------------
The 2016 `MIDIMix_LogicProX.midimix` found online is broken. Its 57 control
records resolve to only 41 unique (channel, CC) addresses: all three button
rows are stacked on ch2 CC22-29, so MUTE n, REC ARM n and SOLO+MUTE n all
transmit the identical message. They differ only in the per-button `type` byte,
which is a device-side behaviour flag and is not transmitted. Under that preset
Logic cannot distinguish the three button rows at all -- MIDI Learn will grab
whichever parameter was focused last and buttons appear to triple-trigger.

This generator produces a preset where all 57 controls are unique, and which is
also fully disjoint from `mGB arduinoboy.midimix` so the two can be hot-swapped
without assignments from one ever firing under the other.

Channel budget (wire values are 0-based; shown 1-based here):

    mGB preset occupies   ch1 entirely, and ch2 CC31-38 / 41-48 / 51-58
    this preset occupies  ch4, ch5, ch6 (knobs), ch7 (faders), ch8 (buttons)

Knobs and faders keep the 2016 layout, which was already sound and is what the
2016 controller-assignment file expects. Only the buttons are relocated -- onto
ch8, which the mGB preset never touches.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midimix import build_preset, parse_preset, control_map  # noqa: E402

OUT = "presets/logic-mode.midimix"

# --- knobs: 3 rows x 8 strips, row selects channel, strip selects CC ---------
# row 1 -> ch4 (pan), row 2 -> ch5 (send 1), row 3 -> ch6 (send 2)
KNOB_CHANS = [3, 4, 5]          # 0-based wire values for ch4/5/6
KNOB_CC = list(range(22, 30))   # CC22..CC29, one per strip

knobs = []
for strip in range(8):
    for row in range(3):
        knobs.append((KNOB_CHANS[row], KNOB_CC[strip]))

# --- faders: 8 channel faders + MASTER, all on ch7 ---------------------------
faders = [(6, 22 + i) for i in range(9)]        # ch7, CC22..CC30

# --- buttons: 3 rows of 8 on ch8, each row in its own CC block ---------------
# Row order in the format is MUTE, REC ARM, SOLO+MUTE.
# Record layout is (channel, type, cc) -- NOT (type, channel, cc). Verified
# against hardware: the mGB preset stores (0, 1, cc) and those buttons were
# observed transmitting on ch1. type=1 matches both stock presets.
BUTTON_CH = 7                                   # 0-based -> ch8
BUTTON_ROW_BASE = [22, 32, 42]                  # MUTE / REC ARM / SOLO+MUTE

buttons = []
for row in range(3):
    for n in range(8):
        buttons.append((BUTTON_CH, 1, BUTTON_ROW_BASE[row] + n))


def main():
    blob = build_preset(knobs, faders, buttons)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as fh:
        fh.write(blob)
    print(f"wrote {OUT} ({len(blob)} bytes)")

    # self-check: every control must be uniquely addressable
    k, f, b = parse_preset(OUT)
    addrs = [a for a in k] + [a for a in f] + [(ch, cc) for ch, _, cc in b]
    assert len(addrs) == 57, len(addrs)
    if len(set(addrs)) != 57:
        raise SystemExit(f"FAIL: only {len(set(addrs))} unique addresses")
    print("  ok: 57 controls -> 57 unique addresses")

    # self-check: must not collide with the mGB rig
    mgb = "mGB arduinoboy.midimix"
    if os.path.exists(mgb):
        overlap = set(control_map(k, f, b)) & set(control_map(*parse_preset(mgb)))
        if overlap:
            raise SystemExit(f"FAIL: collides with {mgb} at {sorted(overlap)}")
        print(f"  ok: disjoint from {mgb}")


if __name__ == "__main__":
    main()
