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

`dd` is 0x14 (Mackie Control) or 0x10 (Logic Control). Logic's Install UI uses
the Logic Control *module* for both models, so we announce on both IDs.

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
DEVICE_ID_MCU = 0x14          # Mackie Control Universal
DEVICE_ID_LC = 0x10           # Emagic Logic Control
ANNOUNCE_IDS = (DEVICE_ID_MCU, DEVICE_ID_LC)
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
        self.device_id = DEVICE_ID_MCU  # last id Logic spoke to
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

        self._on_dest_read = M.READ_PROC(self._dest_callback)

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

        self.dest = M.Ref()
        err = M._cm.MIDIDestinationCreate(
            self.client, M._cfstr(name), self._on_dest_read, None,
            ctypes.byref(self.dest))
        if err:
            raise SystemExit(f"MIDIDestinationCreate({name!r}) failed: {err}")

        self.log(f"virtual surface up: {name!r}  (announcing as MCU 0x14 and LC 0x10)")
        self.log("delete any Control Surface that still points at the real 'MIDI Mix'")

    def log(self, text: str):
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    def emit(self, msg: bytes, note: str = ""):
        err = M._cm.MIDIReceived(self.source, M._packet_list(msg))
        if err:
            self.log(f"MIDIReceived failed ({err}): {msg.hex(' ')}")
            return
        tag = f"  ({note})" if note else ""
        self.log(f"→ host  {msg.hex(' ')}{tag}")

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

    def status_line(self) -> str:
        if self.connected:
            return (f"CONNECTED as 0x{self.connected_id:02X}  "
                    f"host msgs={self.host_msg_count}  touchless={self.touchless}")
        if self.host_msg_count > 0:
            # Logic often streams LCD/meters before (or without) a formal
            # Host Connection Reply — still online enough to move faders.
            return (f"ONLINE (no formal handshake yet)  "
                    f"host msgs={self.host_msg_count}  "
                    f"fader-fb strips={sorted(self.host_faders)}  "
                    f"touchless={self.touchless}")
        return ("WAITING for Logic  host msgs=0  "
                "(Logic Output port is not our dest)")

    # -- from Logic --------------------------------------------------------

    def _dest_callback(self, pkt_list, _src, _ref):
        try:
            for msg in M._iter_packets(pkt_list):
                if msg:
                    self._handle_from_host(msg)
        except Exception as exc:  # noqa: BLE001
            self.log(f"callback error: {exc!r}")

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
        # Always reply on the device id Logic addressed — it scans 0x10/11/14/15/17.
        reply_id = device_id
        self.device_id = reply_id if device_id in ANNOUNCE_IDS else self.device_id

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
    print("    6. Move a fader — either type here, OR from another terminal:")
    print(f"         echo 'f 1 100' > {_ROOT}/.mcu_cmd")
    print()
    print("  Verified earlier: Logic completed handshake (algo match) and sent")
    print("  fader feedback + LCD names. The missing piece was only our outbound")
    print("  fader test not reaching the live process.")
    print()
    print("  commands: f <1-9> <0-127> | sweep | ping | status | q")
    print("=" * 64)
    print()
    print(f"  {surface.status_line()}")
    print()

    import signal
    stop = []
    last_announce = time.monotonic()
    last_status = time.monotonic()
    auto_fader_sent = False

    def _sig(*_):
        stop.append(True)

    prev = signal.signal(signal.SIGINT, _sig)
    try:
        while not stop:
            M._pump(0.1)
            now = time.monotonic()
            _drain_cmd_file(surface, stop)

            # Re-announce every 5s until we have seen host traffic.
            if surface.host_msg_count == 0 and now - last_announce >= 5.0:
                surface.log("still waiting — re-announcing (is Logic Output = MIDI Mix MCU?)")
                surface.send_connection_query(new_challenge=True)
                last_announce = now
            if now - last_status >= 15.0:
                surface.log(surface.status_line())
                last_status = now

            # Wait until handshake is done AND Logic has pushed fader feedback
            # (surface fully online), then run a dramatic volume test.
            if (not auto_fader_sent and surface.connected
                    and len(surface.host_faders) >= 1
                    and surface.host_msg_count >= 30):
                surface._pump_ms(500)  # let Logic settle after handshake
                surface.send_fader_test(1)
                auto_fader_sent = True

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
        print("  f <strip 1-9> <0-127> | test [strip] | sweep | ping | status | quiet | verbose | q")
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
    q = msg_host_connection_query(ch, DEVICE_ID_MCU)
    check("query length 18", len(q) == 18)
    check("query header MCU", q[:6] == bytes([0xF0, 0x00, 0x00, 0x66, 0x14, 0x01]))
    qlc = msg_host_connection_query(ch, DEVICE_ID_LC)
    check("query header LC", qlc[4] == 0x10)

    print("\nfader messages")
    check("pb strip1 @0", fader_pitch_bend(1, 0) == bytes([0xE0, 0x00, 0x00]))
    check("pb strip1 @127", fader_pitch_bend(1, 127) == bytes([0xE0, 0x7F, 0x7F]))
    check("touch down note 104", fader_touch(1, True) == [bytes([0x90, 104, 127])])
    check("touch up has note-off", fader_touch(1, False)[1] == bytes([0x80, 104, 0]))
    check("master touch note 112", fader_touch(9, True)[0][1] == 112)

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
