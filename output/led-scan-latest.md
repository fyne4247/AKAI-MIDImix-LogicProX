# MIDI Mix LED coarse scan (A–G)

- captured: 2026-07-27 16:40:27
- preset: `mgb-mode.midimix`
- device: `MIDI Mix`
- steps completed: **7** / 7

This is the same multi-message blast sequence as the timed
`led --scan` that the user reported lit the panel. After each ON,
observation is freeform user text (verbatim).

| ID | Blast | Detail | Your observation |
|---|---|---|---|
| A | preset button CCs as CC + Note (original test) | `all 24 buttons: CC=127 + NoteOn(note=CC) vel127` | (nothing / empty) |
| B | MCU MUTE notes 16-23 on ch1 (Note On 127 / 0) | `NoteOn ch1 notes 16..23 vel127` | mute 6, 7 & 8. REC ARM 6 & 7 |
| C | MCU SOLO notes 8-15 on ch1 | `NoteOn ch1 notes 8..15 vel127` | mute 4 & 5, REC ARM 3, 4, & 5 |
| D | MCU REC notes 0-7 on ch1 | `NoteOn ch1 notes 0..7 vel127` | mute 1, 2 & 3, REC ARM 1 & 2 |
| E | MCU MUTE 16-23 as Note On + Note Off bangs | `NoteOn/Off bangs notes 16..23` | MUTE 6, 7 & 8, REC ARM 6 & 7 |
| F | Note 23 (MCU mute strip 8) on ALL channels 1-16 | `NoteOn note23 vel127 on ch1..16` | (nothing / empty) |
| G | preset MUTE8 CC38 on ALL channels | `CC38=127 on ch1..16` | (nothing / empty) |

## Raw notes (verbatim)

### [A] preset button CCs as CC + Note (original test)

- sent: `all 24 buttons: CC=127 + NoteOn(note=CC) vel127`
- observation:

```
(nothing / empty)
```

### [B] MCU MUTE notes 16-23 on ch1 (Note On 127 / 0)

- sent: `NoteOn ch1 notes 16..23 vel127`
- observation:

```
mute 6, 7 & 8. REC ARM 6 & 7
```

### [C] MCU SOLO notes 8-15 on ch1

- sent: `NoteOn ch1 notes 8..15 vel127`
- observation:

```
mute 4 & 5, REC ARM 3, 4, & 5
```

### [D] MCU REC notes 0-7 on ch1

- sent: `NoteOn ch1 notes 0..7 vel127`
- observation:

```
mute 1, 2 & 3, REC ARM 1 & 2
```

### [E] MCU MUTE 16-23 as Note On + Note Off bangs

- sent: `NoteOn/Off bangs notes 16..23`
- observation:

```
MUTE 6, 7 & 8, REC ARM 6 & 7
```

### [F] Note 23 (MCU mute strip 8) on ALL channels 1-16

- sent: `NoteOn note23 vel127 on ch1..16`
- observation:

```
(nothing / empty)
```

### [G] preset MUTE8 CC38 on ALL channels

- sent: `CC38=127 on ch1..16`
- observation:

```
(nothing / empty)
```

