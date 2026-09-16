# AKAI MIDI Mix for Logic Pro

Use an AKAI MIDI Mix as a banked Logic Pro mixer surface. This project creates a
small virtual Mackie Control bridge so Logic sees the MIDI Mix as a real control
surface.

## Requirements

- macOS with Logic Pro
- AKAI MIDI Mix connected by USB
- Python 3.9 or newer, installed and available as `python3`
- Akai's MIDI Mix Editor, once, to load the included hardware preset. Download the
  [official macOS editor](https://cdn.inmusicbrands.com/akai/MIDImix_Editor_v1.0.7.dmg).

## Install and configure

1. Download or clone this repository.
2. Use Akai's official MIDI Mix Editor to load this repository's included
   `MIDIMix_LogicProX2026.midimix` preset onto the controller: **File → Open
   Preset**, choose that file, then **File → Send to Hardware**. Akai's
   [Logic setup article](https://support.akaipro.com/en/support/solutions/articles/69000824292-akai-pro-midimix-setup-with-logic-pro-x)
   illustrates the editor workflow.

   **Do not download or install Akai's `com.apple.logic.pro.cs` file.** It is a
   different, preference-replacement mapping, it does not work with this bridge,
   and replacing that file can overwrite existing Logic Controller Assignments.
   Do not use Akai's downloadable preset either—load only
   `MIDIMix_LogicProX2026.midimix` from this repository.
3. Double-click [mixer-mode.command](mixer-mode.command). Keep its terminal window
   open while mixing.
4. In Logic Pro, open **Control Surfaces → Setup**. Add **Mackie Designs → Mackie
   Control** if it is not already present, and set both its Input and Output to
   **MIDI Mix MCU**.
5. In **Logic Pro → Settings → MIDI → Inputs**, disable the real **MIDI Mix** input.
   The bridge handles that physical port; leave its virtual ports enabled.
6. Set the physical MASTER once: select Logic's actual Master volume fader, choose
   **Logic Pro → Control Surfaces → Learn Assignment for Volume**, then move the
   physical MASTER fader. It learns the bridge's dedicated `MIDI Mix Fixed` message
   and never follows bank changes.
7. For normal track banking, set the Mackie control-surface group's **Channel Strip
   View Mode** to **Tracks** or **Arrange**, not **All**.

## What works

| MIDI Mix control | Logic behavior |
|---|---|
| Faders 1–8 | Volume for the current eight-track bank |
| MASTER fader | Actual Logic Master; fixed and never banked |
| BANK LEFT / RIGHT | Move by one eight-track bank |
| MUTE 1–8 | Mute the corresponding tracks |
| REC ARM 1–8 | Record-enable the corresponding tracks |
| SOLO key | Tap toggles a solo layer; holding it still enables the hardware solo layer |
| SEND ALL | Preset-snapshot suppression is implemented; live hardware verification is pending |
| Knob rows 1–3 | 24 independent, fixed custom-learn controls |
| Panel lamps | Follow Logic mute, solo, and record-enable feedback |

Faders support **soft takeover** (default on): after banking, a fader only takes effect
once it crosses through Logic's current value, preventing jumps. Both fader mode and
knob layout can be changed live (type `takeover` or `knobs` in the bridge window) or
pre-set with `mixer-setup.command`.

## Knob choices

`mixer-setup.command` saves the preferred mode:

- **fixed** (default): 24 stable custom-learn controls via the virtual **MIDI Mix
  Fixed** port. Learn any selected Logic parameter—send level, pan, expression,
  or a plug-in parameter—to any knob. Each assignment stays tied to that exact
  Logic target and does not follow fader banking.
- **vpot**: the established manual Mackie V-Pot behavior. The top physical row adjusts
  the one standard MCU parameter currently selected in Logic (for example, pan or one
  send slot) across the current bank. It follows banking and needs no learns.
- **disabled**: leave the knobs unused.

### First-time fixed custom-knob setup

Start the bridge and type `learn`. Click the exact Logic parameter, choose **Control
Surfaces → Learn Assignment for Selected Parameter**, then type `learn <row> <strip>`
in the bridge window. For example, `learn 2 4` sends the unique CC for row 2, strip 4;
Logic decides whether that is a send level, expression, pan, or a plug-in parameter.
`learn master` is available if the Master assignment ever needs to be recreated.

Controller Assignments are stored by Logic globally rather than as a clean per-project
knob layout. Test a new project before relying on custom learns there.

## Known limitations

- The default `fixed` knob assignments are track/parameter locked and do not follow
  the eight-fader bank. A knob learned to Track 3 remains assigned to Track 3 after
  the faders bank to tracks 9–16.
- Mackie Control exposes only one shared bank of eight V-Pots. Consequently, optional
  `vpot` mode uses only the top physical knob row; rows 2 and 3 are inactive in that
  mode. The default `fixed` mode bypasses this restriction and exposes all 24 knobs.
- The MIDI Mix has absolute, non-motorized faders and knobs. Soft takeover prevents
  most fader jumps after banking, but the hardware cannot move to match Logic. After
  changing knob modes, the first knob movement establishes its relative baseline.
- The fixed Master assignment and `fixed` knob learns are global Logic
  Controller Assignments, not portable per-project mappings.
- `SEND ALL` has no unique programmable message. The bridge suppresses the snapshot
  produced by the included preset; another hardware preset may produce a different
  burst and is unsupported.
- Run only one bridge instance, and keep its terminal window open while mixing.

## Dependencies and security

A virtual environment is not required. The bridge installs no packages and uses only
Python's standard library plus Apple's local CoreMIDI and CoreFoundation frameworks.
It performs no network access, automatic downloads, preset flashing, or replacement
of Logic preference files. A venv would isolate third-party Python packages, but there
are none here, and it would not sandbox MIDI hardware or Logic.

## Daily use

Start `mixer-mode.command`, mix, then type `q` in its terminal window when finished.
If the bridge is running and Logic does not connect, verify the Mackie Control is using
**MIDI Mix MCU** for both Input and Output, then restart the bridge.

## Optional: pre-set preferences

Double-click `mixer-setup.command` to choose your knob layout and fader mode before
starting the bridge. The choices are saved and applied the next time
`mixer-mode.command` starts. Restart an already-running bridge after changing them.

## Included files

- `mixer-mode.command` — daily launcher
- `mixer-setup.command` — knob/fader preference setup
- `MIDIMix_LogicProX2026.midimix` — required MIDI Mix preset
- `tools/mcu_surface.py` and `tools/coremidi.py` — the bridge and its small
  CoreMIDI runtime helper

## License

The project code and included project files are released under the [MIT License](LICENSE.txt).
The Akai editor application and vendor manual are deliberately not bundled. The
repository contains only the files needed to install, run, configure, and document
the bridge.
