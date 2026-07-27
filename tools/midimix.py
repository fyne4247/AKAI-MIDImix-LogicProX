#!/usr/bin/env python3
"""AKAI MIDI Mix preset + MIDI tool. Native arm64, stdlib only, no Editor app.

Subcommands:
    show <preset.midimix>       decode a preset to a readable table
    mon  [preset.midimix]       live-monitor the device, labelled via a preset
    send <preset.midimix>       flash a preset to the device
    dump [out.midimix]          ask the device for its current config

Preset format (reverse-engineered, verified against two independent presets):

    F0 47 00 31 67 01 0A  <138 payload bytes>  F7
    |  |  |  |  |  |  |
    |  |  |  |  |  `--`-- 7-bit length pair: (0x01 << 7) | 0x0A = 138
    |  |  |  |  `-------- opcode 0x67 = write config
    |  `--`--`----------- Akai / MIDI Mix device id
    `-------------------- SysEx start

    payload = 24 knobs  x 2 bytes (channel, cc)   strip order, 3 per strip
            +  9 faders x 2 bytes (channel, cc)   1-8 then MASTER
            + 24 buttons x 3 bytes (type, channel, cc)

    Channel bytes are 0-based on the wire; this tool prints them 1-based.

    The panel has only 20 physical buttons (8 MUTE + 8 REC ARM + SEND ALL,
    BANK LEFT, BANK RIGHT, SOLO) but the preset stores 24 button records. The
    third row of 8 is the SOLO-shifted MUTE layer: the manual states "press and
    hold Solo, then press the Mute buttons to solo their tracks". That is why
    no button on the panel is labelled with those CCs.
"""

import ctypes
import ctypes.util
import os
import sys
import time

HEADER = bytes([0xF0, 0x47, 0x00, 0x31, 0x67, 0x01, 0x0A])
PAYLOAD_LEN = 138
DEVICE_NAME = "MIDI Mix"

# 0x67 is confirmed -- it is what both known presets use to write config.
# 0x66 is a guess at the paired read opcode. See cmd_dump.
OPCODE_READ_GUESS = 0x66

BUTTON_ROWS = ["MUTE", "REC ARM", "SOLO+MUTE"]


# --------------------------------------------------------------------------
# preset codec
# --------------------------------------------------------------------------

def parse_preset(path):
    data = open(path, "rb").read()
    if data[:7] != HEADER or data[-1] != 0xF7:
        raise SystemExit(f"{path}: not a MIDI Mix preset (header {data[:7].hex(' ')})")
    payload = data[7:-1]
    if len(payload) != PAYLOAD_LEN:
        raise SystemExit(f"{path}: expected {PAYLOAD_LEN} payload bytes, got {len(payload)}")

    knobs = [(payload[i * 2], payload[i * 2 + 1]) for i in range(24)]
    faders = [(payload[48 + i * 2], payload[48 + i * 2 + 1]) for i in range(9)]
    buttons = [tuple(payload[66 + i * 3: 69 + i * 3]) for i in range(24)]
    return knobs, faders, buttons


def build_preset(knobs, faders, buttons):
    out = bytearray(HEADER)
    for ch, cc in knobs:
        out += bytes([ch, cc])
    for ch, cc in faders:
        out += bytes([ch, cc])
    for t, ch, cc in buttons:
        out += bytes([t, ch, cc])
    assert len(out) == 7 + PAYLOAD_LEN, len(out)
    out.append(0xF7)
    return bytes(out)


def control_map(knobs, faders, buttons):
    """(channel, cc) -> label. Channels 0-based here, as on the wire."""
    m = {}
    for i, (ch, cc) in enumerate(knobs):
        m[(ch, cc)] = f"knob row{i % 3 + 1} strip{i // 3 + 1}"
    for i, (ch, cc) in enumerate(faders):
        m[(ch, cc)] = f"fader {'MASTER' if i == 8 else i + 1}"
    for i, (t, ch, cc) in enumerate(buttons):
        m[(ch, cc)] = f"{BUTTON_ROWS[i // 8]} {i % 8 + 1}"
    return m


def channels_used(knobs, faders, buttons):
    return sorted({ch + 1 for ch, _ in knobs + faders} | {b[1] + 1 for b in buttons})


def cmd_show(path):
    knobs, faders, buttons = parse_preset(path)
    print(f"=== {os.path.basename(path)} ===")

    print("\n-- knobs (24), by strip --")
    for s in range(8):
        cells = "  ".join(f"ch{ch + 1:<2} CC{cc:<3}" for ch, cc in knobs[s * 3:s * 3 + 3])
        print(f"  strip {s + 1}:  {cells}")

    print("\n-- faders (9) --")
    cells = "  ".join(
        f"{'MSTR' if i == 8 else i + 1}:ch{ch + 1}/CC{cc}" for i, (ch, cc) in enumerate(faders))
    print(f"  {cells}")

    print("\n-- buttons (24) --")
    for row in range(3):
        rec = buttons[row * 8:row * 8 + 8]
        types = sorted({t for t, _, _ in rec})
        cells = " ".join(f"ch{ch + 1}/CC{cc}" for _, ch, cc in rec)
        print(f"  {BUTTON_ROWS[row]:<10} type={types}  {cells}")

    print(f"\n  MIDI channels used: {channels_used(knobs, faders, buttons)}")


def cmd_diff(a, b):
    """Show whether two presets can coexist -- i.e. share no (channel, CC)."""
    ma = control_map(*parse_preset(a))
    mb = control_map(*parse_preset(b))
    overlap = sorted(set(ma) & set(mb))
    print(f"{os.path.basename(a)}: {len(ma)} controls, channels "
          f"{channels_used(*parse_preset(a))}")
    print(f"{os.path.basename(b)}: {len(mb)} controls, channels "
          f"{channels_used(*parse_preset(b))}")
    if not overlap:
        print("\n  DISJOINT -- no (channel, CC) pair appears in both presets.")
        print("  Assignments learned under one preset can never be triggered")
        print("  by the other. Hot-swapping between them is safe.")
    else:
        print(f"\n  {len(overlap)} COLLISIONS:")
        for ch, cc in overlap:
            print(f"    ch{ch + 1:<2} CC{cc:<3}  {ma[(ch, cc)]:<22} vs {mb[(ch, cc)]}")


# --------------------------------------------------------------------------
# CoreMIDI plumbing
# --------------------------------------------------------------------------

_cm = ctypes.CDLL(ctypes.util.find_library("CoreMIDI")
                  or "/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI")
_cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))

UTF8 = 0x08000100

_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
_cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
_cf.CFRunLoopRunInMode.restype = ctypes.c_int32
_cf.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]

for _fn, _res, _args in [
    ("MIDIGetNumberOfSources", ctypes.c_ulong, []),
    ("MIDIGetSource", ctypes.c_void_p, [ctypes.c_ulong]),
    ("MIDIGetNumberOfDestinations", ctypes.c_ulong, []),
    ("MIDIGetDestination", ctypes.c_void_p, [ctypes.c_ulong]),
]:
    getattr(_cm, _fn).restype = _res
    getattr(_cm, _fn).argtypes = _args

_cm.MIDIObjectGetStringProperty.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_kName = ctypes.c_void_p.in_dll(_cm, "kMIDIPropertyName")

READ_PROC = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


def _cfstr(s):
    return _cf.CFStringCreateWithCString(None, s.encode(), UTF8)


def _obj_name(obj):
    s = ctypes.c_void_p()
    if _cm.MIDIObjectGetStringProperty(obj, _kName, ctypes.byref(s)) != 0:
        return "?"
    buf = ctypes.create_string_buffer(256)
    _cf.CFStringGetCString(s.value, buf, 256, UTF8)
    return buf.value.decode()


def find_endpoint(kind):
    """kind: 'source' (device -> mac) or 'dest' (mac -> device)."""
    if kind == "source":
        n, get = _cm.MIDIGetNumberOfSources(), _cm.MIDIGetSource
    else:
        n, get = _cm.MIDIGetNumberOfDestinations(), _cm.MIDIGetDestination
    names = []
    for i in range(n):
        ep = get(i)
        nm = _obj_name(ep)
        names.append(nm)
        if nm == DEVICE_NAME:
            return ep
    raise SystemExit(
        f"No CoreMIDI {kind} named {DEVICE_NAME!r}. Found: {names or 'nothing'}\n"
        f"Is the device plugged in? The manual requires a POWERED hub -- try a\n"
        f"direct USB port on the Mac.")


def _client(name="midimix.py"):
    ref = ctypes.c_void_p()
    err = _cm.MIDIClientCreate(_cfstr(name), None, None, ctypes.byref(ref))
    if err:
        raise SystemExit(f"MIDIClientCreate failed: {err}")
    return ref


# MIDIPacketList on arm64: numPackets (u32) + 4 bytes padding, packets from
# offset 8. Each packet: timeStamp (u64), length (u16), data[length]. The
# MIDIPacketNext macro 4-byte-aligns successive packets on ARM.
def _iter_packets(pkt_list_ptr):
    base = ctypes.cast(pkt_list_ptr, ctypes.POINTER(ctypes.c_ubyte))
    num = ctypes.cast(pkt_list_ptr, ctypes.POINTER(ctypes.c_uint32))[0]
    off = 8
    for _ in range(min(num, 64)):
        length = ctypes.cast(ctypes.byref(base.contents, off + 8),
                             ctypes.POINTER(ctypes.c_uint16))[0]
        if not 0 < length <= 65535:
            return
        yield bytes(base[off + 10: off + 10 + length])
        off = (off + 10 + length + 3) & ~3


def _packet_list(msg):
    buf = ctypes.create_string_buffer(8 + 10 + len(msg))
    ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))[0] = 1                     # numPackets
    ctypes.cast(ctypes.byref(buf, 8), ctypes.POINTER(ctypes.c_uint64))[0] = 0    # timeStamp
    ctypes.cast(ctypes.byref(buf, 16), ctypes.POINTER(ctypes.c_uint16))[0] = len(msg)
    ctypes.memmove(ctypes.byref(buf, 18), msg, len(msg))
    return buf


def send_raw(msg, quiet=False):
    dest = find_endpoint("dest")
    port = ctypes.c_void_p()
    if _cm.MIDIOutputPortCreate(_client(), _cfstr("out"), ctypes.byref(port)):
        raise SystemExit("MIDIOutputPortCreate failed")
    err = _cm.MIDISend(port, dest, _packet_list(msg))
    if err:
        raise SystemExit(f"MIDISend failed: {err}")
    if not quiet:
        print(f"sent {len(msg)} bytes to {DEVICE_NAME}")


def _listen(callback):
    """Attach `callback(bytes)` to the device's source. Returns keepalive refs."""
    src = find_endpoint("source")
    client = _client()

    def on_read(pkt_list, _a, _b):
        for msg in _iter_packets(pkt_list):
            if msg:
                callback(msg)

    proc = READ_PROC(on_read)
    port = ctypes.c_void_p()
    if _cm.MIDIInputPortCreate(client, _cfstr("in"), proc, None, ctypes.byref(port)):
        raise SystemExit("MIDIInputPortCreate failed")
    if _cm.MIDIPortConnectSource(port, src, None):
        raise SystemExit("MIDIPortConnectSource failed")
    return client, port, proc  # caller must keep these alive


def _pump(seconds):
    mode = ctypes.c_void_p.in_dll(_cf, "kCFRunLoopDefaultMode")
    _cf.CFRunLoopRunInMode(mode, seconds, False)


# --------------------------------------------------------------------------
# live monitor
# --------------------------------------------------------------------------

YEL, DIM, RST = "\033[33m", "\033[2m", "\033[0m"


def describe(msg, labels):
    st = msg[0]
    kind, ch = st & 0xF0, st & 0x0F
    if kind == 0xB0 and len(msg) >= 3:
        cc, val = msg[1], msg[2]
        label = labels.get((ch, cc))
        if label is None:
            return f"CC      ch{ch + 1:<2} CC{cc:<3} val {val:<3}  {YEL}*** NOT IN PRESET ***{RST}"
        return f"CC      ch{ch + 1:<2} CC{cc:<3} val {val:<3}  {label}"
    if kind in (0x90, 0x80) and len(msg) >= 3:
        nm = "NoteOn " if kind == 0x90 else "NoteOff"
        return f"{nm} ch{ch + 1:<2} note{msg[1]:<3} vel {msg[2]:<3}  {YEL}*** NOTE ***{RST}"
    if st == 0xF0:
        return f"SYSEX   {len(msg)} bytes: {msg.hex(' ')}"
    return f"raw     {msg.hex(' ')}"


def cmd_mon(preset=None):
    labels = control_map(*parse_preset(preset)) if preset else {}
    if preset:
        print(f"labels from {os.path.basename(preset)} ({len(labels)} controls)")

    state = {"last": None, "seen": set(), "unknown": {}}

    def on_msg(msg):
        line = describe(msg, labels)
        key = msg[:2]
        state["seen"].add(key)
        if msg[0] & 0xF0 == 0xB0 and (msg[0] & 0x0F, msg[1]) not in labels:
            state["unknown"][(msg[0] & 0x0F, msg[1])] = msg[2]
        if state["last"] == key:
            print("\r" + line, end="", flush=True)   # collapse a fader sweep
        else:
            print(("\n" if state["last"] else "") + line, end="", flush=True)
        state["last"] = key

    refs = _listen(on_msg)  # noqa: F841 -- keep alive

    print(f"\nListening on {DEVICE_NAME}. Ctrl-C to stop.\n")
    print("Work through it deliberately:")
    print("  1. every knob, top row left to right, then middle, then bottom")
    print("  2. every fader including MASTER")
    print("  3. every MUTE, then every REC ARM")
    print("  4. HOLD SOLO and press each MUTE  -> should be a third CC range")
    print("  5. SEND ALL, then BANK LEFT, then BANK RIGHT")
    print(f"\n{DIM}Anything flagged NOT IN PRESET is a control the preset does not")
    print(f"describe -- that is how we identify the four fixed buttons.{RST}\n")
    try:
        while True:
            _pump(0.2)
    except KeyboardInterrupt:
        pass

    print(f"\n\n--- summary: {len(state['seen'])} distinct controls seen ---")
    if state["unknown"]:
        print("messages NOT described by the preset:")
        for (ch, cc), val in sorted(state["unknown"].items()):
            print(f"  ch{ch + 1:<2} CC{cc:<3} (last val {val})")
    else:
        print("every message matched the preset; the fixed buttons sent nothing.")
        print("=> BANK L/R and SEND ALL are handled internally by the firmware")
        print("   and cannot be mapped in Logic. Use a key command for banking.")


# --------------------------------------------------------------------------
# device I/O
# --------------------------------------------------------------------------

def cmd_send(path):
    knobs, faders, buttons = parse_preset(path)
    blob = open(path, "rb").read()
    print(f"flashing {os.path.basename(path)}  channels={channels_used(knobs, faders, buttons)}")
    send_raw(blob)
    print("done. Run `mon` to confirm the device now reports these channels.")


def cmd_dump(out=None):
    """Ask the device for its current config.

    The read opcode is a guess (0x66, paired with the confirmed 0x67 write).
    If the device does not answer, nothing is harmed -- an unrecognised SysEx
    is ignored -- and the exported preset file remains the real backup.
    """
    got = []
    refs = _listen(lambda m: got.append(m) if m[0] == 0xF0 else None)  # noqa: F841

    req = bytes([0xF0, 0x47, 0x00, 0x31, OPCODE_READ_GUESS, 0x00, 0x00, 0xF7])
    print(f"requesting config dump: {req.hex(' ')}")
    send_raw(req, quiet=True)

    deadline = time.time() + 3.0
    while time.time() < deadline and not got:
        _pump(0.2)

    if not got:
        print("\nNo SysEx reply within 3s. The read opcode guess was wrong, or the")
        print("device simply does not support dumping (quite likely -- the Editor")
        print("app may only ever write).")
        print("Not a problem: your exported preset is the authoritative backup,")
        print("and `mon` verifies the live config empirically.")
        return 1

    blob = got[0]
    out = out or "backups/hardware-dump.midimix"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(blob)
    print(f"got {len(blob)} bytes -> {out}")
    if len(blob) == 146 and blob[:7] == HEADER:
        print("looks like a valid preset:")
        cmd_show(out)
    return 0


def cmd_ports():
    for kind in ("source", "dest"):
        n = _cm.MIDIGetNumberOfSources() if kind == "source" \
            else _cm.MIDIGetNumberOfDestinations()
        get = _cm.MIDIGetSource if kind == "source" else _cm.MIDIGetDestination
        print(f"{kind}s ({n}):")
        for i in range(n):
            print(f"  - {_obj_name(get(i))}")


def main(argv):
    cmds = {
        "show": (cmd_show, 1, 1), "mon": (cmd_mon, 0, 1), "send": (cmd_send, 1, 1),
        "dump": (cmd_dump, 0, 1), "diff": (cmd_diff, 2, 2), "ports": (cmd_ports, 0, 0),
    }
    if len(argv) < 2 or argv[1] not in cmds:
        print(__doc__)
        return 2
    fn, lo, hi = cmds[argv[1]]
    args = argv[2:]
    if not lo <= len(args) <= hi:
        print(f"{argv[1]}: expected {lo}..{hi} argument(s)\n")
        print(__doc__)
        return 2
    return fn(*args) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
