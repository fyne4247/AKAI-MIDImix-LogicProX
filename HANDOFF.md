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

### 3.3 Button records are (channel, type, cc) — a corrected earlier claim

**Retraction.** An earlier version of this document stated that the downloaded 2016
`MIDIMix_LogicProX.midimix` was broken, with 57 records collapsing onto 41 unique
addresses. **That was wrong.** It came from decoding button records as
`(type, channel, cc)` when the real layout is `(channel, type, cc)`. Decoded correctly,
that file has **57/57 unique addresses** (button rows on ch1 / ch3 / ch2, CC22–29 each)
and is perfectly usable.

The two orderings are indistinguishable in the stock presets — both store `(0, 1, cc)` —
and `make_logic_preset.py`'s own uniqueness self-check used the same wrong order, so it
validated the bug instead of catching it. **Hardware measurement settled it:** under
`mgb-mode` the buttons transmit on **ch1**, which only `(channel, type, cc)` predicts.

Consequences already applied:
- `parse_preset`, `build_preset`, `control_map`, `channels_used`, `cmd_show` and
  `make_mapping_doc.py` corrected.
- `presets/logic-mode.midimix` **regenerated** — the old one wrote `7` into the *type*
  byte and left buttons on ch1, which would have collided with mGB's CC32–38 and CC42–48.
  It was never flashed. The current file is verified 57/57 unique and disjoint from mGB.
- The `type` byte is `1` in both stock presets; `logic-mode` now matches.

### 3.4 Faders cannot be made relative in hardware

The manual specifies **270° pots**, not endless encoders. The hardware sends absolute
position 0–127. No preset setting can change this. Relative behaviour and soft-takeover
are only achievable in software, sitting between the device and Logic — which is the main
argument for the translator in §5.

Separately: **Latch vs Touch is Logic's per-track automation mode**, unrelated to any of
this, and works regardless of route. Nothing to configure.

### 3.5 The four fixed buttons — measured, they transmit nothing

The panel has **20 physical buttons** (8 MUTE, 8 REC ARM, SEND ALL, BANK LEFT, BANK
RIGHT, SOLO) but the preset stores **24 button records**. The extra row of 8 is the
SOLO-shifted MUTE layer. **Now confirmed on the wire.**

Measurement: a 70-second full-panel sweep, 1101 messages, produced hits on exactly the
57 preset addresses and **nothing outside them**.

- **BANK LEFT / BANK RIGHT — contradictory results.** First measurement (70s sweep,
  1101 messages) found nothing outside the 57 preset addresses — concluded they transmit
  nothing. Second measurement (2026-07-27, later run) showed BANK LEFT producing
  ch1 CC25 and BANK RIGHT producing ch1 CC26. Those are **knob row3 strip5 / strip6
  addresses in the mGB preset**, so either (a) the bank buttons share addressing with
  those knobs, or (b) they were accidentally bumped. **Not settled — needs a focused
  retest with hands off the knobs.** If they do transmit on those CCs, they are
  mappable after all but will collide with the knobs unless the logic-mode preset
  moves them apart.
- **SEND ALL** retransmits control positions. Second run showed it sending the first
  5 controls with non-zero positions (knob row1 strips 1/3/5/7 and fader MASTER).
  No message of its own — exactly as the manual describes.
- **SOLO behaviour is inconsistent across runs.** First run: toggle (press once to arm,
  again to leave). Second run: hold, matching the manual. The firmware may have two
  modes, or the state may depend on power-cycle / bank state. Releasing SOLO on the
  second run also produced a ch1 CC27 (knob row3 strip7) message — possibly a
  physical bump, possibly firmware. **Not settled.**
- **Button press behaviour is mixed** — some momentary (127 on press, 0 on release),
  some toggling (127, then 0 on the next press). Indistinguishable on the wire: a
  receiver sees only a CC going to 127 and later to 0.
- **The LEDs do not respond to MIDI feedback — confirmed.** Tested with working
  output (the outbound pack(4) fix verified by selftest round-trip). Neither CC
  nor Note On messages on any channel light any lamp. The LEDs are firmware-internal
  only. Neither Controller Assignments nor a translator daemon can light them.
  This removes LED feedback as an argument for the translator route.

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
payload = 24 knobs ×2 (channel, cc) | 9 faders ×2 (channel, cc) | 24 buttons ×3 (channel, type, cc)
```
Channel bytes are 0-based on the wire. `0x66` is a *guess* at the paired read opcode;
`tools/midimix.py dump` tries it, and has never been run against the device.

### Preset layouts (verified disjoint — neither can trigger the other's assignments)

| | knobs | faders | buttons |
|---|---|---|---|
| mgb-mode | ch1, CC1–8 / 11–18 / 21–28 | ch1, CC61–69 | ch1, CC31–38 / 51–58 / 41–48 |
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

### Phase 0 — measure first — **DONE**

Completed 2026-07-27. 70s sweep, 1101 messages, 57/57 preset controls seen, nothing
outside the preset. Results in §3.5. The monitor is confirmed working against real
hardware — the `MIDIPacketList` offset fix is good.

Two bugs this run exposed, both since fixed: the live counter counted
non-preset addresses toward its `n/57` total, and the summary would assert
"banking is achievable" from unknown addresses without checking that preset coverage
was complete — which is exactly how it reached the wrong verdict on this very capture.
It now reports a preset mismatch when unknowns and missing controls rise together.

To re-run at any point:

```sh
python3 tools/midimix.py mon presets/mgb-mode.midimix
```

LED test completed — LEDs do not respond to host MIDI. See §3.5.

**The `pack(4)` trap bit twice.** The inbound fix (§ the `MIDIPacketList` note) was only
half of it: `_packet_list`, used for *every* outgoing message, was still built at natural
alignment. CoreMIDI read the packet length out of the zero half of the timestamp, so it
sent a zero-length packet — no error code, no data. **Every `send` and every LED message
this tool ever issued was silently empty**, which is why the first LED test showed
nothing. Fixed, and `selftest.py` now round-trips `_packet_list` output back through
`_iter_packets` — the reader that hardware has already validated. If you touch either
function, keep that check.

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
**BANK LEFT/RIGHT are dead ends** — Phase 0 measured them transmitting nothing (§3.5),
so MCU notes 46/47 cannot be driven from them. Pick one instead:

- **Repurpose two buttons.** REC ARM 7 and 8 are the obvious candidates; the translator
  maps them to MCU notes 46/47 rather than to record-enable. Costs two record-arms.
- **Logic key command.** Leave the panel out of it entirely. Costs nothing, but means
  reaching for the keyboard.

Recommendation: repurpose REC ARM 7/8, since the whole point is to stop touching the
keyboard. Make it a constant at the top of the daemon so it is trivial to change.

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

Resolved since the first draft: BANK LEFT/RIGHT **do not transmit** (§3.5); the monitor
**does** work against hardware; the button record byte order is `(channel, type, cc)`
(§3.3); the SOLO-shift layer is real and SOLO toggles rather than holds.

Still open:

1. ~~Do the button LEDs accept MIDI feedback?~~ **Resolved: no.** Tested with
   confirmed-working output. LEDs are firmware-internal only. This is no longer
   an argument for or against any route.
2. **The Mackie handshake.** The single biggest project risk. §6 Phase 1.
3. **What the button `type` byte means.** Both stock presets use `1`. Observed press
   behaviour is mixed, so `type` is probably not the only factor. Low priority — it does
   not affect addressing, which is all Logic sees.
4. **Whether `0x66` is really the preset read opcode.** Never tested. Harmless to try.
5. **Banking without hardware support.** Since BANK L/R are dead, decide between a Logic
   key command and repurposing two REC ARM buttons.

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
