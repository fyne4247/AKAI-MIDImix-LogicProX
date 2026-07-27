# Handoff: AKAI MIDI Mix → Logic Pro mixer surface

**Written 2026-07-27.** Self-contained: a fresh session should be able to act on this
without re-deriving anything. Everything below was verified on this machine unless
explicitly flagged as unverified.

---

## 1. The goal

Make the AKAI MIDI Mix work as a real mixer surface for Logic Pro — faders on track
volume, knobs on pan/sends, buttons on mute/solo/rec-arm, with banking to reach tracks
beyond 8.

The user's priorities, in their words:
- Getting it to "do what it's supposed to — be a mixer" is the priority.
- Preserving the existing mGB/Arduinoboy Game Boy setup is **not** a major concern
  (though it is already safely exported and committed, so it costs nothing to keep).
- Logic's Controller Assignments interface is "confusing" and they'd prefer to avoid it.
- Faders should not jump — they want touch/latch-style behaviour, or relative control.

## 2. Machine state (verified)

| Item | Value |
|---|---|
| Hardware | Apple Silicon (arm64), Darwin 25.5, Rosetta 2 installed |
| Logic Pro | **12.3** |
| Device | AKAI "MIDI Mix", USB, now plugged **directly into the Mac** (was on a GenesysLogic hub) |
| CoreMIDI | 1 source + 1 destination, both named `MIDI Mix` |
| Assignments file | `~/Library/Preferences/com.apple.logic.pro.cs` — 115 KB, **776 records** |
| Other MIDI gear seen in Logic's port table | `MPK mini IV`, `EWI-USB`, `iPad`, Logic Pro Virtual In/Out |
| `poppler` | installed via Homebrew (PDF rendering available) |

## 3. Findings — the important ones

### 3.1 The Control Surfaces route is closed. Permanently.

The MIDI Mix is not in Logic's installable device catalog (confirmed by the user in
Setup → Control Surfaces → Install; Akai entries are MAX49, LPD8, MPD24, the MPK family
and MPK mini — no MIDImix). The hardware has no Mackie/HUI emulation mode. Logic's Scan
cannot find it and never will.

"Recording Light" appearing there is **not** recognition of the MIDI Mix — it is an
unrelated Logic utility that flashes an external recording lamp, and was simply the
default-highlighted first row.

### 3.2 Why the user's earlier Learn attempts "stopped working" — root cause found

Logic keeps a **fixed table of remembered MIDI ports** inside `com.apple.logic.pro.cs`,
and controller assignments bind to a *slot* in that table. Diffing the file before and
after plugging in the MIDI Mix showed:

```
offset 13638:  was "EWI-USB\0"   ->  now "MIDI Mix"
offset 13946:  was "EWI-USB\0"   ->  now "MIDI Mix"
```

**The MIDI Mix took over the slot the AKAI EWI-USB previously held.** So assignments
learned in one session get re-pointed at a different device the next time the set of
connected gear differs. The assignments were never lost — they were aimed at the wrong
port. This is the mechanism behind "I had it successfully learned once and then the next
time I opened the same project it no longer worked."

Corollaries:
- Controller assignments are **global, not per-project**.
- Logic **does** see the MIDI Mix at the MIDI level — port recognition works fine. Only
  the Control Surfaces catalog doesn't know it.
- Logic rewrites this file periodically while running, not only on quit (observed:
  mtime advanced while Logic was open).
- A stable **virtual** port name would sidestep the whole slot-reuse problem.

### 3.3 The downloaded 2016 preset is broken — do not flash it

`MIDIMix_LogicProX.midimix` (from the web) has 57 control records resolving to only **41
unique (channel, CC) addresses**. All three button rows sit on ch2 CC22–29:

```
ch2 CC22 used by 3 controls (MUTE 1, REC ARM 1, SOLO+MUTE 1)   ... ×8
```

They differ only in a per-button `type` byte which is a device-side flag and is **not
transmitted**. Logic cannot distinguish the three button rows under that preset.
`presets/logic-mode.midimix` (generated) fixes this: 57 controls → 57 unique addresses.

### 3.4 Faders cannot be made relative in hardware

The manual specifies **270° pots**, not endless encoders. The hardware sends absolute
position 0–127. No preset setting can change this. Relative behaviour and soft-takeover
are only achievable in software, sitting between the device and Logic — which is the main
argument for the translator in §5.

Separately: **Latch vs Touch is Logic's per-track automation mode**, unrelated to any of
this, and works regardless of route. Nothing to configure.

### 3.5 The four fixed buttons

The panel has **20 physical buttons** (8 MUTE, 8 REC ARM, SEND ALL, BANK LEFT, BANK
RIGHT, SOLO) but the preset stores **24 button records**. The extra row of 8 is the
SOLO-shifted MUTE layer — the manual: *"press and hold Solo, then press the Mute buttons
to solo their tracks."* Confirmed by arithmetic and the manual; **not yet confirmed on
the wire.**

- `SEND ALL` — snapshot function, retransmits all control positions. Manual warns it may
  do nothing under pickup/takeover modes.
- `BANK LEFT` / `BANK RIGHT` — manual says they "shift the 8 channels controlled by
  MIDImix". **UNVERIFIED whether they transmit MIDI or are handled internally by the
  firmware.** This is the single most important outstanding measurement. See §7.

## 4. What is already built

Branch `worktree-midimix-tooling`, worktree at `.claude/worktrees/midimix-tooling/`.
Six commits. No remote, so no PR.

```
tools/midimix.py           decode / monitor / flash presets. stdlib-only CoreMIDI via
                           ctypes, native arm64. Subcommands: ports, show, diff, mon,
                           send, dump
tools/make_logic_preset.py generates presets/logic-mode.midimix
tools/make_mapping_doc.py  generates MAPPING.md from the preset (cannot drift)
tools/selftest.py          16 checks, all passing
presets/mgb-mode.midimix   the working Game Boy config, exported from the device
presets/logic-mode.midimix corrected Logic layout, 57 unique addresses
./mgb-mode  ./logic-mode   one-command hot-swap wrappers
MAPPING.md                 generated per-control mapping sheet
README.md                  preset format, ctypes gotchas, troubleshooting
backups/                   copy of the live Logic .cs (776 assignments)
```

The 2015 `MidiMix Editor.app` is **not needed** — it is x86-only, Rosetta-dependent
abandonware. Kept as a reference fallback only. Everything it does, `tools/midimix.py`
does natively.

### Preset format (reverse-engineered, verified against two presets)

```
F0 47 00 31 67 01 0A   <138 payload bytes>   F7
                 `--`-- 7-bit length pair: (0x01<<7)|0x0A = 138
              `-------- opcode 0x67 = write config
payload = 24 knobs ×2 (channel, cc) | 9 faders ×2 (channel, cc) | 24 buttons ×3 (type, channel, cc)
```
Channel bytes are 0-based on the wire. `0x66` is a *guess* at the paired read opcode;
`tools/midimix.py dump` tries it, and has never been run against the device.

### Preset layouts (verified disjoint — neither can trigger the other's assignments)

| | knobs | faders | buttons |
|---|---|---|---|
| mgb-mode | ch1, CC1–8 / 11–18 / 21–28 | ch1, CC61–69 | ch2, CC31–38 / 51–58 / 41–48 |
| logic-mode | ch4/5/6, CC22–29 | ch7, CC22–30 | ch8, CC22–29 / 32–39 / 42–49 |

### Known ctypes traps (all already fixed — do not reintroduce)

1. **`MIDIPacketList` layout.** On arm64 CoreMIDI wraps the structs in `#pragma pack(4)`,
   so `packet[0]` starts at offset **4**, not the 8 that natural alignment implies.
   Reading at 8 lands inside the 64-bit timestamp, yields a garbage length, and walks off
   the buffer — a **bus error**, no Python traceback. The parser now probes both offsets,
   validates that each packet opens with a status byte (≥0x80), and bounds every read.
2. **Every CoreMIDI function needs `argtypes`.** Without them ctypes passes 64-bit
   `CFStringRef` pointers as 32-bit ints and truncates them. Silent crash.
3. **`MIDIObjectRef`/`MIDIClientRef`/`MIDIPortRef`/`MIDIEndpointRef` are `UInt32`
   typedefs, not pointers.**
4. **SIGINT cannot interrupt `CFRunLoopRunInMode`.** Use an explicit signal handler.
5. **CoreMIDI caches the endpoint list**; it only refreshes on run-loop notifications, so
   poll with `_pump()`, never `time.sleep()`.
6. **In-process loopback is impossible.** CoreMIDI does not deliver a virtual endpoint's
   traffic back to the client that created it. Cross-process virtual endpoints also did
   not deliver in this environment. Do not burn time retrying this — test against the
   real device.

## 5. The chosen direction: a Mackie Control translator daemon

**Concept.** A background process creates a virtual CoreMIDI port pair that speaks the
Mackie Control protocol. Logic's built-in Mackie/Logic Control driver *is* in the Install
catalog, so Logic accepts the virtual port as a genuine control surface. The daemon
listens to the real MIDI Mix and translates its CCs into MCU messages.

**Why this over Controller Assignments:**
- Logic recognizes it as a real control surface — banking and track-following come free.
- **Zero** manual assignments. No Controller Assignments interface at all.
- MCU is **bidirectional**: Logic sends fader positions back. The daemon therefore knows
  Logic's current values, which makes genuine **soft-takeover** possible — the fix for
  the user's jumping-fader complaint. The hardware can't display it; the daemon only
  needs to compare.
- A stable virtual port name sidesteps the port-slot-reuse bug in §3.2.

**Honest costs:**
- The MIDI Mix has no motorized faders and no displays. Feedback is one-way to the user;
  physical fader positions will diverge from Logic's after banking or project switches.
  Soft-takeover manages this but cannot eliminate it.
- The daemon must be running for the surface to exist.
- MCU is only semi-documented. See §6 for the biggest risk.

## 6. Implementation plan

### Phase 0 — measure first (blocking, ~5 min of user time)

```sh
cd .claude/worktrees/midimix-tooling
python3 tools/midimix.py mon presets/mgb-mode.midimix
```

Sweep the entire panel — every knob, every fader, every MUTE and REC ARM, then **hold
SOLO while pressing each MUTE**, then SEND ALL / BANK LEFT / BANK RIGHT. Ctrl-C when done.

**The result is written to `output.md`** as a compact summary — per-address stats, which
preset controls were never seen, and which messages fell outside the preset. Read that
file, not the terminal scrollback: a full sweep is thousands of messages. The live display
prints one line per *new* control with a running `n/57` count, so it is obvious when
coverage is complete.

This confirms all 57 controls transmit, verifies the SOLO-shift theory, and — critically —
settles whether BANK LEFT/RIGHT transmit anything. **Do not start Phase 4 without this.**
`output.md` states the banking verdict explicitly.

Note: the monitor has never successfully captured real input yet. The first attempt
bus-errored (§4 trap 1). The fix is committed and unit-tested but **unconfirmed against
hardware.** If it prints nothing while controls move, capture raw bytes rather than
guessing again.

### Phase 1 — prove Logic accepts a virtual surface (the make-or-break step)
Create a virtual CoreMIDI source+destination pair named something Logic-friendly. In
Logic: Setup → Control Surfaces → Install → **Mackie Designs / Mackie Control** → Add,
and point its input/output at the virtual ports. Then send a single fader move and see if
Logic responds.

**Biggest risk, flagged clearly:** Mackie/Logic Control uses a SysEx **handshake** —
host sends a device query, the surface replies with a serial number and a
challenge/response. If Logic requires this before accepting the surface, it must be
emulated correctly or nothing works. The exact byte sequence is **not verified here** and
must be checked against a reference implementation (Ardour's `mackie` control surface
code and the community "Mackie Control protocol" notes are the usual sources). Budget
real time for this. If Logic rejects the surface after a genuine attempt at the
handshake, **stop and fall back to §8** rather than grinding.

### Phase 2 — faders only
MCU faders are **14-bit Pitch Bend**, one MIDI channel per strip: channels 1–8 for strips
1–8, channel 9 for master. Map MIDI Mix fader CC (7-bit) → pitch bend (14-bit).
Verify all 9 move the right tracks in Logic. Stop here and confirm with the user before
continuing.

### Phase 3 — buttons
MCU buttons are Note On/Off on channel 1, velocity 127 = press, 0 = release. Note numbers
(**verify against a reference before trusting**):

```
REC/RDY strips 1-8   notes  0-7
SOLO    strips 1-8   notes  8-15
MUTE    strips 1-8   notes 16-23
SELECT  strips 1-8   notes 24-31
Bank Left  46    Bank Right 47
Channel Left 48  Channel Right 49
```

Map MIDI Mix MUTE row → MUTE, REC ARM row → REC/RDY, SOLO+MUTE layer → SOLO.

### Phase 4 — banking
Map BANK LEFT/RIGHT to MCU notes 46/47 **if Phase 0 showed they transmit**. If they do
not, assign two spare controls (e.g. REC ARM 7 and 8) or leave banking to a Logic key
command.

### Phase 5 — knobs (pan / sends) and soft-takeover
MCU V-Pots are **relative** encoders on CC 16–23, encoded as 0x01–0x3F = clockwise ticks,
0x41–0x7F = counter-clockwise. The MIDI Mix knobs are absolute pots, so the daemon must
convert absolute position changes into relative deltas. This conversion is also what
makes the knobs behave the way the user asked for.

For faders, implement **soft-takeover**: track Logic's last-known fader value from the
inbound pitch-bend feedback, and suppress outbound movement until the physical fader
crosses it.

### Phase 6 — packaging
A `launchd` plist or a simple `./mixer-mode` script to start/stop the daemon, plus
documentation of the Logic-side setup. Commit and update README.

## 7. Outstanding unknowns

1. **Do BANK LEFT/RIGHT transmit MIDI?** Blocking for Phase 4. Phase 0 answers it.
2. **Does the monitor actually work against hardware?** Fix is committed and unit-tested,
   never confirmed live.
3. **The Mackie handshake.** The single biggest project risk. §6 Phase 1.
4. **What the button `type` byte (0/1/2) means.** Probably toggle vs momentary; the AKAI
   editor exposes it as a checkbox. Currently set to 0 everywhere, matching the
   known-good mGB preset. Determine empirically: momentary sends 127-on-press /
   0-on-release, toggle alternates.
5. **Whether `0x66` is really the preset read opcode.** Never tested against the device.
   Harmless to try — unrecognised SysEx is ignored.

## 8. Fallback if the translator fails

Controller Assignments, using the already-generated `MAPPING.md` as the checklist. Flash
`./logic-mode` first. The critical technique, which is where the user got stuck:

1. `Cmd+K`, switch to **Expert** view (only Expert shows the **Input Message** field and
   allows fixed track indices).
2. **Click the on-screen parameter first**, so it is focused.
3. *Then* click Learn Mode, *then* move the hardware control. Doing it in the other order
   is the most common reason nothing happens.
4. Change **Track** from `Selected Track` to a **fixed track number**, or all eight
   faders fight over whichever track is selected.

Diagnostic: watch **Input Message** while moving a fader. Reacts → Logic is receiving,
only the target is wrong. Dead → Logic isn't receiving; check Settings → MIDI → Inputs.

**Given §3.2, also tell the user:** keep the MIDI Mix connected and on the same USB port
whenever Logic launches, or the port-slot reuse will break the assignments again.

## 9. Rules for whoever picks this up

- **Never** copy the 2016 `com.apple.logic.pro.cs` into `~/Library/Preferences`. Logic has
  no merge or import; it replaces the file wholesale and destroys all 776 existing
  assignments. It is a *reference* only.
- Back up `~/Library/Preferences/com.apple.logic.pro.cs` into `backups/` before and after
  any Logic mapping session, and commit. **Logic has no export for controller
  assignments** — that file is the only copy.
- Nothing has been flashed to the device at any point. It is still in mGB config. Flashing
  is recoverable via `./mgb-mode`, but confirm with the user first.
- Don't retry in-process CoreMIDI loopback testing (§4 trap 6).
