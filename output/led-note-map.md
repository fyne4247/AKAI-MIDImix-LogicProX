# MIDI Mix LED note map (definitive from user measurements)

**Date:** 2026-07-27  
**Wire:** Note On, **channel 1**, velocity 127 = lamp on; 0 / Note Off = off.  
**Sources:**  
- Solo **released:** `output/led-notes-solo-off-backup.md`  
- Solo **held:** `output/led-notes-solo-on-backup.md`  

CC does **not** drive LEDs. Preset “echo button CC as note” does **not** (wrong note numbers).

---

## Physical lamps that exist

- **MUTE 1–8** (yellow) — shared with SOLO layer (hardware SOLO button selects which feedback layer you *see* / which notes address mute lamps)
- **REC ARM 1–7** confirmed; **REC ARM 8** never lit in either run
- No separate SOLO-only lamps observed (SOLO is a hold/layer on the mute row)

---

## Pattern (base-3)

For note number `n` on channel 1:

| `n % 3` | Role |
|---|---|
| **1** | **MUTE** lamp, solo **released** layer |
| **2** | **MUTE** lamp, solo **held** layer |
| **0** (and `n > 0`) | **REC ARM** lamp (solo-independent) |
| `n == 0` | nothing |

### MUTE (solo released) — notes `1,4,7,10,13,16,19,22`

| Note | Lamp |
|---|---|
| 1 | MUTE 1 |
| 4 | MUTE 2 |
| 7 | MUTE 3 |
| 10 | MUTE 4 |
| 13 | MUTE 5 |
| 16 | MUTE 6 |
| 19 | MUTE 7 |
| 22 | MUTE 8 |

Strip index: `mute = (n + 2) // 3` for `n % 3 == 1`.

### MUTE (solo held) — notes `2,5,8,11,14,17,20,23`

| Note | Lamp |
|---|---|
| 2 | MUTE 1 |
| 5 | MUTE 2 |
| 8 | MUTE 3 |
| 11 | MUTE 4 |
| 14 | MUTE 5 |
| 17 | MUTE 6 |
| 20 | MUTE 7 |
| 23 | MUTE 8 |

Strip index: `mute = (n + 1) // 3` for `n % 3 == 2`.

User note: empties on the solo-held run for the “solo-released” note series still *would* light mutes if SOLO were released — SOLO gates which mute-note series is visible.

### REC ARM (either solo state) — notes `3,6,9,12,15,18,21`

| Note | Lamp |
|---|---|
| 3 | REC ARM 1 |
| 6 | REC ARM 2 |
| 9 | REC ARM 3 |
| 12 | REC ARM 4 |
| 15 | REC ARM 5 |
| 18 | REC ARM 6 |
| 21 | REC ARM 7 |
| (24 would be RA8 — out of 0–23 range; **RA8 not found**) |

Strip index: `rec = n // 3` for `n % 3 == 0` and `n >= 3`.

---

## Translator recipe (Logic → panel)

When Logic (MCU) wants:

| Logic state | Send to MIDI Mix |
|---|---|
| Mute strip `s` (1–8) on | Note On ch1, note `3*(s-1)+1`, vel 127 |
| Mute strip `s` off | same note, vel 0 |
| Solo strip `s` on | Note On ch1, note `3*(s-1)+2`, vel 127 |
| Solo strip `s` off | same note, vel 0 |
| Rec strip `s` (1–7) on | Note On ch1, note `3*s`, vel 127 |
| Rec strip `s` off | same note, vel 0 |
| Rec strip 8 | **unknown / no LED** |

User must have SOLO **released** on the hardware to *see* mute LEDs, and SOLO **held** to *see* solo-layer mute LEDs (same physical lamps). REC ARM always visible.

---

## Dead notes

- **0** — no lamp in either run  
- Odd/even “gaps” are the other layer’s mute series when SOLO state hides them, not dead firmware slots  

---

## Files

| File | Content |
|---|---|
| `led-notes-solo-off-backup.md` | solo released, 24 notes |
| `led-notes-solo-on-backup.md` | solo held, 24 notes |
| `led-scan-latest.md` | coarse A–G (first proof) |
| `led-note-map.md` | this summary |
