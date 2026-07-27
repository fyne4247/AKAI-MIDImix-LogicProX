# Phase 1 handoff — virtual Mackie Control surface

**Date:** 2026-07-27  
**Result:** **PASSED**  
**Repo path:** project root on `master` (not a worktree)  
**Primary code:** `tools/mcu_surface.py`, wrapper `./mixer-probe`

A fresh session should be able to continue Phase 2+ from this document plus
`HANDOFF.md` without re-deriving the handshake.

---

## 1. Goal of Phase 1

Prove that Logic Pro will accept a **software-emulated Mackie Control** on a
virtual CoreMIDI port pair, and that an outbound **volume** fader move
(MCU pitch-bend) actually moves a mixer fader in Logic.

This is the make-or-break step for the whole translator plan. If it failed, the
fallback was Controller Assignments (`HANDOFF.md` §8).

---

## 2. What changed from the original plan

The original plan (in `HANDOFF.md` §6 Phase 1) was correct in spirit. Details
that only became clear while implementing:

| Topic | Original plan | What we actually needed / found |
|---|---|---|
| Port name | “something Logic-friendly” | Fixed name **`MIDI Mix MCU`** (source + dest) |
| Device ID | Mackie Control `0x14` | Logic scans **many** IDs (`0x10/11/14/15/17`). Handshake completed on **`0x10` (Logic Control)** even when the installed *model* was “Mackie Control”. We announce/reply on whatever ID Logic queries. |
| Handshake risk | “exact bytes unknown; may kill the project” | **Solved.** TouchMCU algorithm matches Logic exactly (`c2 >> 4` for r1). Ardour’s host code uses `c2 >> c3` — wrong for Logic. |
| Fader test | “send a single fader move” | Logic defaults to **touch-sensitive** faders (`cmd 0x0C` payload `00`). Must send **touch notes 104–112** around pitch bend. |
| Auto-install trap | not emphasized | Logic can auto-bind the **real** `MIDI Mix` as Logic Control. That only sees raw CCs and must be **deleted**. Only `MIDI Mix MCU` is valid. |
| Virtual MIDI delivery | earlier note said cross-process virtual endpoints failed | That was about midimix loopback experiments. **`MIDIReceived` source + `MIDIDestinationCreate` dest work across processes** (Logic ↔ probe). |
| Status / online | formal handshake only | Logic often streams **LCD + meters + fader feedback** before (or without) a clean Host Connection Reply this boot. Treat LCD / host traffic as online. |
| Ops hazards | not listed | **One probe instance only** (duplicate same-name ports break Logic). Background probe has no stdin — use `.mcu_cmd` or `test`. |

Nothing in the high-level plan was abandoned. Soft-takeover, buttons, banking,
and knobs remain later phases.

---

## 3. What was implemented

### 3.1 Files

| Path | Role |
|---|---|
| `tools/mcu_surface.py` | Virtual MCU: CoreMIDI ports, handshake, fader emit, CLI, selfcheck |
| `./mixer-probe` | `python3 tools/mcu_surface.py run` |
| `.mcu_surface.pid` | Single-instance lock (runtime) |
| `.mcu_cmd` | Optional command inject from a second terminal |

### 3.2 Virtual ports

- **Source** (Logic **Input**): surface → host. Uses `MIDISourceCreate` + `MIDIReceived`.
- **Destination** (Logic **Output**): host → surface. Uses `MIDIDestinationCreate` + read callback.
- Name for both: **`MIDI Mix MCU`**.
- CoreMIDI plumbing reuses `tools/midimix.py` (`_packet_list`, `_iter_packets`, ctypes traps).

### 3.3 Handshake (device side)

```
host  →  F0 00 00 66 dd 00 F7                             Device Query
device→  F0 00 00 66 dd 01 <7 serial> <4 challenge> F7    Host Connection Query
host  →  F0 00 00 66 dd 02 <7 serial> <4 response>  F7    Host Connection Reply
device→  F0 00 00 66 dd 03 <7 serial> F7                  Host Connection Confirmation
host  →  F0 00 00 66 dd 13 00 F7                          Version Request
device→  F0 00 00 66 dd 14 <5 version> F7                 Version Reply
```

- Serial: `MIDIMix` (7 ASCII bytes)
- Version: `V1.00` (5 ASCII bytes)
- Challenge response (verified against Logic):

```
r0 = 0x7F & ( c0 + (c1 ^ 0x0A) - c3 )
r1 = 0x7F & ( (c2 >> 4) ^ (c0 + c3) )
r2 = 0x7F & ( (c3 - (c2 << 2)) ^ (c0 | c1) )
r3 = 0x7F & ( c1 - c2 + (0xF0 ^ (c3 << 4)) )
```

### 3.4 Faders (MCU wire format)

| Meaning in Logic | Wire |
|---|---|
| Strip 1–8 volume | Pitch Bend, MIDI channel 1–8 |
| Master volume | Pitch Bend, MIDI channel 9 |
| “Finger on fader” | Note On/Off ch1, notes **104–112** |

**Important for the user:** MCU pitch bend is **only** the mixer wire format on
the `MIDI Mix MCU` port. It does **not** overwrite performance pitch bend / CC2 /
CC11 / CC64 on other ports (EWI, MPK, etc.).

### 3.5 CLI (while `run` is up)

```
f <1-9> <0-127>   move one strip volume
test [strip]      0 → 127 → 64 for visibility
sweep             all 9 faders
ping              re-announce
status            connection / host msg counts
quiet / verbose   log noise
q                 quit
```

Second terminal: `echo 'test' > .mcu_cmd`

Selfcheck (no Logic required for unit bits):  
`python3 tools/mcu_surface.py selfcheck`

---

## 4. How it was verified

### Automated / probe-side

- Virtual ports visible in CoreMIDI
- Cross-process source and dest delivery
- Handshake `algo_match=True` against live Logic replies
- Logic → surface: fader feedback, LCD track names, LEDs, meters

### User-confirmed

- Outbound fader move **moves the volume fader** in Logic’s mixer (2026-07-27)

### Logic setup that works

1. Start `./mixer-probe` first  
2. Delete any Control Surface still on real **`MIDI Mix`**  
3. Install → Mackie Designs → **Mackie Control**  
4. Input **and** Output = **`MIDI Mix MCU`**  
5. Close Setup; open a project with tracks  
6. `test` in the probe (or wait for auto-test after live/LCD)

---

## 5. Button LEDs — host feedback **works** (retraction + new work)

### 5.1 Retraction

Earlier project conclusion (“LEDs are firmware-internal only; host MIDI cannot
light them”) is **wrong / incomplete**. It came from:

1. First `led` runs while **outgoing packets were zero-length** (`pack(4)` bug).
2. Later tests that only **echoed each button’s own CC** as CC + Note with
   `note number = CC` (31–58 etc.) — outside the range the device actually uses.

Akai’s public docs still say little/nothing about LED feedback. Empirically the
panel **does** respond to a narrow Note-On pattern.

### 5.2 Coarse scan result (user-verified 2026-07-27)

Command: `python3 tools/midimix.py led --scan`  
Report: `output/led-scan-latest.md`

| ID | What we sent | Lamps that lit (user) |
|---|---|---|
| A | all preset buttons CC+Note (note#=CC) | **nothing** |
| B | Note On ch1 notes **16–23** | **MUTE 6,7,8 + REC ARM 6,7** |
| C | Note On ch1 notes **8–15** | **MUTE 4,5 + REC ARM 3,4,5** |
| D | Note On ch1 notes **0–7** | **MUTE 1,2,3 + REC ARM 1,2** |
| E | notes 16–23 with Note Off bangs | same as B |
| F | note 23 alone on all channels | nothing |
| G | CC38 on all channels | nothing |

**Protocol so far:**

- **Works:** `Note On`, **channel 1**, note numbers roughly **0–23**, velocity 127.
- **Does not work (for LEDs):** CC; Note with note# = button CC; single note 23 alone
  (batch 16–23 does light high mutes/recs — per-note map still incomplete).
- Mapping is **not** clean MCU strip order: MCU “mute notes” light a **mix of
  MUTE and REC ARM** lamps on the AKAI panel.

**Rough batch banks (not yet 1:1):**

```
notes  0–7   →  MUTE 1–3,  REC 1–2
notes  8–15  →  MUTE 4–5,  REC 3–5
notes 16–23  →  MUTE 6–8,  REC 6–7
```

(REC 8 never reported in the coarse scan.)

### 5.3 Per-note map — **DONE** (solo off + solo on)

```sh
python3 tools/midimix.py led --notes   # → output/led-notes-latest.md
```

Runs completed 2026-07-27:

| Run | Backup file |
|---|---|
| SOLO released | `output/led-notes-solo-off-backup.md` |
| SOLO held | `output/led-notes-solo-on-backup.md` |
| Merged map | **`output/led-note-map.md`** |

**Definitive rule (ch1 Note On, vel 127):** base-3 on note `n`:

| `n % 3` | Lamp | Formula |
|---|---|---|
| 1 | MUTE `s` when SOLO **released** | `n = 3*(s-1)+1`, s=1..8 |
| 2 | MUTE `s` when SOLO **held** (solo layer) | `n = 3*(s-1)+2`, s=1..8 |
| 0 (`n≥3`) | REC ARM `s` (solo-independent) | `n = 3*s`, s=1..7 |
| 0 | nothing | — |

- **REC ARM 8:** no note found in 0–23.  
- SOLO is a **hardware layer** on the mute lamps, not a separate LED row.  
- Translator can drive mute/solo/rec lamps once Logic state is known; user still
  needs SOLO released/held on the panel to *see* mute vs solo layer.

### 5.4 Why fine one-CC-at-a-time tests went dark

An intermediate interactive map split preset path into CC-only then Note-only and
pre-cleared aggressively. Coarse A always sent **CC+Note together in a multi-button
blast**. That experiment was a test-design dead end; use `--scan` / `--notes` above.

### 5.5 Impact on the plan

- LED feedback is back as an **argument for the translator** (Controller Assignments
  will not light these; the daemon can).
- Phase 2 (faders → volume) does **not** depend on finishing the note map.
- Do not reinstall Mackie Control just for LED testing.

---

## 6. Known quirks (carry into Phase 2+)

1. **Meter spam** — Logic sends continuous channel-pressure meters; probe quiets them by default.  
2. **Multiple Device Queries** — Logic scans several Mackie device IDs; reply on the queried ID.  
3. **Touchless = false** — host sets `0x0C 00`; hold touch across live fader moves.  
4. **Channel Strip Track `262150`** — means offline / wrong ports; not a real track index.  
5. **Performance MIDI safety** — never put instrument tracks on `MIDI Mix MCU`; never put the Mackie surface on the real `MIDI Mix` port.  
6. **LED map complete** — see `output/led-note-map.md` (base-3 ch1 notes). REC8 unknown.  
7. **One probe instance only** — duplicate `MIDI Mix MCU` ports break Logic binding.

---

## 7. Phase 1 → Phase 2 boundary

Phase 1 proved: *virtual MCU ↔ Logic, synthetic fader → volume, and (bonus) host
can light MUTE/REC LEDs via ch1 notes 0–23.*

Phase 2: listen to the **real AKAI MIDI Mix** fader CCs and translate them into
the same MCU pitch-bend path. Buttons/knobs/banking/soft-takeover/LED echo stay later.

Device was never required for Phase 1 MCU ports and should still be on **mgb-mode**
(nothing was flashed in Phase 1). Fader addresses under that preset:

| Strip | Wire (0-based ch) | Display |
|---|---|---|
| 1–8 | ch0 CC61–68 | ch1 CC61–68 |
| Master | ch0 CC69 | ch1 CC69 |

(`logic-mode` uses ch7 CC22–30 if that preset is ever flashed.)

---

## 8. Commands cheat sheet

```sh
cd "/Users/fish4247/Claude Code Projects/MIDIMix_LogicProX"

# Phase 1 MCU probe (Logic open; surface on MIDI Mix MCU)
./mixer-probe
# in probe:  test

python3 tools/mcu_surface.py selfcheck
python3 tools/midimix.py ports

# LED — prefer Logic quit
python3 tools/midimix.py led --scan    # coarse A–G → output/led-scan-latest.md
python3 tools/midimix.py led --notes   # notes 0–23  → output/led-notes-latest.md
```

Agent: when user says LED notes are done, read **`output/led-notes-latest.md`**.
