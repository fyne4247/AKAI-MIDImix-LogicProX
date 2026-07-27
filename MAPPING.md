# Logic mapping sheet

Addresses are generated from `presets/logic-mode.midimix` by
`tools/make_mapping_doc.py` — they cannot drift from what is flashed.

Flash this layout first:

```sh
./logic-mode
```

## What each control should do

| Control | Sends | Assign to |
|---|---|---|
| Knob row 1, strip 1 | ch4 CC22 | **Pan**, track 1 |
| Knob row 1, strip 2 | ch4 CC23 | **Pan**, track 2 |
| Knob row 1, strip 3 | ch4 CC24 | **Pan**, track 3 |
| Knob row 1, strip 4 | ch4 CC25 | **Pan**, track 4 |
| Knob row 1, strip 5 | ch4 CC26 | **Pan**, track 5 |
| Knob row 1, strip 6 | ch4 CC27 | **Pan**, track 6 |
| Knob row 1, strip 7 | ch4 CC28 | **Pan**, track 7 |
| Knob row 1, strip 8 | ch4 CC29 | **Pan**, track 8 |
| Knob row 2, strip 1 | ch5 CC22 | **Send 1 level**, track 1 |
| Knob row 2, strip 2 | ch5 CC23 | **Send 1 level**, track 2 |
| Knob row 2, strip 3 | ch5 CC24 | **Send 1 level**, track 3 |
| Knob row 2, strip 4 | ch5 CC25 | **Send 1 level**, track 4 |
| Knob row 2, strip 5 | ch5 CC26 | **Send 1 level**, track 5 |
| Knob row 2, strip 6 | ch5 CC27 | **Send 1 level**, track 6 |
| Knob row 2, strip 7 | ch5 CC28 | **Send 1 level**, track 7 |
| Knob row 2, strip 8 | ch5 CC29 | **Send 1 level**, track 8 |
| Knob row 3, strip 1 | ch6 CC22 | **Send 2 level**, track 1 |
| Knob row 3, strip 2 | ch6 CC23 | **Send 2 level**, track 2 |
| Knob row 3, strip 3 | ch6 CC24 | **Send 2 level**, track 3 |
| Knob row 3, strip 4 | ch6 CC25 | **Send 2 level**, track 4 |
| Knob row 3, strip 5 | ch6 CC26 | **Send 2 level**, track 5 |
| Knob row 3, strip 6 | ch6 CC27 | **Send 2 level**, track 6 |
| Knob row 3, strip 7 | ch6 CC28 | **Send 2 level**, track 7 |
| Knob row 3, strip 8 | ch6 CC29 | **Send 2 level**, track 8 |
| Fader 1 | ch7 CC22 | **Volume**, track 1 |
| Fader 2 | ch7 CC23 | **Volume**, track 2 |
| Fader 3 | ch7 CC24 | **Volume**, track 3 |
| Fader 4 | ch7 CC25 | **Volume**, track 4 |
| Fader 5 | ch7 CC26 | **Volume**, track 5 |
| Fader 6 | ch7 CC27 | **Volume**, track 6 |
| Fader 7 | ch7 CC28 | **Volume**, track 7 |
| Fader 8 | ch7 CC29 | **Volume**, track 8 |
| Fader MASTER | ch7 CC30 | **Master / Output volume** |
| MUTE 1 | ch8 CC22 | **Mute**, track 1 |
| MUTE 2 | ch8 CC23 | **Mute**, track 2 |
| MUTE 3 | ch8 CC24 | **Mute**, track 3 |
| MUTE 4 | ch8 CC25 | **Mute**, track 4 |
| MUTE 5 | ch8 CC26 | **Mute**, track 5 |
| MUTE 6 | ch8 CC27 | **Mute**, track 6 |
| MUTE 7 | ch8 CC28 | **Mute**, track 7 |
| MUTE 8 | ch8 CC29 | **Mute**, track 8 |
| REC ARM 1 | ch8 CC32 | **Record Enable**, track 1 |
| REC ARM 2 | ch8 CC33 | **Record Enable**, track 2 |
| REC ARM 3 | ch8 CC34 | **Record Enable**, track 3 |
| REC ARM 4 | ch8 CC35 | **Record Enable**, track 4 |
| REC ARM 5 | ch8 CC36 | **Record Enable**, track 5 |
| REC ARM 6 | ch8 CC37 | **Record Enable**, track 6 |
| REC ARM 7 | ch8 CC38 | **Record Enable**, track 7 |
| REC ARM 8 | ch8 CC39 | **Record Enable**, track 8 |
| SOLO+MUTE 1 | ch8 CC42 | **Solo**, track 1 |
| SOLO+MUTE 2 | ch8 CC43 | **Solo**, track 2 |
| SOLO+MUTE 3 | ch8 CC44 | **Solo**, track 3 |
| SOLO+MUTE 4 | ch8 CC45 | **Solo**, track 4 |
| SOLO+MUTE 5 | ch8 CC46 | **Solo**, track 5 |
| SOLO+MUTE 6 | ch8 CC47 | **Solo**, track 6 |
| SOLO+MUTE 7 | ch8 CC48 | **Solo**, track 7 |
| SOLO+MUTE 8 | ch8 CC49 | **Solo**, track 8 |

## How to actually assign them

Order matters. This is the step people get wrong:

1. `Cmd+K` to open Controller Assignments.
2. Switch to **Expert** view (button, bottom-left). Easy view cannot do
   fixed track indices, and only Expert shows the **Input Message** field.
3. **Click the on-screen parameter first** so it is focused — e.g. track 1's
   volume fader in the mixer.
4. Click **Learn Mode**.
5. *Now* move the hardware control.
6. Still in Expert view, find the **Track** field. It defaults to
   `Selected Track` — change it to a **fixed track number**. Skip this and
   all eight faders fight over whichever track happens to be selected.
7. Turn Learn Mode off before clicking anything else, or you will overwrite
   the assignment you just made.

Repeat per control. Roughly 20 minutes for the full panel.

### If nothing happens

Watch the **Input Message** field while moving a fader:

- **It reacts** → Logic is receiving; only the assignment target is wrong.
- **It stays dead** → Logic is not receiving at all. Check
  Settings → MIDI → Inputs, and Setup → Control Surfaces → Setup (a control
  surface plugin holding the port hides the device from Controller
  Assignments). Confirm the hardware itself is transmitting with
  `python3 tools/midimix.py mon presets/logic-mode.midimix`.

## Banking (tracks 9–16 and beyond)

**Unresolved** — it depends on something not yet measured. The manual says
BANK LEFT/RIGHT "shift the 8 channels controlled by MIDImix", but not
whether the firmware does that internally or by transmitting a message.
Run `mon` and press them:

- **If they transmit** (`mon` flags them as NOT IN PRESET, showing a
  channel and CC): assign them in Logic to the next/previous track bank,
  and the fixed track numbers above become bank-relative.
- **If they transmit nothing**: they are firmware-internal and cannot be
  mapped. Fall back to a Logic key command for banking, or assign two
  spare buttons — e.g. REC ARM 7 and 8 — to bank navigation instead.

## Changing your mind later

Re-assigning a control in Logic needs no reflash — the preset only decides
*which message* each control sends, never what it does. Reflash only if you
want to move controls onto different channels or CCs, which is a layout edit
in `tools/make_logic_preset.py` followed by `./logic-mode`.

After any mapping session: quit Logic (it writes the assignments file on
exit), then copy `~/Library/Preferences/com.apple.logic.pro.cs` into
`backups/` and commit. Logic has no export for controller assignments.
