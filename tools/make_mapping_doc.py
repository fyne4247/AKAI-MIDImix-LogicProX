#!/usr/bin/env python3
"""Generate MAPPING.md from presets/logic-mode.midimix.

The address table is derived from the preset file rather than typed by hand, so
the document cannot drift from what is actually flashed to the device. Re-run
this after changing the preset layout.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midimix import parse_preset  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET = os.path.join(ROOT, "presets", "logic-mode.midimix")
OUT = os.path.join(ROOT, "MAPPING.md")

KNOB_ROW_TARGET = ["Pan", "Send 1 level", "Send 2 level"]
BUTTON_ROW_TARGET = ["Mute", "Record Enable", "Solo"]


def main():
    knobs, faders, buttons = parse_preset(PRESET)
    L = []
    w = L.append

    w("# Logic mapping sheet\n")
    w("Addresses are generated from `presets/logic-mode.midimix` by")
    w("`tools/make_mapping_doc.py` — they cannot drift from what is flashed.\n")
    w("Flash this layout first:\n")
    w("```sh\n./logic-mode\n```\n")

    w("## What each control should do\n")
    w("| Control | Sends | Assign to |")
    w("|---|---|---|")
    for row in range(3):
        for strip in range(8):
            ch, cc = knobs[strip * 3 + row]
            w(f"| Knob row {row + 1}, strip {strip + 1} | ch{ch + 1} CC{cc} | "
              f"**{KNOB_ROW_TARGET[row]}**, track {strip + 1} |")
    for i, (ch, cc) in enumerate(faders):
        if i == 8:
            w(f"| Fader MASTER | ch{ch + 1} CC{cc} | **Master / Output volume** |")
        else:
            w(f"| Fader {i + 1} | ch{ch + 1} CC{cc} | **Volume**, track {i + 1} |")
    for row in range(3):
        for n in range(8):
            ch, _t, cc = buttons[row * 8 + n]
            label = ["MUTE", "REC ARM", "SOLO+MUTE"][row]
            w(f"| {label} {n + 1} | ch{ch + 1} CC{cc} | **{BUTTON_ROW_TARGET[row]}**, "
              f"track {n + 1} |")
    w("")

    w("## How to actually assign them\n")
    w("Order matters. This is the step people get wrong:\n")
    w("1. `Cmd+K` to open Controller Assignments.")
    w("2. Switch to **Expert** view (button, bottom-left). Easy view cannot do")
    w("   fixed track indices, and only Expert shows the **Input Message** field.")
    w("3. **Click the on-screen parameter first** so it is focused — e.g. track 1's")
    w("   volume fader in the mixer.")
    w("4. Click **Learn Mode**.")
    w("5. *Now* move the hardware control.")
    w("6. Still in Expert view, find the **Track** field. It defaults to")
    w("   `Selected Track` — change it to a **fixed track number**. Skip this and")
    w("   all eight faders fight over whichever track happens to be selected.")
    w("7. Turn Learn Mode off before clicking anything else, or you will overwrite")
    w("   the assignment you just made.\n")
    w("Repeat per control. Roughly 20 minutes for the full panel.\n")

    w("### If nothing happens\n")
    w("Watch the **Input Message** field while moving a fader:\n")
    w("- **It reacts** → Logic is receiving; only the assignment target is wrong.")
    w("- **It stays dead** → Logic is not receiving at all. Check")
    w("  Settings → MIDI → Inputs, and Setup → Control Surfaces → Setup (a control")
    w("  surface plugin holding the port hides the device from Controller")
    w("  Assignments). Confirm the hardware itself is transmitting with")
    w("  `python3 tools/midimix.py mon presets/logic-mode.midimix`.\n")

    w("## Banking (tracks 9–16 and beyond)\n")
    w("**Unresolved** — it depends on something not yet measured. The manual says")
    w("BANK LEFT/RIGHT \"shift the 8 channels controlled by MIDImix\", but not")
    w("whether the firmware does that internally or by transmitting a message.")
    w("Run `mon` and press them:\n")
    w("- **If they transmit** (`mon` flags them as NOT IN PRESET, showing a")
    w("  channel and CC): assign them in Logic to the next/previous track bank,")
    w("  and the fixed track numbers above become bank-relative.")
    w("- **If they transmit nothing**: they are firmware-internal and cannot be")
    w("  mapped. Fall back to a Logic key command for banking, or assign two")
    w("  spare buttons — e.g. REC ARM 7 and 8 — to bank navigation instead.\n")

    w("## Changing your mind later\n")
    w("Re-assigning a control in Logic needs no reflash — the preset only decides")
    w("*which message* each control sends, never what it does. Reflash only if you")
    w("want to move controls onto different channels or CCs, which is a layout edit")
    w("in `tools/make_logic_preset.py` followed by `./logic-mode`.\n")
    w("After any mapping session: quit Logic (it writes the assignments file on")
    w("exit), then copy `~/Library/Preferences/com.apple.logic.pro.cs` into")
    w("`backups/` and commit. Logic has no export for controller assignments.")

    with open(OUT, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {OUT} ({len(L)} lines)")


if __name__ == "__main__":
    main()
