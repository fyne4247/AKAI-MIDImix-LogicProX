#!/usr/bin/env python3
"""AKAI MIDI Mix to Logic Pro Mackie Control bridge.

The physical controller uses the CC/note layout in
``MIDIMix_LogicProX2026.midimix``. This process translates it into one virtual
Logic Control surface for banked tracks plus a separate fixed-control source
for the nonbanked Master fader and optional custom knob assignments.

Run with ``mixer-mode.command``. While it is open, type ``help`` for the small
set of supported runtime commands. See README.md for the one-time Logic and
hardware-preset setup.
"""

from __future__ import annotations

import ctypes
import fcntl
import os
import queue
import select
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coremidi as M  # noqa: E402

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

PORT_NAME = "MIDI Mix MCU"
FIXED_PORT_NAME = "MIDI Mix Fixed"
DEVICE_ID_LC = 0x10           # Emagic Logic Control
# Do not answer 0x11 / 0x15: they are extender identities. Logic's base
# controller on 0x10 is the member that receives Bank Left/Right commands.
ANNOUNCE_IDS = (DEVICE_ID_LC,)
SERIAL = b"MIDIMix"           # 7 ASCII bytes
VERSION = b"V1.00"            # 5 ASCII bytes
CLIENT_NAME = "mcu_surface.py"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_PATH = os.path.join(_ROOT, ".mcu_surface.pid")

CMD_DEVICE_QUERY = 0x00
CMD_HOST_CONN_QUERY = 0x01
CMD_HOST_CONN_REPLY = 0x02
CMD_HOST_CONN_CONFIRM = 0x03
CMD_TOUCHLESS = 0x0C
CMD_VERSION_REQUEST = 0x13
CMD_VERSION_REPLY = 0x14
CMD_GO_OFFLINE = 0x0F
CMD_RESET = 0x63

# Fader touch notes (ch 1): strip1=104 … strip8=111, master=112
TOUCH_NOTE_BASE = 104

# The current MIDIMix_LogicProX2026 preset leaves the fixed panel buttons on their firmware
# notes: BANK LEFT=25, BANK RIGHT=26, SOLO=27. Its third knob row was moved to
# CC71..78, so the fixed buttons cannot collide with it.
# Its nine faders remain channel 1 (wire channel 0), CC61 through CC69.
MGB_FADER_CCS = {61 + i: i + 1 for i in range(9)}
MGB_BANK_BUTTON_NOTES = {25: "left", 26: "right"}
# MIDIMix_LogicProX2026 programmable channel buttons (wire channel 0 = display ch1).
MGB_MUTE_CCS = {31 + i: i + 1 for i in range(8)}      # strip 1..8
MGB_REC_CCS = {51 + i: i + 1 for i in range(8)}
MGB_SOLO_LAYER_CCS = {41 + i: i + 1 for i in range(8)}  # SOLO held + MUTE
MGB_SOLO_BUTTON_NOTE = 27  # firmware fixed; local layer only, not mapped to Logic
# Knob CCs from MIDIMix_LogicProX2026 preset (all on wire channel 0 = display ch1)
MGB_KNOB_ROW1_CCS = {1 + i: i + 1 for i in range(8)}   # CC1-8 → strip 1-8
MGB_KNOB_ROW2_CCS = {11 + i: i + 1 for i in range(8)}  # CC11-18 → strip 1-8
MGB_KNOB_ROW3_CCS = {71 + i: i + 1 for i in range(8)}  # CC71-78 → strip 1-8
MGB_KNOB_ROWS = {1: MGB_KNOB_ROW1_CCS, 2: MGB_KNOB_ROW2_CCS, 3: MGB_KNOB_ROW3_CCS}
FADER_TOUCH_RELEASE_SECS = 0.18

# MCU channel-strip button notes on channel 1 (Logic / Mackie protocol).
MCU_REC_NOTE_BASE = 0     # strips 1..8 → notes 0..7
MCU_SOLO_NOTE_BASE = 8    # strips 1..8 → notes 8..15
MCU_MUTE_NOTE_BASE = 16   # strips 1..8 → notes 16..23

# A separate stable virtual source for the one thing that must never follow an
# MCU bank: the physical MASTER fader → Logic Master volume. It is kept
# separate from the MCU port so Logic can learn exactly one fixed Controller
# Assignment without colliding with control-surface messages.
FIXED_MASTER_STATUS = 0xBF  # MIDI channel 16; deliberately outside mGB use
FIXED_MASTER_CC = 119

# MCU navigation buttons (channel 1). Bank moves by eight channel strips;
# Channel moves by one. We use only Bank for the physical eight-fader layout.
MCU_BANK_LEFT_NOTE = 46
MCU_BANK_RIGHT_NOTE = 47
MCU_HOME_BANK_PRESSES = 16

MCU_VPOT_CC_BASE = 0x10  # CC16, strips 1-8 — relative encoding

# SEND ALL has no unique programmable message. With the shipped preset it
# reports this snapshot burst; treating it as normal input would move Master
# and several knobs. Suppress the complete burst when CoreMIDI delivers it
# together.
SEND_ALL_BURST_CCS = frozenset((1, 3, 5, 7, 69))
SEND_ALL_WINDOW_SECS = 0.035

KNOB_LAYOUT_PATH = os.path.join(_ROOT, ".knob_layout")
KNOB_LAYOUTS = ("fixed", "vpot", "disabled")
DEFAULT_KNOB_LAYOUT = "fixed"

# In "fixed" layout, knobs emit absolute CCs on MIDI Mix Fixed (ch16).
# They are intentionally blank, unique learn targets—not a hard-wired send map.
# Row 1 CC1-8, row 2 CC11-18, row 3 CC71-78.
# These don't collide with the master fader (CC119) on the same port.
KNOB_FIXED_CC = {
    (1, s): s for s in range(1, 9)         # row1 → CC1-8
} | {
    (2, s): 10 + s for s in range(1, 9)    # row2 → CC11-18
} | {
    (3, s): 70 + s for s in range(1, 9)    # row3 → CC71-78
}

SOFT_TAKEOVER_TOLERANCE = 2  # 0-127 units; fader is "at" host value within this
SOFT_TAKEOVER_PATH = os.path.join(_ROOT, ".soft_takeover")


def _load_knob_layout() -> str:
    try:
        layout = open(KNOB_LAYOUT_PATH).read().strip()
        if layout in KNOB_LAYOUTS:
            return layout
    except OSError:
        pass
    return DEFAULT_KNOB_LAYOUT


def _load_soft_takeover() -> bool:
    try:
        val = open(SOFT_TAKEOVER_PATH).read().strip().lower()
        return val != "off"
    except OSError:
        return True  # default on


# --------------------------------------------------------------------------
# pure protocol helpers
# --------------------------------------------------------------------------

def challenge_response(challenge: bytes) -> bytes:
    """4-byte host response to a 4-byte device challenge (TouchMCU form)."""
    if len(challenge) != 4:
        raise ValueError(f"challenge must be 4 bytes, got {len(challenge)}")
    c0, c1, c2, c3 = challenge
    r0 = 0x7F & (c0 + (c1 ^ 0x0A) - c3)
    r1 = 0x7F & ((c2 >> 4) ^ (c0 + c3))
    r2 = 0x7F & ((c3 - (c2 << 2)) ^ (c0 | c1))
    r3 = 0x7F & (c1 - c2 + (0xF0 ^ (c3 << 4)))
    return bytes([r0, r1, r2, r3])


def make_challenge() -> bytes:
    return bytes(b & 0x7F for b in os.urandom(4))


def sysex(device_id: int, cmd: int, payload: bytes = b"") -> bytes:
    return bytes([0xF0, 0x00, 0x00, 0x66, device_id, cmd]) + payload + bytes([0xF7])


def msg_host_connection_query(challenge: bytes, device_id: int) -> bytes:
    return sysex(device_id, CMD_HOST_CONN_QUERY, SERIAL + challenge)


def msg_host_connection_confirm(device_id: int) -> bytes:
    return sysex(device_id, CMD_HOST_CONN_CONFIRM, SERIAL)


def msg_version_reply(device_id: int) -> bytes:
    return sysex(device_id, CMD_VERSION_REPLY, VERSION)


def fader_pitch_bend(strip: int, value_7bit: int) -> bytes:
    """strip 1..9, value 0..127 → Pitch Bend on channel strip-1."""
    if not 1 <= strip <= 9:
        raise ValueError(f"strip must be 1..9, got {strip}")
    if not 0 <= value_7bit <= 127:
        raise ValueError(f"value must be 0..127, got {value_7bit}")
    pb = value_7bit * 0x3FFF // 127
    ch = strip - 1
    return bytes([0xE0 | ch, pb & 0x7F, (pb >> 7) & 0x7F])


def fader_touch(strip: int, down: bool) -> list:
    """Fader touch as MCU note bangs on ch1, notes 104..112.

    Returns one or two messages. Touch down = Note On vel 127.
    Release = Note On vel 0 *and* Note Off (hosts vary).
    """
    if not 1 <= strip <= 9:
        raise ValueError(f"strip must be 1..9, got {strip}")
    note = TOUCH_NOTE_BASE + (strip - 1)
    if down:
        return [bytes([0x90, note, 127])]
    return [bytes([0x90, note, 0]), bytes([0x80, note, 0])]


def parse_mackie_sysex(msg: bytes):
    if len(msg) < 7 or msg[0] != 0xF0 or msg[-1] != 0xF7:
        return None
    if msg[1:4] != bytes([0x00, 0x00, 0x66]):
        return None
    return msg[4], msg[5], msg[6:-1]


def parse_mgb_fader(msg: bytes):
    """Return ``(strip, value)`` for a current-preset MIDI Mix fader CC."""
    if len(msg) < 3 or msg[0] != 0xB0:
        return None
    strip = MGB_FADER_CCS.get(msg[1])
    return (strip, msg[2]) if strip is not None else None


def parse_mgb_bank_button(msg: bytes):
    """Return ``(direction, pressed)`` for MIDIMix_LogicProX2026's fixed bank buttons.

    These hardware buttons are firmware-fixed Note 25/26. In the original mGB
    preset those note numbers were easily confused with knob CC25/26; the 2026 preset
    moves that knob row to CC71..78, making the separation obvious.
    """
    if len(msg) < 3:
        return None
    kind, channel = msg[0] & 0xF0, msg[0] & 0x0F
    if channel != 0 or kind not in (0x90, 0x80):
        return None
    direction = MGB_BANK_BUTTON_NOTES.get(msg[1])
    if direction is None:
        return None
    return direction, kind == 0x90 and msg[2] != 0


def parse_mgb_channel_button(msg: bytes):
    """Return ``(kind, strip, pressed)`` for MUTE / REC / SOLO-layer CCs.

    kind is \"mute\", \"rec\", or \"solo\" (SOLO held + MUTE strip).
    pressed is True when value >= 64 (momentary or toggle 0/127).
    """
    if len(msg) < 3 or msg[0] != 0xB0:
        return None
    cc, val = msg[1], msg[2]
    if cc in MGB_MUTE_CCS:
        return "mute", MGB_MUTE_CCS[cc], val >= 64
    if cc in MGB_REC_CCS:
        return "rec", MGB_REC_CCS[cc], val >= 64
    if cc in MGB_SOLO_LAYER_CCS:
        return "solo", MGB_SOLO_LAYER_CCS[cc], val >= 64
    return None


def mcu_channel_button_note(kind: str, strip: int) -> int:
    """MCU note number for a channel-strip button (strip 1..8)."""
    if not 1 <= strip <= 8:
        raise ValueError(f"strip must be 1..8, got {strip}")
    if kind == "mute":
        return MCU_MUTE_NOTE_BASE + strip - 1
    if kind == "solo":
        return MCU_SOLO_NOTE_BASE + strip - 1
    if kind == "rec":
        return MCU_REC_NOTE_BASE + strip - 1
    raise ValueError(f"unknown button kind {kind!r}")


def hardware_led_note(kind: str, strip: int):
    """AKAI panel LED note (ch1) for mute/solo/rec, or None if no lamp.

    Base-3 map from output/led-note-map.md. REC 8 is the logical extension
    note 24 (= 3*8); confirmed only after the extended note scan if present.
    """
    if not 1 <= strip <= 8:
        return None
    if kind == "mute":
        return 3 * (strip - 1) + 1          # SOLO released layer
    if kind == "solo":
        return 3 * (strip - 1) + 2          # SOLO held / software-solo layer
    if kind == "rec":
        return 3 * strip                     # RA1..8 → notes 3,6,...,24
    return None


def parse_mcu_led_note(msg: bytes):
    """If msg is an MCU LED note from Logic, return ``(kind, strip, on)``."""
    if len(msg) < 3:
        return None
    kind, channel = msg[0] & 0xF0, msg[0] & 0x0F
    if channel != 0 or kind not in (0x90, 0x80):
        return None
    note, vel = msg[1], msg[2]
    on = kind == 0x90 and vel >= 64
    if MCU_MUTE_NOTE_BASE <= note <= MCU_MUTE_NOTE_BASE + 7:
        return "mute", note - MCU_MUTE_NOTE_BASE + 1, on
    if MCU_SOLO_NOTE_BASE <= note <= MCU_SOLO_NOTE_BASE + 7:
        return "solo", note - MCU_SOLO_NOTE_BASE + 1, on
    if MCU_REC_NOTE_BASE <= note <= MCU_REC_NOTE_BASE + 7:
        return "rec", note - MCU_REC_NOTE_BASE + 1, on
    return None


def mcu_button_press(note: int) -> list:
    """Return a complete press/release for an MCU button on channel 1."""
    if not 0 <= note <= 127:
        raise ValueError(f"MCU note must be 0..127, got {note}")
    return [bytes([0x90, note, 127]), bytes([0x80, note, 0])]


def parse_mgb_knob(msg: bytes):
    """Return ``(row, strip, value)`` for a 2026-preset knob CC, or None."""
    if len(msg) < 3 or msg[0] != 0xB0:
        return None
    cc = msg[1]
    for row, ccs in MGB_KNOB_ROWS.items():
        strip = ccs.get(cc)
        if strip is not None:
            return row, strip, msg[2]
    return None


def vpot_relative(strip: int, delta: int) -> list[bytes]:
    """Conservative MCU V-Pot ticks for one absolute-knob movement.

    The MIDI Mix pots can jump by many absolute units between samples. Mackie
    V-Pots are relative encoders, so translate only the direction and a small
    bounded amount. This avoids undefined high relative values and prevents a
    single noisy sample from sweeping a send.
    """
    if not 1 <= strip <= 8:
        raise ValueError(f"strip must be 1..8, got {strip}")
    if delta == 0:
        return []
    cc = MCU_VPOT_CC_BASE + strip - 1
    value = 0x01 if delta > 0 else 0x41
    repeats = min(abs(delta), 4)
    return [bytes([0xB0, cc, value])] * repeats


def _crosses(prev, current: int, target: int) -> bool:
    """True if the physical fader crossed or matched the host value."""
    if abs(current - target) <= SOFT_TAKEOVER_TOLERANCE:
        return True
    if prev is None:
        return False
    return (prev < target <= current) or (prev > target >= current)


# --------------------------------------------------------------------------
# single-instance lock
# --------------------------------------------------------------------------

def _acquire_pid_lock():
    """Hold an OS lock so duplicate virtual ports cannot be created."""
    lock_file = open(PID_PATH, "a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.seek(0)
        owner = lock_file.read().strip() or "unknown"
        lock_file.close()
        raise SystemExit(
            f"another mixer bridge is already running (pid {owner}).\n"
            "Quit its mixer-mode.command window before starting another.")
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


# --------------------------------------------------------------------------
# virtual surface
# --------------------------------------------------------------------------

class VirtualMCU:
    def __init__(self, name: str = PORT_NAME):
        self.name = name
        self.device_id = DEVICE_ID_LC  # the one base identity we emulate
        self.challenges = {did: make_challenge() for did in ANNOUNCE_IDS}
        self.connected = False
        self.connected_id = None
        self.host_msg_count = 0
        self.touchless = False  # Logic may enable via cmd 0x0C
        self.quiet = True       # suppress high-rate meter / LED chatter
        self._meter_count = 0
        self._incoming = queue.SimpleQueue()
        self._closing = False
        # Last fader positions Logic sent us (0..1), keyed by strip 1..9
        self.host_faders = {}
        self._logic_led_state = {}  # (kind, strip) -> bool
        self._mix_msg_count = 0
        self._mix_last_value = {}
        self._mix_touches = {}  # strip -> monotonic release deadline
        self._send_all_pending = []  # (timestamp, message)
        self._btn_state = {}    # (kind, strip) -> pressed bool
        self._solo_key_down = False
        # Software SOLO layer: tap SOLO (Note 27) toggles. While latched, MUTE
        # CCs are sent as MCU Solo, and solo LED state is painted on the mute
        # lamps so you can see it without holding SOLO.
        self.solo_mode_latched = False
        self.mix_connected = False
        self.mix_out_ok = False
        self.soft_takeover_enabled = _load_soft_takeover()
        self._soft_takeover = {}     # strip -> True (tracking) or absent (suppressed)
        self._phys_fader_last = {}   # strip -> last physical value 0-127
        self._phys_fader_sent_at = {}  # strip -> monotonic send time
        self._knob_last = {}         # (row, strip) -> last absolute value
        self._knob_layout = _load_knob_layout()

        self._on_dest_read = M.READ_PROC(self._dest_callback)
        self._on_mix_read = M.READ_PROC(self._mix_callback)

        self.client = M.Ref()
        err = M._cm.MIDIClientCreate(
            M._cfstr(CLIENT_NAME), M._NULL_NOTIFY, None, ctypes.byref(self.client))
        if err:
            raise SystemExit(f"MIDIClientCreate failed: {err}")

        for fn, res, args in [
            ("MIDISourceCreate", M.OSStatus, [M.Ref, ctypes.c_void_p, M.RefP]),
            ("MIDIDestinationCreate", M.OSStatus,
             [M.Ref, ctypes.c_void_p, M.READ_PROC, ctypes.c_void_p, M.RefP]),
            ("MIDIReceived", M.OSStatus, [M.Ref, ctypes.c_void_p]),
            ("MIDIEndpointDispose", M.OSStatus, [M.Ref]),
            ("MIDIOutputPortCreate", M.OSStatus,
             [M.Ref, ctypes.c_void_p, M.RefP]),
            ("MIDISend", M.OSStatus, [M.Ref, M.Ref, ctypes.c_void_p]),
        ]:
            getattr(M._cm, fn).restype = res
            getattr(M._cm, fn).argtypes = args

        self.source = M.Ref()
        err = M._cm.MIDISourceCreate(
            self.client, M._cfstr(name), ctypes.byref(self.source))
        if err:
            raise SystemExit(f"MIDISourceCreate({name!r}) failed: {err}")

        self.fixed_source = M.Ref()
        err = M._cm.MIDISourceCreate(
            self.client, M._cfstr(FIXED_PORT_NAME), ctypes.byref(self.fixed_source))
        if err:
            raise SystemExit(f"MIDISourceCreate({FIXED_PORT_NAME!r}) failed: {err}")

        self.dest = M.Ref()
        err = M._cm.MIDIDestinationCreate(
            self.client, M._cfstr(name), self._on_dest_read, None,
            ctypes.byref(self.dest))
        if err:
            raise SystemExit(f"MIDIDestinationCreate({name!r}) failed: {err}")

        # Listen to the physical controller with the same client that owns the
        # virtual MCU ports. CoreMIDI fans a source out to multiple clients, so
        # this does not interfere with other MIDI users.
        self.mix_input = M.Ref()
        self.mix_output = M.Ref()
        self.mix_dest = None
        try:
            mix_source = M.find_endpoint("source")
        except SystemExit:
            self.log("real 'MIDI Mix' input is not present — controls are unavailable")
        else:
            err = M._cm.MIDIInputPortCreate(
                self.client, M._cfstr("MIDI Mix in"), self._on_mix_read, None,
                ctypes.byref(self.mix_input))
            if err:
                self.log(f"could not listen to real MIDI Mix ({err}) — controls unavailable")
            else:
                err = M._cm.MIDIPortConnectSource(self.mix_input, mix_source, None)
                if err:
                    self.log(f"could not connect real MIDI Mix ({err}) — controls unavailable")
                else:
                    self.mix_connected = True
                    self.log("listening to MIDI Mix: faders CC61–69; banks Note25/26; "
                             "MUTE CC31–38; REC CC51–58; SOLO+MUTE CC41–48; "
                             "knobs CC1–8/11–18/71–78 (2026 preset)")

        try:
            mix_dest = M.find_endpoint("dest")
        except SystemExit:
            self.log("real 'MIDI Mix' output is not present — panel lamps are unavailable")
        else:
            err = M._cm.MIDIOutputPortCreate(
                self.client, M._cfstr("MIDI Mix out"), ctypes.byref(self.mix_output))
            if err:
                self.log(f"could not open MIDI Mix output ({err}) — no LED feedback")
            else:
                self.mix_dest = mix_dest
                self.mix_out_ok = True
                self.log("MIDI Mix output open — Logic mute/solo/rec LEDs → panel")

        self.log(f"virtual surface up: {name!r}  (announcing as Logic Control 0x10)")
        self.log("delete any Control Surface that still points at the real 'MIDI Mix'")

    def log(self, text: str):
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    def emit(self, msg: bytes, note: str = "", log: bool = True):
        err = M._cm.MIDIReceived(self.source, M._packet_list(msg))
        if err:
            self.log(f"MIDIReceived failed ({err}): {msg.hex(' ')}")
            return
        if log:
            tag = f"  ({note})" if note else ""
            self.log(f"→ host  {msg.hex(' ')}{tag}")

    def send_to_mix(self, msg: bytes, note: str = "", log: bool = False):
        """Host → physical MIDI Mix (panel LED feedback)."""
        if not self.mix_out_ok or self.mix_dest is None:
            return
        err = M._cm.MIDISend(self.mix_output, self.mix_dest, M._packet_list(msg))
        if err:
            self.log(f"MIDISend to MIDI Mix failed ({err}): {msg.hex(' ')}")
            return
        if log or not self.quiet:
            tag = f"  ({note})" if note else ""
            self.log(f"→ mix   {msg.hex(' ')}{tag}")

    def emit_fixed_master(self, value_7bit: int):
        """Send the stable, learnable master CC on its own virtual MIDI port."""
        self.emit_fixed_cc(FIXED_MASTER_CC, value_7bit, label="fixed-master")

    def emit_fixed_cc(self, cc: int, value_7bit: int, label: str = "fixed"):
        """Emit an absolute CC on the stable, learnable ``MIDI Mix Fixed`` port."""
        if not 0 <= cc <= 127 or not 0 <= value_7bit <= 127:
            raise ValueError("fixed CC and value must both be 0..127")
        msg = bytes([FIXED_MASTER_STATUS, cc, value_7bit])
        err = M._cm.MIDIReceived(self.fixed_source, M._packet_list(msg))
        if err:
            self.log(f"{label} MIDIReceived failed ({err}): {msg.hex(' ')}")

    def send_connection_query(self, device_id: int = None, new_challenge: bool = True,
                              clear_connected: bool = False):
        """Announce to Logic. Do NOT clear `connected` on routine Device Query
        replies — Logic re-queries often and wiping state caused flapping."""
        if clear_connected:
            self.connected = False
            self.connected_id = None
        ids = [device_id] if device_id is not None else list(ANNOUNCE_IDS)
        for did in ids:
            if new_challenge or did not in self.challenges:
                self.challenges[did] = make_challenge()
            ch = self.challenges[did]
            self.emit(msg_host_connection_query(ch, did),
                      f"Host Connection Query  id=0x{did:02X}  "
                      f"serial={SERIAL!r}  challenge={ch.hex(' ')}")

    def _pump_ms(self, ms: int):
        """Sleep while still servicing CoreMIDI (so Logic traffic isn't stalled)."""
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            M._pump(0.02)

    def send_bank(self, direction: str, count: int = 1):
        """Ask Logic to move the MCU eight-strip bank left or right."""
        note = {"left": MCU_BANK_LEFT_NOTE, "right": MCU_BANK_RIGHT_NOTE}.get(direction)
        if note is None or count < 1:
            raise ValueError("usage: bank <left|right|home> [count]")
        self._logic_led_state.clear()
        for strip in range(1, 9):
            for kind in ("mute", "solo", "rec"):
                hw = hardware_led_note(kind, strip)
                if hw is not None:
                    self.send_to_mix(bytes([0x90, hw, 0]), log=False)
        for _ in range(count):
            for msg in mcu_button_press(note):
                self.emit(msg, f"bank {direction}")
            self._pump_ms(30)
        self._reset_soft_takeover()
        self.log(f"banked {direction} ×{count}")

    def send_bank_home(self):
        """Saturate Bank Left so Logic lands on its first eight-strip bank."""
        self.send_bank("left", MCU_HOME_BANK_PRESSES)
        self.log("bank home requested — faders should now address Logic's first bank")

    def status_line(self) -> str:
        mix_values = ",".join(f"{strip}:{value}" for strip, value in
                              sorted(self._mix_last_value.items())) or "none"
        mix = (f"MIDI Mix faders={self._mix_msg_count} last=[{mix_values}]"
               if self.mix_connected else "MIDI Mix not connected")
        takeover = "soft" if self.soft_takeover_enabled else "absolute"
        knobs = self._knob_layout
        common = f"{mix}  master=fixed  faders={takeover}  knobs={knobs}"
        if self.connected:
            return (f"CONNECTED as 0x{self.connected_id:02X}  "
                    f"host msgs={self.host_msg_count}  {common}")
        if self.host_msg_count > 0:
            return (f"ONLINE (no formal handshake yet)  "
                    f"host msgs={self.host_msg_count}  "
                    f"fader-fb strips={sorted(self.host_faders)}  {common}")
        return f"WAITING for Logic  host msgs=0  {common}"

    # -- from Logic --------------------------------------------------------

    def _dest_callback(self, pkt_list, _src, _ref):
        """CoreMIDI callback: copy packets only; main loop owns bridge state."""
        try:
            for msg in M._iter_packets(pkt_list):
                if msg and not self._closing:
                    self._incoming.put(("host", time.monotonic(), bytes(msg)))
        except Exception as exc:  # noqa: BLE001
            self.log(f"callback error: {exc!r}")

    def _mix_callback(self, pkt_list, _src, _ref):
        """CoreMIDI callback: copy packets only; main loop owns bridge state."""
        try:
            for msg in M._iter_packets(pkt_list):
                if msg and not self._closing:
                    self._incoming.put(("mix", time.monotonic(), bytes(msg)))
        except Exception as exc:  # noqa: BLE001
            self.log(f"MIDI Mix callback error: {exc!r}")

    def service_incoming(self):
        """Drain copied CoreMIDI messages on the main thread."""
        while True:
            try:
                origin, received_at, msg = self._incoming.get_nowait()
            except queue.Empty:
                break
            if origin == "host":
                self._handle_from_host(msg)
            else:
                self._handle_from_mix(received_at, msg)
        self._flush_send_all_pending(time.monotonic())

    def _flush_send_all_pending(self, now: float, force: bool = False):
        if not self._send_all_pending:
            return
        first_at = self._send_all_pending[0][0]
        if not force and now - first_at < SEND_ALL_WINDOW_SECS:
            return
        pending, self._send_all_pending = self._send_all_pending, []
        for _received_at, msg in pending:
            self._route_mix_message(msg)

    def _handle_from_mix(self, received_at: float, msg: bytes):
        """Coalesce SEND ALL's known snapshot before routing physical input."""
        is_candidate = (
            len(msg) >= 3
            and msg[0] == 0xB0
            and msg[1] in SEND_ALL_BURST_CCS
        )
        if not is_candidate:
            self._flush_send_all_pending(received_at, force=True)
            self._route_mix_message(msg)
            return

        if self._send_all_pending:
            first_at = self._send_all_pending[0][0]
            seen = {pending[1][1] for pending in self._send_all_pending}
            if (received_at - first_at > SEND_ALL_WINDOW_SECS
                    or msg[1] in seen):
                self._flush_send_all_pending(received_at, force=True)

        self._send_all_pending.append((received_at, msg))
        seen = {pending[1][1] for pending in self._send_all_pending}
        if seen == SEND_ALL_BURST_CCS:
            # Preserve absolute knob baselines, but never forward the snapshot.
            for _stamp, pending in self._send_all_pending:
                knob = parse_mgb_knob(pending)
                if knob is not None:
                    row, strip, value = knob
                    self._knob_last[(row, strip)] = value
            self._send_all_pending.clear()
            self.log("SEND ALL snapshot ignored (protected knobs and fixed Master)")

    def _route_mix_message(self, msg: bytes):
        """Translate one physical MIDI Mix message."""
        if (len(msg) >= 3 and (msg[0] & 0xF0) in (0x90, 0x80)
                and msg[1] in MGB_BANK_BUTTON_NOTES):
            self.log(f"← MIDI Mix  {msg.hex(' ')}  [bank]")
        event = parse_mgb_fader(msg)
        if event is not None:
            self.forward_midi_mix_fader(*event)
            return
        bank = parse_mgb_bank_button(msg)
        if bank is not None:
            direction, pressed = bank
            if pressed:
                self.send_bank(direction)
            return
        btn = parse_mgb_channel_button(msg)
        if btn is not None:
            self.forward_channel_button(*btn)
            return
        knob = parse_mgb_knob(msg)
        if knob is not None:
            self.forward_knob(*knob)
            return
        # Firmware SOLO key (Note 27): rising edge toggles software solo mode.
        if (len(msg) >= 3 and (msg[0] & 0x0F) == 0
                and msg[1] == MGB_SOLO_BUTTON_NOTE
                and (msg[0] & 0xF0) in (0x90, 0x80)):
            pressed = (msg[0] & 0xF0) == 0x90 and msg[2] != 0
            self.handle_solo_key(pressed)

    def handle_solo_key(self, pressed: bool):
        """SOLO Note 27: latch on press (toggle), ignore auto-repeat while held."""
        if pressed and not self._solo_key_down:
            self.solo_mode_latched = not self.solo_mode_latched
            state = "ON" if self.solo_mode_latched else "OFF"
            self.log(f"*** SOLO mode {state} (tap toggle) — "
                     f"MUTE buttons now send "
                     f"{'SOLO' if self.solo_mode_latched else 'MUTE'} ***")
            # A press can straddle a layer change; forget edge state so its
            # eventual release cannot suppress the next valid press.
            self._btn_state.clear()
            self._refresh_solo_mode_leds()
        self._solo_key_down = pressed

    def _refresh_solo_mode_leds(self):
        """Clear both panel layers, then repaint Logic's cached state."""
        for strip in range(1, 9):
            for kind in ("mute", "solo"):
                hw = hardware_led_note(kind, strip)
                if hw is not None:
                    self.send_to_mix(bytes([0x90, hw, 0]), log=False)
        for strip in range(1, 9):
            if self.solo_mode_latched:
                self._paint_led_to_mix(
                    "solo", strip, self._logic_led_state.get(("solo", strip), False))
            else:
                self._paint_led_to_mix(
                    "mute", strip, self._logic_led_state.get(("mute", strip), False))
                self._paint_led_to_mix(
                    "solo", strip, self._logic_led_state.get(("solo", strip), False))

    def forward_channel_button(self, kind: str, strip: int, pressed: bool):
        """MUTE / REC / SOLO-layer CC → MCU channel-strip button notes.

        When software SOLO mode is latched, physical MUTE CCs are treated as
        SOLO (so you need not hold the SOLO key). Hardware SOLO+MUTE layer CCs
        (41–48) always map to solo regardless.
        """
        effective = "solo" if (kind == "mute" and self.solo_mode_latched) else kind
        # Edge-detect on the *incoming* control (mute vs solo-layer CC vs rec).
        key_in = (kind, strip)
        prev = self._btn_state.get(key_in)
        if prev is pressed:
            return
        self._btn_state[key_in] = pressed

        note = mcu_channel_button_note(effective, strip)
        label = f"{effective} strip {strip}"
        if effective != kind:
            label += " (MUTE key, solo mode)"
        if pressed:
            self.emit(bytes([0x90, note, 127]), f"{label} down")
        else:
            self.emit(bytes([0x90, note, 0]), f"{label} up", log=False)
            self.emit(bytes([0x80, note, 0]), f"{label} up")

    def forward_led_to_mix(self, kind: str, strip: int, on: bool):
        """Logic MCU LED note → physical MIDI Mix lamp (base-3 map).

        In software SOLO mode, solo state is painted on the *mute* lamp notes
        so the mute-row LEDs show solo without holding SOLO. Mute LEDs are
        suppressed in that mode so the two don't fight over the same lamps.
        """
        self._logic_led_state[(kind, strip)] = on
        self._paint_led_to_mix(kind, strip, on)

    def _paint_led_to_mix(self, kind: str, strip: int, on: bool):
        paint_kind = kind
        if self.solo_mode_latched:
            if kind == "mute":
                return
            if kind == "solo":
                paint_kind = "mute"  # solo status → mute-row lamps
        hw = hardware_led_note(paint_kind, strip)
        if hw is None:
            return
        vel = 127 if on else 0
        self.send_to_mix(bytes([0x90, hw, vel]),
                         f"LED {kind} {strip} → note {hw} "
                         f"{'on' if on else 'off'}"
                         + (" [solo mode→mute lamp]" if paint_kind != kind else ""),
                         log=not self.quiet)

    def _reset_soft_takeover(self):
        """Re-engage soft takeover on all faders (call after bank change)."""
        if self._soft_takeover:
            self.log("soft-takeover reset (bank changed)")
        self._soft_takeover.clear()

    def set_knob_layout(self, layout: str, save: bool = False):
        if layout not in KNOB_LAYOUTS:
            raise ValueError(f"unknown knob layout {layout!r}")
        self._knob_layout = layout
        self._knob_last.clear()
        if save:
            with open(KNOB_LAYOUT_PATH, "w") as fh:
                fh.write(layout + "\n")

    def forward_knob(self, row: int, strip: int, value: int):
        """Route a physical knob according to the selected knob layout."""
        if self._knob_layout == "disabled":
            return

        if self._knob_layout == "fixed":
            # Separate absolute addresses let Logic learn any selected parameter.
            # They deliberately remain tied to that learned target; Controller
            # Assignments do not follow the MCU fader bank.
            self.emit_fixed_cc(KNOB_FIXED_CC[(row, strip)], value,
                               label=f"fixed knob row {row} strip {strip}")
            return

        if self._knob_layout == "vpot" and row != 1:
            # A real Mackie Control has eight V-Pots. Keeping just the top
            # physical row live makes this manual compatibility mode legible.
            return

        # V-Pot mode preserves a manually selected shared MCU parameter.
        key = (row, strip)
        prev = self._knob_last.get(key)
        self._knob_last[key] = value
        if prev is None:
            return
        delta = value - prev
        for msg in vpot_relative(strip, delta):
            self.emit(msg, log=False)

    def forward_midi_mix_fader(self, strip: int, value_7bit: int):
        """Forward a physical fader with optional soft takeover."""
        if strip == 9:
            self.emit_fixed_master(value_7bit)
            self._mix_msg_count += 1
            self._mix_last_value[strip] = value_7bit
            return
        target_strip = strip

        if self.soft_takeover_enabled:
            host_val = self.host_faders.get(target_strip)
            if host_val is not None:
                host_7bit = int(round(host_val * 127))
                prev = self._phys_fader_last.get(strip)
                if not self._soft_takeover.get(strip):
                    if _crosses(prev, value_7bit, host_7bit):
                        self._soft_takeover[strip] = True
                        self.log(f"soft-takeover strip {strip}: caught at {value_7bit}")
                    else:
                        self._phys_fader_last[strip] = value_7bit
                        self._mix_msg_count += 1
                        self._mix_last_value[strip] = value_7bit
                        return

        self._phys_fader_last[strip] = value_7bit
        if not self.touchless and target_strip not in self._mix_touches:
            for msg in fader_touch(target_strip, True):
                self.emit(msg, f"MIDI Mix fader {strip} touch DOWN", log=False)
        self.emit(fader_pitch_bend(target_strip, value_7bit), log=False)
        self._phys_fader_sent_at[strip] = time.monotonic()
        self._mix_touches[target_strip] = time.monotonic() + FADER_TOUCH_RELEASE_SECS
        self._mix_msg_count += 1
        self._mix_last_value[strip] = value_7bit

    def release_idle_midi_mix_touches(self):
        """Release touch after the physical fader has been still briefly."""
        if self.touchless:
            self._mix_touches.clear()
            return
        now = time.monotonic()
        idle = [strip for strip, deadline in self._mix_touches.items() if deadline <= now]
        for strip in idle:
            for msg in fader_touch(strip, False):
                self.emit(msg, f"MIDI Mix fader {strip} touch UP", log=False)
            del self._mix_touches[strip]

    def _handle_from_host(self, msg: bytes):
        self.host_msg_count += 1
        parsed = parse_mackie_sysex(msg)
        if parsed is None:
            kind = msg[0] & 0xF0 if msg else 0
            # Meters (channel pressure) fire dozens of times per second while
            # audio plays — that flood is what made the log look broken.
            if kind == 0xD0:
                self._meter_count += 1
                if not self.quiet and self._meter_count % 50 == 1:
                    self.log(f"← host  meters… ({self._meter_count} so far)")
                return
            if kind == 0xE0 and len(msg) >= 3:
                # Logic → surface fader position feedback
                strip = (msg[0] & 0x0F) + 1
                if 1 <= strip <= 9:
                    pb = msg[1] | (msg[2] << 7)
                    new_value = pb / 16383.0
                    previous = self.host_faders.get(strip)
                    self.host_faders[strip] = new_value
                    recently_sent = (
                        time.monotonic() - self._phys_fader_sent_at.get(strip, 0.0)
                        < FADER_TOUCH_RELEASE_SECS + 0.15
                    )
                    changed_elsewhere = (
                        previous is not None
                        and abs(new_value - previous) * 127 > SOFT_TAKEOVER_TOLERANCE
                        and not recently_sent
                    )
                    if (strip <= 8 and self.soft_takeover_enabled
                            and self._soft_takeover.get(strip)
                            and changed_elsewhere):
                        self._soft_takeover.pop(strip, None)
                        self.log(f"soft-takeover strip {strip}: Logic value changed")
                if self.quiet:
                    return
            # Logic → MCU LED notes → physical panel (base-3 map)
            led = parse_mcu_led_note(msg)
            if led is not None:
                self.forward_led_to_mix(*led)
                if self.quiet:
                    return
            if self.quiet and kind in (0x90, 0x80, 0xB0):
                return
            label = {0xE0: "pitchbend/fader-fb", 0x90: "note", 0x80: "note-off",
                     0xB0: "cc"}.get(kind, "other")
            self.log(f"← host  {msg.hex(' ')}  [{label}]")
            return

        device_id, cmd, payload = parsed
        # Logic probes extender and other Mackie-family IDs too. Replying to an
        # extender query makes this one eight-fader surface an XT, and Logic
        # correctly ignores its Bank buttons. Only the base 0x10 owns banking.
        if device_id not in ANNOUNCE_IDS:
            if cmd == CMD_DEVICE_QUERY and not self.quiet:
                self.log(f"ignoring non-base Device Query id=0x{device_id:02X}")
            return
        reply_id = device_id
        self.device_id = reply_id

        # Handshake / version / offline are always logged. Routine config is quiet.
        noisy_config = cmd in (0x0A, 0x0B, 0x0E, 0x12, 0x20, 0x21, 0x10, 0x11, 0x72)

        if not (self.quiet and noisy_config):
            self.log(f"← host  {msg.hex(' ')}  "
                     f"(dev=0x{device_id:02X} cmd=0x{cmd:02X})")

        if cmd == CMD_DEVICE_QUERY:
            self.challenges[reply_id] = make_challenge()
            ch = self.challenges[reply_id]
            self.emit(msg_host_connection_query(ch, reply_id),
                      f"Host Connection Query  id=0x{reply_id:02X}")

        elif cmd == CMD_HOST_CONN_REPLY:
            serial, response = payload[:7], payload[7:11]
            alts = {did: challenge_response(ch)
                    for did, ch in self.challenges.items()}
            algo_ok = response in alts.values()
            matched_id = next((did for did, r in alts.items() if r == response), None)
            self.log(f"  Host Connection Reply  serial={serial!r} "
                     f"algo_match={algo_ok}"
                     + (f" (id 0x{matched_id:02X})" if matched_id else ""))
            self.emit(msg_host_connection_confirm(reply_id),
                      "Host Connection Confirmation")
            self.connected = True
            self.connected_id = reply_id
            self.log("  *** HANDSHAKE OK — surface is live ***")

        elif cmd == CMD_VERSION_REQUEST:
            self.emit(msg_version_reply(reply_id), f"Version Reply {VERSION!r}")

        elif cmd == CMD_TOUCHLESS:
            self.touchless = bool(payload and payload[0])
            self.log(f"  Touchless faders → {self.touchless}")

        elif cmd == CMD_GO_OFFLINE:
            self.log("  Go Offline")
            self.connected = False
            self.connected_id = None

        elif cmd == CMD_RESET:
            self.log("  Reset — re-announcing")
            self.send_connection_query(new_challenge=True, clear_connected=True)

        elif cmd == 0x12 and len(payload) > 1:
            text = bytes(b if 32 <= b < 127 else 0x20 for b in payload[1:1 + 48]).decode("ascii")
            self.log(f"  LCD: {text!r}")
            # LCD from Logic means the surface is live even if we never saw
            # a Host Connection Reply on this boot.
            if not self.connected:
                self.connected = True
                self.connected_id = reply_id
                self.log("  *** surface live (LCD) — ready for fader test ***")

        elif cmd in (0x0A, 0x0B, 0x0E, 0x20, 0x21, 0x10, 0x11, 0x72):
            pass  # routine host config; silence is fine

        else:
            if not self.quiet:
                self.log(f"  unhandled Mackie cmd 0x{cmd:02X}")

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._send_all_pending.clear()
        for strip in list(self._mix_touches):
            for msg in fader_touch(strip, False):
                self.emit(msg, f"MIDI Mix fader {strip} touch UP", log=False)
        self._mix_touches.clear()
        try:
            M._cm.MIDIEndpointDispose(self.source)
            M._cm.MIDIEndpointDispose(self.fixed_source)
            M._cm.MIDIEndpointDispose(self.dest)
            M._cm.MIDIClientDispose(self.client)
        except Exception:  # noqa: BLE001
            pass
        self.log("virtual surface torn down")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_run():
    import signal
    lock_file = _acquire_pid_lock()
    stop = threading.Event()
    surface = None
    previous_handlers = {}

    def _sig(*_):
        stop.set()

    try:
        surface = VirtualMCU()
        surface.send_connection_query(new_challenge=True, clear_connected=True)

        fader_mode = "soft-takeover" if surface.soft_takeover_enabled else "absolute"
        print()
        print("MIDI Mix → Logic mixer bridge is running.")
        print(f"Faders ({fader_mode}), knobs ({surface._knob_layout}),")
        print("fixed Master, BANK, MUTE, REC, SOLO, and panel lamps are active.")
        print("Keep this window open while mixing; type q here when finished.")
        print(f"Logic surface: Input + Output = {PORT_NAME!r}")
        print("If this is a new Logic setup, see README.md for the one-time configuration.")
        print("Commands: status | solo | takeover | knobs | bank home | q")
        print()
        print(f"  {surface.status_line()}")
        print()

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_handlers[sig] = signal.signal(sig, _sig)

        last_announce = time.monotonic()
        last_status = time.monotonic()
        while not stop.is_set():
            M._pump(0.02)
            surface.service_incoming()
            now = time.monotonic()
            surface.release_idle_midi_mix_touches()

            # Re-announce every 5s until we have seen host traffic.
            if surface.host_msg_count == 0 and now - last_announce >= 5.0:
                surface.log("still waiting — re-announcing (is Logic Output = MIDI Mix MCU?)")
                surface.send_connection_query(new_challenge=True)
                last_announce = now
            if now - last_status >= 15.0:
                surface.log(surface.status_line())
                last_status = now

            if sys.stdin.isatty():
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    _handle_cli(surface, line.strip(), stop)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if surface is not None:
            surface.close()
        lock_file.close()
    return 0


def _print_fixed_knob_learn_help():
    """Print the exact fixed-port assignments without blocking the MIDI loop."""
    print("\n  Fixed custom-knob setup (one-time, global Logic assignments)")
    print("  1. In Logic, click the exact parameter you want this knob to control.")
    print("  2. Choose Control Surfaces → Learn Assignment for Selected Parameter.")
    print("  3. Back here, type the matching command below. It emits MIDI Mix Fixed ch16.")
    print("     The physical knob can be moved instead, but these commands make the")
    print("     captured address explicit and avoid accidentally learning a fader.")
    print("\n  Master:  learn master       (CC119; already learned if MASTER works)")
    print("  Knobs:   learn <row> <strip>  (row 1-3; strip 1-8)")
    print("\n  Example: click the desired Track 4 parameter in Logic, arm Learn, then:")
    print("           learn 2 4           (emits ch16 CC14 at a middle value)\n")


def _emit_fixed_learn_value(surface: VirtualMCU, target: str, row: int = None,
                            strip: int = None):
    """Send a deterministic middle value for one Logic Learn capture."""
    if target == "master":
        surface.emit_fixed_master(64)
        print("  emitted MIDI Mix Fixed ch16 CC119 = 64 for Logic Learn")
        return
    cc = KNOB_FIXED_CC[(row, strip)]
    surface.emit_fixed_cc(cc, 64, label=f"learn row {row} strip {strip}")
    print(f"  emitted MIDI Mix Fixed ch16 CC{cc} = 64 "
          f"for row {row}, strip {strip} Learn")


def _handle_cli(surface: VirtualMCU, line: str, stop: threading.Event):
    if not line:
        return
    parts = line.split()
    cmd = parts[0].lower()

    if cmd in ("q", "quit", "exit"):
        stop.set()
        return
    if cmd == "ping":
        surface.send_connection_query(new_challenge=True, clear_connected=False)
        return
    if cmd == "status":
        solo = "ON" if surface.solo_mode_latched else "OFF"
        takeover = "soft" if surface.soft_takeover_enabled else "absolute"
        print(f"  {surface.status_line()}")
        print(f"  solo_mode={solo}  meters={surface._meter_count}  "
              f"faders={takeover}  knobs={surface._knob_layout}")
        return
    if cmd == "solo":
        # solo | solo on | solo off | solo toggle
        arg = parts[1].lower() if len(parts) > 1 else "toggle"
        if arg in ("toggle", "t"):
            surface.solo_mode_latched = not surface.solo_mode_latched
        elif arg in ("on", "1", "true"):
            surface.solo_mode_latched = True
        elif arg in ("off", "0", "false"):
            surface.solo_mode_latched = False
        else:
            print("  usage: solo [on|off|toggle]")
            return
        surface._btn_state.clear()
        surface._refresh_solo_mode_leds()
        print(f"  solo mode → {'ON' if surface.solo_mode_latched else 'OFF'} "
              f"(MUTE keys send {'SOLO' if surface.solo_mode_latched else 'MUTE'})")
        return
    if cmd == "quiet":
        surface.quiet = True
        print("  quiet on (meters/LEDs suppressed)")
        return
    if cmd == "verbose":
        surface.quiet = False
        print("  quiet off (full log)")
        return
    if cmd == "bank":
        direction = parts[1].lower() if len(parts) > 1 else ""
        if direction == "home" and len(parts) == 2:
            surface.send_bank_home()
        else:
            print("  usage: bank home")
        return
    if cmd == "takeover":
        arg = parts[1].lower() if len(parts) > 1 else "toggle"
        if arg in ("toggle", "t"):
            surface.soft_takeover_enabled = not surface.soft_takeover_enabled
        elif arg in ("on", "1"):
            surface.soft_takeover_enabled = True
        elif arg in ("off", "0"):
            surface.soft_takeover_enabled = False
            surface._soft_takeover.clear()
        else:
            print("  usage: takeover [on|off|toggle]")
            return
        state = "ON" if surface.soft_takeover_enabled else "OFF (absolute)"
        print(f"  soft-takeover → {state}")
        try:
            with open(SOFT_TAKEOVER_PATH, "w") as fh:
                fh.write("on\n" if surface.soft_takeover_enabled else "off\n")
        except OSError as exc:
            print(f"  warning: setting changed for this run but was not saved: {exc}")
        return
    if cmd == "knobs":
        arg = parts[1].lower() if len(parts) > 1 else ""
        if arg in KNOB_LAYOUTS:
            saved = True
            try:
                surface.set_knob_layout(arg, save=True)
            except OSError as exc:
                saved = False
                surface.set_knob_layout(arg, save=False)
                print(f"  warning: layout changed for this run but was not saved: {exc}")
            meaning = {
                "fixed": "24 stable custom-learn CCs through MIDI Mix Fixed (nonbanked)",
                "vpot": "one native MCU parameter across the current bank (no learns)",
                "disabled": "knobs off",
            }[arg]
            scope = "saved" if saved else "this run only"
            print(f"  knob layout → {arg} ({scope}): {meaning}")
        else:
            print(f"  layout: {surface._knob_layout}")
            print(f"  knobs <{'|'.join(KNOB_LAYOUTS)}>  — choose layout")
        return
    if cmd == "learn":
        if len(parts) == 1:
            _print_fixed_knob_learn_help()
            return
        if len(parts) == 2 and parts[1].lower() == "master":
            _emit_fixed_learn_value(surface, "master")
            return
        if len(parts) == 3:
            try:
                row, strip = int(parts[1]), int(parts[2])
                if not (1 <= row <= 3 and 1 <= strip <= 8):
                    raise ValueError
            except ValueError:
                print("  usage: learn <row 1-3> <strip 1-8>  |  learn master")
                return
            _emit_fixed_learn_value(surface, "knob", row, strip)
            return
        print("  usage: learn [master | <row 1-3> <strip 1-8>]")
        return
    if cmd == "help":
        print("  status | solo [on|off|toggle] | takeover [on|off|toggle]")
        print(f"  knobs [{'|'.join(KNOB_LAYOUTS)}] | learn [master|<row> <strip>]")
        print("  bank home | ping | quiet | verbose | q")
        return
    print(f"  unknown command {line!r}  (try: help)")


def cmd_selfcheck():
    failures = []

    def check(name, cond, detail=""):
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(name)

    print("challenge-response algorithm")
    c = bytes([0x01, 0x02, 0x03, 0x04])
    r = challenge_response(c)
    check("vector 01 02 03 04", r == bytes([0x05, 0x05, 0x7B, 0x2F]), r.hex(" "))

    print("\nsysex builders")
    ch = make_challenge()
    q = msg_host_connection_query(ch, DEVICE_ID_LC)
    check("query length 18", len(q) == 18)
    check("query header base Logic Control", q[:6] ==
          bytes([0xF0, 0x00, 0x00, 0x66, 0x10, 0x01]))
    check("only base identity is announced", ANNOUNCE_IDS == (DEVICE_ID_LC,))

    print("\nfader messages")
    check("pb strip1 @0", fader_pitch_bend(1, 0) == bytes([0xE0, 0x00, 0x00]))
    check("pb strip1 @127", fader_pitch_bend(1, 127) == bytes([0xE0, 0x7F, 0x7F]))
    check("touch down note 104", fader_touch(1, True) == [bytes([0x90, 104, 127])])
    check("touch up has note-off", fader_touch(1, False)[1] == bytes([0x80, 104, 0]))
    check("master touch note 112", fader_touch(9, True)[0][1] == 112)
    check("bank left is MCU note 46", mcu_button_press(MCU_BANK_LEFT_NOTE) ==
          [bytes([0x90, 46, 127]), bytes([0x80, 46, 0])])
    check("bank right is MCU note 47", mcu_button_press(MCU_BANK_RIGHT_NOTE) ==
          [bytes([0x90, 47, 127]), bytes([0x80, 47, 0])])

    print("\nMIDI Mix mGB fader routing")
    check("CC61 maps to strip 1", parse_mgb_fader(bytes([0xB0, 61, 77])) == (1, 77))
    check("CC69 maps to master", parse_mgb_fader(bytes([0xB0, 69, 12])) == (9, 12))
    check("other channel ignored", parse_mgb_fader(bytes([0xB1, 61, 77])) is None)
    check("knob CC ignored", parse_mgb_fader(bytes([0xB0, 21, 77])) is None)
    check("Note25 is physical bank left", parse_mgb_bank_button(bytes([0x90, 25, 127])) ==
          ("left", True))
    check("Note26 release is bank right up", parse_mgb_bank_button(bytes([0x80, 26, 127])) ==
          ("right", False))
    check("CC75 is not a bank button", parse_mgb_bank_button(bytes([0xB0, 75, 127])) is None)
    check("fixed master uses isolated CC119", (FIXED_MASTER_STATUS, FIXED_MASTER_CC) ==
          (0xBF, 119))

    print("\nchannel buttons + LED map")
    check("MUTE1 CC31 down", parse_mgb_channel_button(bytes([0xB0, 31, 127])) ==
          ("mute", 1, True))
    check("MUTE8 CC38 up", parse_mgb_channel_button(bytes([0xB0, 38, 0])) ==
          ("mute", 8, False))
    check("REC3 CC53 down", parse_mgb_channel_button(bytes([0xB0, 53, 127])) ==
          ("rec", 3, True))
    check("SOLO+MUTE layer strip2", parse_mgb_channel_button(bytes([0xB0, 42, 127])) ==
          ("solo", 2, True))
    check("knob not a channel button", parse_mgb_channel_button(bytes([0xB0, 1, 64])) is None)
    check("MCU mute strip1 note 16", mcu_channel_button_note("mute", 1) == 16)
    check("MCU solo strip8 note 15", mcu_channel_button_note("solo", 8) == 15)
    check("MCU rec strip1 note 0", mcu_channel_button_note("rec", 1) == 0)
    check("LED mute1 note 1", hardware_led_note("mute", 1) == 1)
    check("LED solo3 note 8", hardware_led_note("solo", 3) == 8)
    check("LED rec7 note 21", hardware_led_note("rec", 7) == 21)
    check("LED rec8 is note 24 (base-3 extension)", hardware_led_note("rec", 8) == 24)
    check("parse MCU LED mute3 on", parse_mcu_led_note(bytes([0x90, 18, 127])) ==
          ("mute", 3, True))
    check("parse MCU LED rec1 off", parse_mcu_led_note(bytes([0x80, 0, 0])) ==
          ("rec", 1, False))

    print("\nknob parsing + V-Pot encoding")
    check("row1 CC1 strip1", parse_mgb_knob(bytes([0xB0, 1, 64])) == (1, 1, 64))
    check("row2 CC18 strip8", parse_mgb_knob(bytes([0xB0, 18, 100])) == (2, 8, 100))
    check("row3 CC71 strip1", parse_mgb_knob(bytes([0xB0, 71, 0])) == (3, 1, 0))
    check("row3 CC78 strip8", parse_mgb_knob(bytes([0xB0, 78, 127])) == (3, 8, 127))
    check("fader CC not a knob", parse_mgb_knob(bytes([0xB0, 61, 64])) is None)
    check("vpot cw +3 uses three safe ticks",
          vpot_relative(1, 3) == [bytes([0xB0, 0x10, 0x01])] * 3)
    check("vpot ccw is capped at four safe ticks",
          vpot_relative(1, -5) == [bytes([0xB0, 0x10, 0x41])] * 4)
    check("vpot zero is empty", vpot_relative(1, 0) == [])
    check("vpot strip8", vpot_relative(8, 1) == [bytes([0xB0, 0x17, 0x01])])
    check("fixed map has 24 controls", len(KNOB_FIXED_CC) == 24)
    check("fixed row1 strip1 is CC1", KNOB_FIXED_CC[(1, 1)] == 1)
    check("fixed row2 strip8 is CC18", KNOB_FIXED_CC[(2, 8)] == 18)
    check("fixed row3 strip1 is CC71", KNOB_FIXED_CC[(3, 1)] == 71)
    check("fixed map excludes master CC119", FIXED_MASTER_CC not in KNOB_FIXED_CC.values())

    print("\nSEND ALL protection")
    protected = VirtualMCU.__new__(VirtualMCU)
    protected._send_all_pending = []
    protected._knob_last = {}
    protected.log = lambda _text: None
    routed = []
    protected._route_mix_message = lambda msg: routed.append(msg)
    base = time.monotonic()
    for index, cc in enumerate(SEND_ALL_BURST_CCS):
        protected._handle_from_mix(base + index * 0.001, bytes([0xB0, cc, 64]))
    check("SEND ALL burst is suppressed", routed == [] and protected._send_all_pending == [])
    check("SEND ALL never forwards Master", not any(msg[1] == 69 for msg in routed))

    print("\nknob layout state reset + LED cache")
    stateful = VirtualMCU.__new__(VirtualMCU)
    stateful._knob_layout = "vpot"
    stateful._knob_last = {(1, 1): 64}
    stateful.set_knob_layout("fixed")
    check("layout reset clears knob baselines", stateful._knob_last == {})

    lamps = VirtualMCU.__new__(VirtualMCU)
    lamps._logic_led_state = {}
    lamps.solo_mode_latched = False
    lamps.quiet = True
    lamp_messages = []
    lamps.send_to_mix = lambda msg, note="", log=False: lamp_messages.append(msg)
    lamps.forward_led_to_mix("mute", 1, True)
    check("Logic LED state is cached", lamps._logic_led_state[("mute", 1)] is True)
    check("mute1 paints physical note1", lamp_messages[-1] == bytes([0x90, 1, 127]))

    print("\nsoft-takeover crossing")
    check("at target", _crosses(50, 80, 80))
    check("within tolerance", _crosses(50, 79, 80))
    check("crossed upward", _crosses(70, 85, 80))
    check("crossed downward", _crosses(90, 75, 80))
    check("not crossed", not _crosses(50, 60, 80))
    check("no prev, not at target", not _crosses(None, 60, 80))

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("PASS: offline protocol selfcheck")
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if len(argv) >= 2 else 2
    cmd = argv[1]
    if cmd == "run" and len(argv) == 2:
        return cmd_run()
    if cmd == "selfcheck" and len(argv) == 2:
        return cmd_selfcheck()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
