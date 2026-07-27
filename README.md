# AKAI MIDI Mix ↔ Logic Pro, without breaking the mGB / Arduinoboy rig

## The thing to know first

**The MIDI Mix will never appear under Logic's Setup → Control Surfaces → Install.**
That is not a fault and cannot be fixed. Logic only auto-detects devices it has a
driver module for; the modules compiled into Logic are Axiom, Axiom Pro, AxiomAIR,
CS-32, FaderMaster, GiO, HUI, iControl, Logic Control, Logic Remote, MCS3,
microKONTROL, Motormix, Oxygen, Recording Light, SAC-2K and SI-24. The MIDI Mix is
not among them and has no Mackie/HUI emulation mode in its firmware.

The supported route is **Controller Assignments** (`Cmd+K`) — a completely separate
subsystem from Control Surfaces.

## Preset format

Reverse-engineered here and verified against two independent presets. 146 bytes:

```
F0 47 00 31 67 01 0A   <138 payload bytes>   F7
|  |  |  |  |  |  |
|  |  |  |  |  `--`--- 7-bit length pair: (0x01 << 7) | 0x0A = 138
|  |  |  |  `--------- opcode 0x67 = write config
|  `--`--`------------ Akai / MIDI Mix device id
`--------------------- SysEx start

payload = 24 knobs  × 2 bytes (channel, cc)    strip order, 3 per strip
        +  9 faders × 2 bytes (channel, cc)    1–8 then MASTER
        + 24 buttons × 3 bytes (channel, type, cc)
```

Channel bytes are 0-based on the wire.

### The 24-vs-20 button puzzle

The panel has **20 physical buttons** — 8 MUTE, 8 REC ARM, plus SEND ALL, BANK LEFT,
BANK RIGHT and SOLO — but the preset stores **24 button records**. The extra row of 8
is the SOLO-shifted MUTE layer. Per the manual: *"Press and hold this button to
activate the solo feature for the Mute buttons."* That is why no button on the panel
carries those CCs' label.

## Button records are (channel, type, cc)

Not `(type, channel, cc)`, which is what this repo assumed at first. The two
byte orders are indistinguishable in the stock presets — both store
`(0, 1, cc)` — so the mistake survived a self-check that happened to use the
same wrong order. **Hardware measurement settled it:** under `mgb-mode` the
buttons were observed transmitting on **ch1**, and only `(channel, type, cc)`
predicts that.

A retracted claim: this README previously stated that the downloaded 2016
`MIDIMix_LogicProX.midimix` was broken, with 57 controls collapsing onto 41
unique addresses. **That was wrong** — an artifact of the byte-order bug, not a
defect in the file. Decoded correctly it has **57/57 unique addresses**, with the
three button rows on ch1 / ch3 / ch2, CC22–29 each. It is a perfectly good preset.

That file also proves the button **channel is freely assignable** — it uses three
different channels across the rows. `presets/logic-mode.midimix` puts all three
rows on ch8 with distinct CC blocks, which is equivalent and easier to read.

The `type` byte is `1` in both stock presets. Its meaning is still unconfirmed;
observed behaviour is mixed (some buttons momentary, some toggling), so it is
probably not the only thing governing that.

## Two modes, hot-swappable

The device holds one config at a time, so the two rigs live in separate presets. They
are **fully disjoint** — no (channel, CC) pair appears in both — which means Logic
assignments learned in Logic mode can never be triggered while the device is in mGB
mode, and vice versa.

| | knobs | faders | buttons |
|---|---|---|---|
| **mgb-mode** | ch1, CC1–8 / 11–18 / 21–28 | ch1, CC61–69 | ch1, CC31–38 / 51–58 / 41–48 |
| **logic-mode** | ch4/5/6, CC22–29 | ch7, CC22–30 | ch8, CC22–29 / 32–39 / 42–49 |

```sh
./mgb-mode      # flash for Game Boy / Arduinoboy
./logic-mode    # flash for Logic mixing
```

Verify with `python3 tools/midimix.py diff presets/mgb-mode.midimix presets/logic-mode.midimix`.

## Tools

Pure Python, stdlib only, native arm64 CoreMIDI via ctypes. **The 2015 `MidiMix
Editor.app` is not needed** — it is x86-only abandonware surviving on Rosetta, which
Apple is winding down. It is kept in the repo as a reference fallback only.

```sh
python3 tools/midimix.py ports              # list CoreMIDI endpoints
python3 tools/midimix.py show <preset>      # decode a preset to a table
python3 tools/midimix.py diff <a> <b>       # check two presets for collisions
python3 tools/midimix.py mon [preset]       # live monitor -> writes output.md
python3 tools/midimix.py send <preset>      # flash a preset
python3 tools/midimix.py dump [out]         # request device config (see below)
python3 tools/make_logic_preset.py          # regenerate logic-mode.midimix
python3 tools/selftest.py                   # parser + preset round-trip tests
```

### A note on `MIDIPacketList`

The first version of the monitor crashed with a **bus error**. CoreMIDI declares

```c
struct MIDIPacket     { MIDITimeStamp timeStamp; UInt16 length; Byte data[256]; };
struct MIDIPacketList { UInt32 numPackets; MIDIPacket packet[1]; };
```

Natural alignment puts `packet[0]` at offset 8, because `MIDITimeStamp` is 64-bit
— but on arm64 CoreMIDI wraps both structs in `#pragma pack(4)`, so it actually
begins at offset **4**. Reading at 8 lands inside the timestamp, produces a garbage
length, and walks off the end of the buffer. The parser now probes both layouts,
validates that each packet starts with a real status byte, and bounds every read,
so malformed input yields nothing instead of killing the process.

Two other traps in the ctypes bindings, both fatal and both silent:

- **Every function needs `argtypes`.** Without them ctypes passes 64-bit
  `CFStringRef` pointers as 32-bit ints, truncating them.
- **`MIDIObjectRef` and friends are `UInt32` typedefs, not pointers.**

`tools/selftest.py` covers the parsing deterministically. It does not exercise
Apple's own struct construction: CoreMIDI will not deliver a virtual endpoint's
traffic back to the client that created it, and cross-process virtual endpoints
did not deliver here either. The real device is the final check.

`dump` sends opcode `0x66`, a guess at the read pairing for the confirmed `0x67`
write. If the device doesn't answer, nothing is harmed — an unrecognised SysEx is
ignored — and the exported preset files remain the authoritative backup.

## Backups

- `backups/logic-cs.*.bin` — a copy of `~/Library/Preferences/com.apple.logic.pro.cs`,
  115 KB, **776 controller-assignment records**. Logic has *no export function* for
  controller assignments, so this file is the only recovery path. Logic rewrites it on
  quit, so re-copy after any mapping session.
- `presets/mgb-mode.midimix` — the working Game Boy config, exported from the device.

**Never drop the 2016 `com.apple.logic.pro.cs` into `~/Library/Preferences`.** Logic has
no merge or import for assignments; it would replace the live file wholesale and destroy
all 776 existing records, including the mGB template's. It is kept here as a *reference*
for the intended mapping only.

## Mapping in Logic

Suspects, in order, for "Learn isn't working":

1. **Order of operations.** Learn is: `Cmd+K` → **Learn Mode** on → **click the
   on-screen parameter first** so it is focused → *then* move the hardware. Moving the
   hardware first is the most common reason nothing happens.
2. **Use Expert view** (bottom-left). It exposes the **Input Message** field — if that
   reacts when you move a fader, Logic is receiving and only the target is wrong. If it
   stays dead, Logic is not receiving at all.
3. **Settings → MIDI → Inputs** — confirm MIDI Mix is enabled.
4. **Setup → Control Surfaces → Setup** — confirm nothing has claimed the port. A
   control surface plugin holding it hides the device from Controller Assignments.
5. **Hardware state.** SOLO is a hold-modifier; BANK L/R shift which channels are
   controlled.

Target layout for logic-mode:

- Faders 1–8 (ch7 CC22–29) → track **Volume**, tracks 1–8. In Expert view set a
  **fixed track index per assignment** — left on *Selected Track*, all eight faders
  fight over whichever track is selected. This is the second-most-common failure.
- Fader 9 (ch7 CC30) → Master / Output volume
- Knob row 1 (ch4) → **Pan** · row 2 (ch5) → **Send 1** · row 3 (ch6) → **Send 2**
- MUTE (ch8 CC22–29) → Mute · REC ARM (ch8 CC32–39) → Record Enable ·
  SOLO+MUTE (ch8 CC42–49) → Solo

After a mapping session: quit Logic (it flushes the `.cs` on exit), then re-copy it into
`backups/` and commit.

## Hardware notes

- The manual requires a **powered** hub if you use one. Currently plugged directly into
  the Mac, which sidesteps this.
- **SEND ALL** retransmits every control's current position, so software can sync to the
  physical positions. The manual notes it may do nothing if the software uses pickup or
  takeover mode.
- **BANK LEFT / RIGHT transmit nothing.** Measured: a 70-second full-panel sweep
  produced 1101 messages across exactly the 57 preset addresses and **nothing else**.
  The manual says they "shift the 8 channels controlled by MIDImix"; that shift is
  handled entirely inside the firmware. They cannot be mapped. Use a Logic key
  command for banking, or repurpose two spare buttons.
- **SOLO is a toggle on this unit, not a hold.** The manual says "press and hold";
  the hardware disagrees. Press it once to arm the shifted layer, again to leave.
  The shifted MUTE row (CC41–48 in mgb-mode) transmits either way.
- **Button behaviour is mixed** — some send 127-on-press / 0-on-release (momentary),
  others alternate 127 / 0 across presses (toggle). Both look identical on the wire,
  so Logic sees only "a CC that goes to 127 and later to 0".
- **The LEDs do not self-light.** Undocumented — the manual has no LED section.
  Run `python3 tools/midimix.py led` to test whether they respond to MIDI echoed
  back to the device. This matters: if they need an echo, Logic's Controller
  Assignments cannot provide one and the lamps will stay dark on that route.
