# Phase 3 handoff — physical BANK buttons and channel-strip view

**Date:** 2026-07-27
**Result:** **physical banking PASSED; channel-button mapping remains next**
**Repo path:** project root on `master`
**Primary code:** `tools/mcu_surface.py`
**Current hardware preset:** `mgb70.midimix` (flashed to the MIDI Mix)

This continues `phase2handoff.md`. Phase 2 made the faders and fixed Master
work. This phase established what the MIDI Mix panel's fixed buttons actually
send and connected the physical BANK LEFT/RIGHT buttons to Logic banking.

---

## 1. Final result

**User-confirmed passed:** the AKAI's physical **BANK LEFT** and **BANK RIGHT**
buttons now move the active eight-fader Logic Control bank.

The physical MASTER remains independent of banks through `MIDI Mix Fixed`, as
established in Phase 2.

The remaining Phase 3 work is mapping the eight MUTE buttons, eight REC ARM
buttons, and SOLO layer to their corresponding Mackie functions. Do not call
the entire button phase complete yet.

---

## 2. What the fixed panel controls really transmit

The earlier monitoring report misleadingly labeled all three-byte messages as
“CC.” The status byte is decisive: MIDI CC and MIDI Note can share the same
number without colliding.

| Panel control | Confirmed wire messages | Meaning in the bridge |
|---|---|---|
| BANK LEFT | `90 19 7f` press; `80 19 7f` release | ch1 Note 25 |
| BANK RIGHT | `90 1a 7f` press; `80 1a 7f` release | ch1 Note 26 |
| SOLO | Note 27 (confirmed) | reserved for later solo-layer mapping |
| SEND ALL | no unique message | retransmits current control positions |

`90` is Note On on MIDI channel 1; `80` is Note Off on MIDI channel 1.
Therefore **Note 25 is not CC25**. The bank buttons were never protocol-level
collisions with the old third-row knob CC25/26 assignments.

### SEND ALL is not a mappable button

SEND ALL causes the hardware to resend current values using the controls'
ordinary messages. One observed burst was CC1, CC3, CC5, CC7, and CC69. Those
are the current values of regular controls—not a SEND ALL identifier.

Leave SEND ALL unmapped. Reassigning those knobs or the Master CC would only
change the messages in the burst; it cannot give SEND ALL its own MIDI address.

---

## 3. Current `mgb70` hardware preset

The user created and flashed `mgb70.midimix` during investigation. It preserves
the working fader and button layout and moves the third knob row from CC21–28
to CC71–78:

| Control group | Current input |
|---|---|
| Knob row 1 | ch1 CC1–8 |
| Knob row 2 | ch1 CC11–18 |
| Knob row 3 | ch1 CC71–78 |
| Faders 1–8 | ch1 CC61–68 |
| Physical MASTER | ch1 CC69 → `MIDI Mix Fixed` ch16 CC119 |
| MUTE 1–8 | ch1 CC31–38 |
| REC ARM 1–8 | ch1 CC51–58 |
| SOLO+MUTE layer | ch1 CC41–48 |

The third-row remap is perfectly safe to keep and simplifies the future knob
layout. It is **not required** to make Bank Left/Right safe, because the fixed
bank controls are Notes, not CCs.

The AKAI Editor can configure the programmable MUTE/SOLO/REC ARM controls as
CC or Note input. That may be desirable later, but no change is needed before
mapping them: their current CC addresses are already distinct.

---

## 4. Bridge implementation

`tools/mcu_surface.py` now:

1. listens to the physical MIDI Mix alongside the virtual `MIDI Mix MCU` ports;
2. recognizes ch1 Note 25 and Note 26, including their Note Off messages;
3. on a physical press, emits the correct Mackie Control gesture:
   - Bank Left: ch1 Note 46 On/Off
   - Bank Right: ch1 Note 47 On/Off
4. intentionally ignores SEND ALL, Note 27/SOLO, and the programmable channel
   buttons for now.

The running bridge logs a low-rate diagnostic while testing:

```text
← MIDI Mix  90 19 7f  [bank candidate]
→ host  90 2e 7f  (bank left)
→ host  80 2e 00  (bank left)
banked left ×1
```

Restart `mixer-mode.command` after code changes. The terminal must remain open
while mixing.

---

## 5. Logic banking view: why sends, Stereo Out, and Master appeared

This was a Logic view-mode setting, not bridge routing.

In **All** Channel Strip View Mode, Logic banks through its wider mixer
inventory—including aux/send returns, outputs, and Master. That is why a later
bank in a small project landed on send returns, Stereo Out, and Master.

For ordinary track mixing, set the **control-surface group's** Channel Strip
View Mode to **Arrange** or **Tracks**, rather than All:

1. Logic Pro → Control Surfaces → Setup.
2. Select the group containing `MIDI Mix MCU`.
3. In the group inspector, set **Channel Strip View Mode** to Arrange or Tracks.
4. Type `bank home` in the bridge terminal if a reset to the first bank is
   wanted.

The blue Tracks/All selector in the Mixer and the control-surface group's view
are related but not the same setting. Logic documents All view as including
channel-strip types such as auxes independently of Tracks, while Arrange follows
the Tracks-area order.

---

## 6. Verification completed

- Bank Left raw press/release captured as ch1 Note 25: **passed**.
- Bank Right raw press/release captured as ch1 Note 26: **passed**.
- Bridge translation Note 25/26 → MCU Bank Left/Right Note 46/47:
  **user-confirmed passed**.
- `mgb70.midimix` decoded and confirmed with knob row 3 at CC71–78: passed.
- `python3 tools/selftest.py`: passed.
- `python3 tools/mcu_surface.py selfcheck`: all pure routing/protocol checks
  pass; the virtual-port creation subtest returns `-10833` only in the agent's
  inactive non-GUI CoreMIDI session.

---

## 7. Next work

1. Map MUTE → MCU Mute notes 16–23.
2. Map REC ARM → MCU REC/RDY notes 0–7.
3. Decide how the panel SOLO button and SOLO+MUTE layer should behave, then map
   it to MCU Solo notes 8–15.
4. Add the three knob rows (pan / sends) using the current `mgb70` addresses.
5. Add soft takeover for absolute faders so bank/project changes cannot cause a
   jump on the first physical move.
