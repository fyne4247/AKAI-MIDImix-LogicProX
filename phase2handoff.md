# Phase 2 handoff — physical faders, fixed Master, and first-bank routing

**Date:** 2026-07-27
**Result:** **PASSED**
**Repo path:** project root on `master`
**Primary code:** `tools/mcu_surface.py`, launcher `mixer-mode.command`

This document continues `phase1handoff.md`. Phase 1 proved that Logic accepts
the virtual Mackie/Logic Control surface. Phase 2 connects the *real* AKAI MIDI
Mix faders to it, makes the physical MASTER permanently independent of banks,
and establishes the correct first eight-track bank.

---

## 1. Phase 2 goal and final result

The desired mixer behavior was:

- physical faders 1–8 control Logic's first eight channel strips;
- physical **MASTER** controls Logic's actual **Master** channel, never a
  banked strip and never Stereo Out by accident;
- no MIDI Mix hardware preset flash;
- real MIDI Mix data must not leak directly into Logic alongside bridge data.

**User-confirmed final result:** after the base-identity fix and `bank home`,
the eight physical faders address the intended first track bank and MASTER
controls Logic's Master channel through a permanent, separate assignment.

This was superseded during Phase 3 by the user-created, flashed `mgb70.midimix`
preset. See `phase3handoff.md` for its current layout.

---

## 2. The two discoveries that made it work

### 2.1 `0x11` is an extender, not the base surface

The first Phase 2 build answered every Mackie-family SysEx Device Query that
Logic sent. Logic subsequently connected the port as device ID **`0x11`**.
That is a Logic Control XT extender identity: faders worked, but MCU Bank
Left/Right did nothing.

The bridge now announces and answers **only `0x10` (base Logic Control)**.
Delete and re-add the Mackie Control surface once after this change. A healthy
launch log says:

```
CONNECTED as 0x10
```

MCU Bank Left/Right are ch1 Note On/Off notes 46/47. `bank home` sends Bank
Left 16 times, saturating Logic at its first eight-strip bank. Logic's own
Mackie Control documentation confirms that Bank Left/Right move the active
channel strips by the size of the control-surface group.

### 2.2 Master needs its own virtual port

Logic ignored the dedicated MCU master-fader lane (Pitch Bend on channel 9) in
this configuration. Mirroring physical MASTER to MCU strip 8 temporarily moved
Stereo Out, but would have broken as soon as the eight-strip bank moved.

The durable solution is a second virtual **source-only** port:

| Virtual port | Message | Purpose |
|---|---|---|
| `MIDI Mix MCU` | MCU protocol | banked faders 1–8, later buttons/knobs |
| `MIDI Mix Fixed` | ch16 CC119, absolute 0–127 | physical MASTER → Logic Master volume |

`MIDI Mix Fixed` is a stable virtual port name, so it avoids the real-device
port-slot reassignment failure documented in `HANDOFF.md`.

---

## 3. Final Logic setup (important)

### Control Surface Setup

There must be exactly one relevant surface:

1. Start `mixer-mode.command` first.
2. Logic Pro → Control Surfaces → Setup → Install → Mackie Designs →
   **Mackie Control**.
3. Set **Input** and **Output** to `MIDI Mix MCU`.
4. Delete any surface that names the real `MIDI Mix` port.

If the bridge was upgraded from the pre-`0x10` version, delete the old virtual
surface and add it again once. The bridge must report `CONNECTED as 0x10`.

### Disable the raw hardware input in Logic

Logic Pro → Settings → MIDI → Inputs:

- turn **off** `MIDI Mix` (the physical AKAI port);
- leave `MIDI Mix MCU` and `MIDI Mix Fixed` enabled.

This does **not** prevent the Python bridge from hearing the hardware. It only
stops raw CCs such as physical MASTER's CC69 from reaching Logic in parallel
with translated messages.

### One-time fixed Master assignment

This assignment is global and should survive project changes:

1. In the bridge terminal, type `master fixed` (the code now defaults to this;
   use it only if changing a live older process).
2. Click the purple **Master** channel's volume fader in Logic's mixer.
3. Choose Logic Pro → Control Surfaces → **Learn Assignment for Volume**.
4. Move the physical MASTER fader.
5. End Learn. The assignment must show **`MIDI Mix Fixed`**, channel 16,
   CC119 — not raw MIDI Mix CC69.

Do not use the general Controller Assignments Expert window for this. Its Zones
and Modes are irrelevant to this single fixed assignment.

After Logic quits, back up the current `com.apple.logic.pro.cs` as instructed
in `HANDOFF.md`; it now contains this important assignment.

---

## 4. Running and banking

Double-click `mixer-mode.command` and keep its Terminal window open while
mixing. Closing it tears down both virtual ports and stops the surface.

Useful terminal commands:

```text
status
bank home
bank left [count]
bank right [count]
master fixed
master mirror       # diagnostic fallback only; do not use in normal mixing
```

Run `bank home` after launch whenever you want faders 1–8 to begin at the
first eight-track bank. It is intentionally manual at this point; do not make
it automatic without deciding whether startup should preserve the previous
bank in larger projects.

### Current physical mapping (mGB preset; no flash)

| Physical control | Hardware input | Logic destination |
|---|---|---|
| Faders 1–8 | ch1 CC61–68 | MCU faders 1–8, current eight-strip bank |
| MASTER | ch1 CC69 | `MIDI Mix Fixed` ch16 CC119 → fixed Logic Master |

Physical faders are currently **direct absolute** controls: the first movement
can jump to the fader's physical position. Soft takeover is the next planned
improvement.

---

## 5. Verification completed

- Phase 1 virtual MCU handshake and synthetic volume move: passed.
- Real MIDI Mix faders 1–8 arrive as ch1 CC61–68: passed.
- Real physical MASTER arrives as ch1 CC69: passed.
- Raw hardware data disabled in Logic; translated virtual data remains live:
  passed.
- `MIDI Mix Fixed` learned as the actual Logic Master assignment: passed.
- Base Logic Control `0x10` connection and `bank home` first-bank routing:
  **user-confirmed passed**.
- Physical MASTER remains independent of the bank: user-confirmed passed.

Automated checks: `python3 tools/selftest.py` passes. `mcu_surface.py
selfcheck` passes all pure protocol/routing checks; its virtual-port creation
subtest only requires the macOS CoreMIDI server to be active (it returns
`-10833` in an inactive non-GUI session).

---

## 6. Next work

**Soft takeover for faders.** Track Logic's incoming fader feedback,
then suppress each physical fader until it crosses Logic's last-known value.
This eliminates jumps after project changes or banking.

After that: map mute / solo / record-arm buttons, panel LED feedback, and
relative pan/send knobs. Physical BANK buttons were verified and implemented
in Phase 3; see `phase3handoff.md`.
