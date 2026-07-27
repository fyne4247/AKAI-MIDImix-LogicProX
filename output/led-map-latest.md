# MIDI Mix LED map

- captured: 2026-07-27 16:38:59
- preset: `mgb-mode.midimix`
- device: `MIDI Mix`
- steps completed: **2** / 52 (aborted early)

Differences vs the one-at-a-time pass that saw nothing:
- smoke steps recreate the original coarse multi-message blasts
- preset steps send **CC + Note together** (not CC-only or Note-only)
- MCU singles re-send the note several times
- CoreMIDI runloop is pumped after each send

Observations are **verbatim** user input.

| ID | What we sent | Detail | Your observation |
|---|---|---|---|
| S0 | SMOKE: all preset buttons CC+Note at once (coarse A) | `all 24 buttons: CC127 + NoteOn127 each` | (nothing / empty) |
| S1 | SMOKE: MCU MUTE notes 16-23 all at once (coarse B) | `NoteOn ch1 notes 16..23 vel127` | (aborted) |

## Raw notes (verbatim)

### S0 — SMOKE: all preset buttons CC+Note at once (coarse A)

- sent: `all 24 buttons: CC127 + NoteOn127 each`
- resend count: 2
- observation:

```
(nothing / empty)
```

### S1 — SMOKE: MCU MUTE notes 16-23 all at once (coarse B)

- sent: `NoteOn ch1 notes 16..23 vel127`
- resend count: 2
- observation:

```
(aborted)
```

## Steps with a non-empty observation

(none)

