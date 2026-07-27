#!/usr/bin/env python3
"""Phase 1: virtual Mackie Control surface for Logic Pro.

Creates a CoreMIDI source+destination pair named "MIDI Mix MCU" that speaks
the Mackie / Logic Control handshake and can emit MCU fader messages.

Handshake (device side — TouchMCU protocol notes + Ardour host code)
-------------------------------------------------------------------
    host  ->  F0 00 00 66 dd 00 F7                          Device Query
    device->  F0 00 00 66 dd 01 <7 serial> <4 challenge> F7 Host Connection Query
    host  ->  F0 00 00 66 dd 02 <7 serial> <4 response>  F7 Host Connection Reply
    device->  F0 00 00 66 dd 03 <7 serial> F7               Host Connection Confirmation
    host  ->  F0 00 00 66 dd 13 00 F7                       Version Request (optional)
    device->  F0 00 00 66 dd 14 <5 version> F7              Version Reply

Logic probes several identities on a new port. This bridge answers only as the
base Logic Control (`dd = 0x10`): answering `0x11` creates a Logic Control XT
extender, whose faders work but whose bank buttons do not own navigation.

Faders are 14-bit Pitch Bend (ch 1-8 = strips, ch 9 = master). Logic's default
is touch-sensitive: we send Note On 104-112 (touch) around each move.

Usage
-----
    ./mixer-probe                         # or: python3 tools/mcu_surface.py run
    python3 tools/mcu_surface.py selfcheck

While running, type:
    f 1 100     strip-1 fader → 100/127  (sends touch + pitch bend)
    f 9 64      master
    sweep       walk all 9 faders
    ping        re-announce both device IDs
    status      connection state
    q           quit

Logic setup (critical order)
----------------------------
1. Start ./mixer-probe FIRST (ports must exist before Install).
2. Delete any auto-installed "Logic Control" that points at the real
   "MIDI Mix" hardware — that only sees CCs and will confuse things.
3. Control Surfaces → Setup → New → Install → Mackie Designs →
   Mackie Control → Add.
4. Set Input AND Output to "MIDI Mix MCU" (exactly one of each).
5. Close the Setup window (surfaces often only go fully online after).
6. Open a project with real tracks. Channel Strip Track should become a
   normal number (1, 2, …) — NOT 262150.
7. In the probe: f 1 100
"""

from __future__ import annotations

import atexit
import ctypes
import os
import select
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midimix as M  # noqa: E402

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
# Second terminal can inject commands while run is up:
#   echo "f 1 100" > .mcu_cmd
CMD_PATH = os.path.join(_ROOT, ".mcu_cmd")

CMD_DEVICE_QUERY = 0x00
CMD_HOST_CONN_QUERY = 0x01
CMD_HOST_CONN_REPLY = 0x02
CMD_HOST_CONN_CONFIRM = 0x03
CMD_HOST_CONN_ERROR = 0x04
CMD_TOUCHLESS = 0x0C
CMD_VERSION_REQUEST = 0x13
CMD_VERSION_REPLY = 0x14
CMD_GO_OFFLINE = 0x0F
CMD_RESET = 0x63

# Fader touch notes (ch 1): strip1=104 … strip8=111, master=112
TOUCH_NOTE_BASE = 104

# The current mgb70 preset leaves the fixed panel buttons on their firmware
# notes: BANK LEFT=25, BANK RIGHT=26, SOLO=27. Its third knob row was moved to
# CC71..78, so the fixed buttons cannot collide with it.
# Its nine faders remain channel 1 (wire channel 0), CC61 through CC69.
MGB_FADER_CCS = {61 + i: i + 1 for i in range(9)}
MGB_BANK_BUTTON_NOTES = {25: "left", 26: "right"}
FADER_TOUCH_RELEASE_SECS = 0.18

# Logic currently maps MCU strip 8 to its Stereo Out, but does not act on the
# dedicated MCU master-fader lane (strip 9). Keep the physical MASTER useful by
# routing it to that proven Stereo Out lane. This is deliberately a constant:
# banking can later choose whether it follows the MCU bank or gets a dedicated
# fixed-output route.
PHYSICAL_MASTER_TARGET_STRIP = 8

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


def msg_host_connection_error(device_id: int) -> bytes:
    return sysex(device_id, CMD_HOST_CONN_ERROR, SERIAL)


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
    """Return ``(direction, pressed)`` for mgb70's fixed bank buttons.

    These hardware buttons are firmware-fixed Note 25/26. In the original mGB
    preset those note numbers were easily confused with knob CC25/26; mgb70
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


def mcu_button_press(note: int) -> list:
    """Return a complete press/release for an MCU button on channel 1."""
    if not 0 <= note <= 127:
        raise ValueError(f"MCU note must be 0..127, got {note}")
    return [bytes([0x90, note, 127]), bytes([0x80, note, 0])]


# --------------------------------------------------------------------------
# single-instance lock
# --------------------------------------------------------------------------

def _acquire_pid_lock():
    """Refuse to start a second probe — duplicate 'MIDI Mix MCU' ports break Logic."""
    if os.path.exists(PID_PATH):
        try:
            old = int(open(PID_PATH).read().strip())
            os.kill(old, 0)  # raises if dead
            raise SystemExit(
                f"another mcu_surface is already running (pid {old}).\n"
                f"Kill it first:  kill {old}\n"
                f"Or:  pkill -f mcu_surface.py\n"
                f"Duplicate ports with the same name make Logic bind to the wrong one.")
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale pid file
    with open(PID_PATH, "w") as fh:
        fh.write(str(os.getpid()))

    def _clear():
        try:
            if os.path.exists(PID_PATH) and open(PID_PATH).read().strip() == str(os.getpid()):
                os.remove(PID_PATH)
        except OSError:
            pass

    atexit.register(_clear)


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
        # Last fader positions Logic sent us (0..1), keyed by strip 1..9
        self.host_faders = {}
        self._lock = threading.Lock()
        self._mix_msg_count = 0
        self._mix_last_value = {}
        self._mix_touches = {}  # strip -> monotonic release deadline
        self.mix_connected = False
        # The one-time Logic assignment on MIDI Mix Fixed is now the permanent
        # Master route. It remains independent of every MCU bank.
        self.master_route = "fixed"

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
        try:
            mix_source = M.find_endpoint("source")
        except SystemExit:
            self.log("real 'MIDI Mix' is not present — virtual probe only")
        else:
            err = M._cm.MIDIInputPortCreate(
                self.client, M._cfstr("MIDI Mix faders"), self._on_mix_read, None,
                ctypes.byref(self.mix_input))
            if err:
                self.log(f"could not listen to real MIDI Mix ({err}) — virtual probe only")
            else:
                err = M._cm.MIDIPortConnectSource(self.mix_input, mix_source, None)
                if err:
                    self.log(f"could not connect real MIDI Mix ({err}) — virtual probe only")
                else:
                    self.mix_connected = True
                    self.log("listening to MIDI Mix: faders ch1 CC61–69; "
                             "banks Note25/26 (mgb70 preset)")

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

    def emit_fixed_master(self, value_7bit: int):
        """Send the stable, learnable master CC on its own virtual MIDI port."""
        msg = bytes([FIXED_MASTER_STATUS, FIXED_MASTER_CC, value_7bit])
        err = M._cm.MIDIReceived(self.fixed_source, M._packet_list(msg))
        if err:
            self.log(f"fixed-master MIDIReceived failed ({err}): {msg.hex(' ')}")

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

    def send_fader(self, strip: int, value_7bit: int, hold_ms: int = 80):
        """Drive one MCU fader. Watch the *volume* fader in Logic's mixer.

        MCU encodes fader position as Pitch Bend on MIDI channel = strip.
        That is wire format only — Logic maps it to channel strip volume,
        not to track pitch-bend automation.
        """
        label = "MASTER" if strip == 9 else f"strip {strip}"
        before = self.host_faders.get(strip)

        # Touch down and hold for the whole move (Logic sent touchless=0).
        if not self.touchless:
            for m in fader_touch(strip, True):
                self.emit(m, f"touch {label} DOWN")
            self._pump_ms(30)

        # Ramp so the move is obvious even if Logic samples sparsely.
        start = int(round((before or 0.0) * 127)) if before is not None else 0
        steps = max(abs(value_7bit - start), 1)
        n = min(steps, 8)
        for i in range(1, n + 1):
            v = start + (value_7bit - start) * i // n
            self.emit(fader_pitch_bend(strip, v),
                      f"fader {label} = {v}/127  (MCU pitch-bend ch{strip})")
            self._pump_ms(15)

        self._pump_ms(hold_ms)

        if not self.touchless:
            for m in fader_touch(strip, False):
                self.emit(m, f"touch {label} UP")
            self._pump_ms(30)

        after = self.host_faders.get(strip)
        if after is not None:
            self.log(f"  Logic fader-fb strip {strip}: "
                     f"before={before!s} after={after:.3f} "
                     f"(target≈{value_7bit / 127:.3f})")
        else:
            self.log(f"  (no fader-fb from Logic yet for strip {strip})")

    def send_fader_test(self, strip: int = 1):
        """Dramatic 0 → 127 → 64 so a volume move is hard to miss."""
        self.log(f"*** FADER TEST strip {strip}: watch VOLUME fader in Logic mixer ***")
        self.log("    (not pitch bend — MCU uses pitch-bend bytes to mean volume)")
        self.send_fader(strip, 0, hold_ms=100)
        self.send_fader(strip, 127, hold_ms=200)
        self.send_fader(strip, 64, hold_ms=100)
        self.log("*** FADER TEST done — did the volume fader jump? ***")

    def sweep_faders(self):
        self.log("sweeping all 9 faders 0 → 127 → 0 …")
        for strip in range(1, 10):
            for v in (0, 64, 127, 0):
                self.send_fader(strip, v, hold_ms=40)

    def send_bank(self, direction: str, count: int = 1):
        """Ask Logic to move the MCU eight-strip bank left or right."""
        note = {"left": MCU_BANK_LEFT_NOTE, "right": MCU_BANK_RIGHT_NOTE}.get(direction)
        if note is None or count < 1:
            raise ValueError("usage: bank <left|right|home> [count]")
        for _ in range(count):
            for msg in mcu_button_press(note):
                self.emit(msg, f"bank {direction}")
            self._pump_ms(30)
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
        master = f"master-route={self.master_route}"
        if self.connected:
            return (f"CONNECTED as 0x{self.connected_id:02X}  "
                    f"host msgs={self.host_msg_count}  {mix}  {master}  touchless={self.touchless}")
        if self.host_msg_count > 0:
            # Logic often streams LCD/meters before (or without) a formal
            # Host Connection Reply — still online enough to move faders.
            return (f"ONLINE (no formal handshake yet)  "
                    f"host msgs={self.host_msg_count}  "
                    f"fader-fb strips={sorted(self.host_faders)}  "
                    f"{mix}  {master}  touchless={self.touchless}")
        return ("WAITING for Logic  host msgs=0  "
                f"{mix}  {master}  (Logic Output port is not our dest)")

    # -- from Logic --------------------------------------------------------

    def _dest_callback(self, pkt_list, _src, _ref):
        try:
            for msg in M._iter_packets(pkt_list):
                if msg:
                    self._handle_from_host(msg)
        except Exception as exc:  # noqa: BLE001
            self.log(f"callback error: {exc!r}")

    def _mix_callback(self, pkt_list, _src, _ref):
        """Translate faders and the collision-free fixed bank buttons."""
        try:
            for msg in M._iter_packets(pkt_list):
                # Keep these two raw diagnostics visible while bringing the
                # physical buttons online.  They are low-rate and make it
                # immediately clear whether the bridge saw the press.
                if len(msg) >= 3 and msg[1] in MGB_BANK_BUTTON_NOTES:
                    self.log(f"← MIDI Mix  {msg.hex(' ')}  [bank candidate]")
                event = parse_mgb_fader(msg)
                if event is not None:
                    self.forward_midi_mix_fader(*event)
                    continue
                bank = parse_mgb_bank_button(msg)
                if bank is not None:
                    direction, pressed = bank
                    # A full MCU press/release is emitted on the physical
                    # press. The MIDI Mix release CC is only confirmation.
                    if pressed:
                        self.send_bank(direction)
        except Exception as exc:  # noqa: BLE001
            self.log(f"MIDI Mix callback error: {exc!r}")

    def forward_midi_mix_fader(self, strip: int, value_7bit: int):
        """Forward a physical fader and hold MCU touch while it is in motion.

        This is direct absolute control for Phase 2. Soft takeover needs Logic
        feedback plus a crossing detector and is intentionally deferred to the
        next phase rather than guessed at here.
        """
        # The fixed port is always emitted. Until the user creates the one-time
        # Logic assignment it is harmless; the temporary MCU mirror below keeps
        # MASTER usable through the current mirror in the pre-assignment layout.
        if strip == 9:
            self.emit_fixed_master(value_7bit)
            if self.master_route == "fixed":
                self._mix_msg_count += 1
                self._mix_last_value[strip] = value_7bit
                return
        target_strip = PHYSICAL_MASTER_TARGET_STRIP if strip == 9 else strip
        with self._lock:
            if not self.touchless and target_strip not in self._mix_touches:
                for msg in fader_touch(target_strip, True):
                    self.emit(msg, f"MIDI Mix fader {strip} touch DOWN", log=False)
            self.emit(fader_pitch_bend(target_strip, value_7bit), log=False)
            self._mix_touches[target_strip] = time.monotonic() + FADER_TOUCH_RELEASE_SECS
            self._mix_msg_count += 1
            self._mix_last_value[strip] = value_7bit

    def release_idle_midi_mix_touches(self):
        """Release touch after the physical fader has been still briefly."""
        if self.touchless:
            self._mix_touches.clear()
            return
        now = time.monotonic()
        with self._lock:
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
                    self.host_faders[strip] = pb / 16383.0
                if self.quiet:
                    return
            if self.quiet and kind in (0x90, 0x80, 0xB0):
                # LED notes + timecode/v-pot CCs: keep quiet after online
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

def _drain_cmd_file(surface: VirtualMCU, stop: list):
    """Read lines from .mcu_cmd (written by a second terminal) and run them."""
    if not os.path.exists(CMD_PATH):
        return
    try:
        with open(CMD_PATH) as fh:
            lines = fh.read().splitlines()
        os.remove(CMD_PATH)
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line:
            surface.log(f"(cmd file) {line}")
            _handle_cli(surface, line, stop)


def cmd_run():
    _acquire_pid_lock()
    # Clear stale command file
    try:
        if os.path.exists(CMD_PATH):
            os.remove(CMD_PATH)
    except OSError:
        pass

    surface = VirtualMCU()
    surface.send_connection_query(new_challenge=True, clear_connected=True)

    print()
    print("=" * 64)
    print("  Phase 1 probe running  (ONE instance only)")
    print(f"  Ports: Input = {PORT_NAME!r}   Output = {PORT_NAME!r}")
    print()
    print("  Logic checklist:")
    print("    1. Delete any surface still using the real 'MIDI Mix' ports")
    print("    2. Install → Mackie Designs → Mackie Control → Add")
    print(f"    3. Input + Output both = {PORT_NAME!r}")
    print("    4. Close the Setup window")
    print("    5. Wait until this log shows HANDSHAKE OK / LCD track names")
    print("    6. Move a physical MIDI Mix fader (mgb70 preset: ch1 CC61–69),")
    print("       or drive a synthetic fader here / from another terminal:")
    print(f"         echo 'f 1 100' > {_ROOT}/.mcu_cmd")
    print(f"  Fixed master port: {FIXED_PORT_NAME!r} sends ch16 CC{FIXED_MASTER_CC}")
    print()
    print("  Logic handshake and synthetic fader testing were verified in Phase 1.")
    print("  This mixer route never moves a Logic fader by itself: it responds only")
    print("  to physical MIDI Mix movement or an explicit test command.")
    print()
    print("  Phase 2 is direct absolute fader control; soft takeover comes next.")
    print("  Physical BANK LEFT/RIGHT use fixed ch1 Note25/26 (mgb70 preset).")
    print("  commands: f <1-9> <0-127> | bank <left|right|home> [count]")
    print("            | master <mirror|fixed> | sweep | ping | status | q")
    print("=" * 64)
    print()
    print(f"  {surface.status_line()}")
    print()

    import signal
    stop = []
    last_announce = time.monotonic()
    last_status = time.monotonic()

    def _sig(*_):
        stop.append(True)

    prev = signal.signal(signal.SIGINT, _sig)
    try:
        while not stop:
            M._pump(0.1)
            now = time.monotonic()
            _drain_cmd_file(surface, stop)
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
        signal.signal(signal.SIGINT, prev)
        surface.close()
    return 0


def _handle_cli(surface: VirtualMCU, line: str, stop: list):
    if not line:
        return
    parts = line.split()
    cmd = parts[0].lower()

    if cmd in ("q", "quit", "exit"):
        stop.append(True)
        return
    if cmd == "ping":
        surface.send_connection_query(new_challenge=True, clear_connected=False)
        return
    if cmd == "status":
        print(f"  {surface.status_line()}  meters={surface._meter_count}")
        return
    if cmd == "quiet":
        surface.quiet = True
        print("  quiet on (meters/LEDs suppressed)")
        return
    if cmd == "verbose":
        surface.quiet = False
        print("  quiet off (full log)")
        return
    if cmd == "sweep":
        surface.sweep_faders()
        return
    if cmd == "bank":
        direction = parts[1].lower() if len(parts) > 1 else ""
        try:
            if direction == "home":
                surface.send_bank_home()
            else:
                count = int(parts[2]) if len(parts) > 2 else 1
                surface.send_bank(direction, count)
        except ValueError as exc:
            print(f"  {exc}")
        return
    if cmd == "master" and len(parts) == 2:
        route = parts[1].lower()
        if route not in ("mirror", "fixed"):
            print("  usage: master <mirror|fixed>")
        else:
            surface.master_route = route
            print(f"  physical MASTER route → {route}")
        return
    if cmd in ("f", "fader") and len(parts) >= 3:
        try:
            surface.send_fader(int(parts[1]), int(parts[2]))
        except ValueError as exc:
            print(f"  usage: f <strip 1-9> <0-127>   ({exc})")
        return
    if cmd == "test":
        strip = int(parts[1]) if len(parts) > 1 else 1
        surface.send_fader_test(strip)
        return
    if cmd == "help":
        print("  f <strip 1-9> <0-127> | test [strip] | sweep | bank <left|right|home> [count]")
        print("  master <mirror|fixed> | ping | status | quiet | verbose | q")
        print("  (fader = volume in Logic mixer; MCU wires it as pitch-bend)")
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

    print("\nvirtual port creation")
    try:
        s = VirtualMCU(name="MIDI Mix MCU selfcheck")
        names_src = [M._obj_name(M._cm.MIDIGetSource(i))
                     for i in range(M._cm.MIDIGetNumberOfSources())]
        names_dst = [M._obj_name(M._cm.MIDIGetDestination(i))
                     for i in range(M._cm.MIDIGetNumberOfDestinations())]
        check("source visible", "MIDI Mix MCU selfcheck" in names_src)
        check("dest visible", "MIDI Mix MCU selfcheck" in names_dst)
        s.send_connection_query()
        s.send_fader(1, 100)
        M._pump(0.2)
        s.close()
        check("create/emit/close", True)
    except SystemExit as exc:
        check("create/emit/close", False, str(exc))

    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("PASS: mcu_surface selfcheck")
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "run":
        return cmd_run()
    if cmd == "selfcheck":
        return cmd_selfcheck()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
