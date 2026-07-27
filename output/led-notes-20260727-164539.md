# MIDI Mix LED — per-note map (ch1 notes 0–23)

- captured: 2026-07-27 16:49:10
- preset: `mgb-mode.midimix`
- device: `MIDI Mix`
- steps completed: **24** / 24

Per-note map (ch1). Batch scan (2026-07-27) suggested roughly:
  notes 0–7  → MUTE 1–3, REC 1–2
  notes 8–15 → MUTE 4–5, REC 3–5
  notes 16–23→ MUTE 6–8, REC 6–7
Confirm or correct with the per-note observations below.

| Note | MCU hint | Your observation |
|---|---|---|
| 0 | MCU REC strip 1 | (nothing / empty) |
| 1 | MCU REC strip 2 | (nothing / empty) |
| 2 | MCU REC strip 3 | m1 |
| 3 | MCU REC strip 4 | ra1 |
| 4 | MCU REC strip 5 | (nothing / empty) |
| 5 | MCU REC strip 6 | m2 |
| 6 | MCU REC strip 7 | ra2 |
| 7 | MCU REC strip 8 | ok so as i suspected, this is glowing m3 when solo is held, and while it is depressed, it is turned off |
| 8 | MCU SOLO strip 1 | and the same goes for this in reverse, while solo is not pressed, m3 is off. when i press solo, it lights up m3, and turns off when released |
| 9 | MCU SOLO strip 2 | REC ARM is not affected by solo button press or release either way, this is still lighting up RA3 |
| 10 | MCU SOLO strip 3 | (nothing / empty) |
| 11 | MCU SOLO strip 4 | M4 |
| 12 | MCU SOLO strip 5 | RA4 |
| 13 | MCU SOLO strip 6 | (nothing / empty) |
| 14 | MCU SOLO strip 7 | M5 |
| 15 | MCU SOLO strip 8 | RA5 |
| 16 | MCU MUTE strip 1 | (nothing / empty) |
| 17 | MCU MUTE strip 2 | M6 |
| 18 | MCU MUTE strip 3 | RA6 |
| 19 | MCU MUTE strip 4 | (JUST to be clear, all the nothing/empty replies are lighting the mute buttons up--just not when solo is depressed) |
| 20 | MCU MUTE strip 5 | m7 |
| 21 | MCU MUTE strip 6 | ra7 |
| 22 | MCU MUTE strip 7 | (nothing / empty) |
| 23 | MCU MUTE strip 8 | m8 |


Observations are **verbatim** user input.

| ID | What we sent | Detail | Your observation |
|---|---|---|---|
| N00 | Note On ch1 note 0 | `NoteOn ch1 note0 vel127  (MCU REC strip 1)` | (nothing / empty) |
| N01 | Note On ch1 note 1 | `NoteOn ch1 note1 vel127  (MCU REC strip 2)` | (nothing / empty) |
| N02 | Note On ch1 note 2 | `NoteOn ch1 note2 vel127  (MCU REC strip 3)` | m1 |
| N03 | Note On ch1 note 3 | `NoteOn ch1 note3 vel127  (MCU REC strip 4)` | ra1 |
| N04 | Note On ch1 note 4 | `NoteOn ch1 note4 vel127  (MCU REC strip 5)` | (nothing / empty) |
| N05 | Note On ch1 note 5 | `NoteOn ch1 note5 vel127  (MCU REC strip 6)` | m2 |
| N06 | Note On ch1 note 6 | `NoteOn ch1 note6 vel127  (MCU REC strip 7)` | ra2 |
| N07 | Note On ch1 note 7 | `NoteOn ch1 note7 vel127  (MCU REC strip 8)` | ok so as i suspected, this is glowing m3 when solo is held, and while it is depressed, it is turned off |
| N08 | Note On ch1 note 8 | `NoteOn ch1 note8 vel127  (MCU SOLO strip 1)` | and the same goes for this in reverse, while solo is not pressed, m3 is off. when i press solo, it lights up m3, and turns off when released |
| N09 | Note On ch1 note 9 | `NoteOn ch1 note9 vel127  (MCU SOLO strip 2)` | REC ARM is not affected by solo button press or release either way, this is still lighting up RA3 |
| N10 | Note On ch1 note 10 | `NoteOn ch1 note10 vel127  (MCU SOLO strip 3)` | (nothing / empty) |
| N11 | Note On ch1 note 11 | `NoteOn ch1 note11 vel127  (MCU SOLO strip 4)` | M4 |
| N12 | Note On ch1 note 12 | `NoteOn ch1 note12 vel127  (MCU SOLO strip 5)` | RA4 |
| N13 | Note On ch1 note 13 | `NoteOn ch1 note13 vel127  (MCU SOLO strip 6)` | (nothing / empty) |
| N14 | Note On ch1 note 14 | `NoteOn ch1 note14 vel127  (MCU SOLO strip 7)` | M5 |
| N15 | Note On ch1 note 15 | `NoteOn ch1 note15 vel127  (MCU SOLO strip 8)` | RA5 |
| N16 | Note On ch1 note 16 | `NoteOn ch1 note16 vel127  (MCU MUTE strip 1)` | (nothing / empty) |
| N17 | Note On ch1 note 17 | `NoteOn ch1 note17 vel127  (MCU MUTE strip 2)` | M6 |
| N18 | Note On ch1 note 18 | `NoteOn ch1 note18 vel127  (MCU MUTE strip 3)` | RA6 |
| N19 | Note On ch1 note 19 | `NoteOn ch1 note19 vel127  (MCU MUTE strip 4)` | (JUST to be clear, all the nothing/empty replies are lighting the mute buttons up--just not when solo is depressed) |
| N20 | Note On ch1 note 20 | `NoteOn ch1 note20 vel127  (MCU MUTE strip 5)` | m7 |
| N21 | Note On ch1 note 21 | `NoteOn ch1 note21 vel127  (MCU MUTE strip 6)` | ra7 |
| N22 | Note On ch1 note 22 | `NoteOn ch1 note22 vel127  (MCU MUTE strip 7)` | (nothing / empty) |
| N23 | Note On ch1 note 23 | `NoteOn ch1 note23 vel127  (MCU MUTE strip 8)` | m8 |

## Raw notes (verbatim)

### N00 — Note On ch1 note 0

- sent: `NoteOn ch1 note0 vel127  (MCU REC strip 1)`
- observation:

```
(nothing / empty)
```

### N01 — Note On ch1 note 1

- sent: `NoteOn ch1 note1 vel127  (MCU REC strip 2)`
- observation:

```
(nothing / empty)
```

### N02 — Note On ch1 note 2

- sent: `NoteOn ch1 note2 vel127  (MCU REC strip 3)`
- observation:

```
m1
```

### N03 — Note On ch1 note 3

- sent: `NoteOn ch1 note3 vel127  (MCU REC strip 4)`
- observation:

```
ra1
```

### N04 — Note On ch1 note 4

- sent: `NoteOn ch1 note4 vel127  (MCU REC strip 5)`
- observation:

```
(nothing / empty)
```

### N05 — Note On ch1 note 5

- sent: `NoteOn ch1 note5 vel127  (MCU REC strip 6)`
- observation:

```
m2
```

### N06 — Note On ch1 note 6

- sent: `NoteOn ch1 note6 vel127  (MCU REC strip 7)`
- observation:

```
ra2
```

### N07 — Note On ch1 note 7

- sent: `NoteOn ch1 note7 vel127  (MCU REC strip 8)`
- observation:

```
ok so as i suspected, this is glowing m3 when solo is held, and while it is depressed, it is turned off
```

### N08 — Note On ch1 note 8

- sent: `NoteOn ch1 note8 vel127  (MCU SOLO strip 1)`
- observation:

```
and the same goes for this in reverse, while solo is not pressed, m3 is off. when i press solo, it lights up m3, and turns off when released
```

### N09 — Note On ch1 note 9

- sent: `NoteOn ch1 note9 vel127  (MCU SOLO strip 2)`
- observation:

```
REC ARM is not affected by solo button press or release either way, this is still lighting up RA3
```

### N10 — Note On ch1 note 10

- sent: `NoteOn ch1 note10 vel127  (MCU SOLO strip 3)`
- observation:

```
(nothing / empty)
```

### N11 — Note On ch1 note 11

- sent: `NoteOn ch1 note11 vel127  (MCU SOLO strip 4)`
- observation:

```
M4
```

### N12 — Note On ch1 note 12

- sent: `NoteOn ch1 note12 vel127  (MCU SOLO strip 5)`
- observation:

```
RA4
```

### N13 — Note On ch1 note 13

- sent: `NoteOn ch1 note13 vel127  (MCU SOLO strip 6)`
- observation:

```
(nothing / empty)
```

### N14 — Note On ch1 note 14

- sent: `NoteOn ch1 note14 vel127  (MCU SOLO strip 7)`
- observation:

```
M5
```

### N15 — Note On ch1 note 15

- sent: `NoteOn ch1 note15 vel127  (MCU SOLO strip 8)`
- observation:

```
RA5
```

### N16 — Note On ch1 note 16

- sent: `NoteOn ch1 note16 vel127  (MCU MUTE strip 1)`
- observation:

```
(nothing / empty)
```

### N17 — Note On ch1 note 17

- sent: `NoteOn ch1 note17 vel127  (MCU MUTE strip 2)`
- observation:

```
M6
```

### N18 — Note On ch1 note 18

- sent: `NoteOn ch1 note18 vel127  (MCU MUTE strip 3)`
- observation:

```
RA6
```

### N19 — Note On ch1 note 19

- sent: `NoteOn ch1 note19 vel127  (MCU MUTE strip 4)`
- observation:

```
(JUST to be clear, all the nothing/empty replies are lighting the mute buttons up--just not when solo is depressed)
```

### N20 — Note On ch1 note 20

- sent: `NoteOn ch1 note20 vel127  (MCU MUTE strip 5)`
- observation:

```
m7
```

### N21 — Note On ch1 note 21

- sent: `NoteOn ch1 note21 vel127  (MCU MUTE strip 6)`
- observation:

```
ra7
```

### N22 — Note On ch1 note 22

- sent: `NoteOn ch1 note22 vel127  (MCU MUTE strip 7)`
- observation:

```
(nothing / empty)
```

### N23 — Note On ch1 note 23

- sent: `NoteOn ch1 note23 vel127  (MCU MUTE strip 8)`
- observation:

```
m8
```

## Steps with a non-empty observation

- **N02** `NoteOn ch1 note2 vel127  (MCU REC strip 3)` → m1
- **N03** `NoteOn ch1 note3 vel127  (MCU REC strip 4)` → ra1
- **N05** `NoteOn ch1 note5 vel127  (MCU REC strip 6)` → m2
- **N06** `NoteOn ch1 note6 vel127  (MCU REC strip 7)` → ra2
- **N07** `NoteOn ch1 note7 vel127  (MCU REC strip 8)` → ok so as i suspected, this is glowing m3 when solo is held, and while it is depressed, it is turned off
- **N08** `NoteOn ch1 note8 vel127  (MCU SOLO strip 1)` → and the same goes for this in reverse, while solo is not pressed, m3 is off. when i press solo, it lights up m3, and turns off when released
- **N09** `NoteOn ch1 note9 vel127  (MCU SOLO strip 2)` → REC ARM is not affected by solo button press or release either way, this is still lighting up RA3
- **N11** `NoteOn ch1 note11 vel127  (MCU SOLO strip 4)` → M4
- **N12** `NoteOn ch1 note12 vel127  (MCU SOLO strip 5)` → RA4
- **N14** `NoteOn ch1 note14 vel127  (MCU SOLO strip 7)` → M5
- **N15** `NoteOn ch1 note15 vel127  (MCU SOLO strip 8)` → RA5
- **N17** `NoteOn ch1 note17 vel127  (MCU MUTE strip 2)` → M6
- **N18** `NoteOn ch1 note18 vel127  (MCU MUTE strip 3)` → RA6
- **N19** `NoteOn ch1 note19 vel127  (MCU MUTE strip 4)` → (JUST to be clear, all the nothing/empty replies are lighting the mute buttons up--just not when solo is depressed)
- **N20** `NoteOn ch1 note20 vel127  (MCU MUTE strip 5)` → m7
- **N21** `NoteOn ch1 note21 vel127  (MCU MUTE strip 6)` → ra7
- **N23** `NoteOn ch1 note23 vel127  (MCU MUTE strip 8)` → m8

