#!/usr/bin/env python3
"""Tests for the MIDIPacketList parsing in midimix.py. No hardware needed.

Why this file exists
--------------------
The first version of _iter_packets assumed packet[0] begins at offset 8 in a
MIDIPacketList:

    struct MIDIPacket     { MIDITimeStamp timeStamp; UInt16 length; Byte data[256]; };
    struct MIDIPacketList { UInt32 numPackets; MIDIPacket packet[1]; };

Natural alignment would indeed put it at 8, because MIDITimeStamp is 64-bit.
But on arm64 CoreMIDI wraps both structs in `#pragma pack(4)`, so packet[0]
actually begins at offset 4. Reading at 8 lands inside the timestamp, yields a
garbage length, and walks off the end of the buffer. That surfaced as a bus
error -- the process is killed outright, with no Python traceback to work from.

What this does and does not prove
---------------------------------
It builds MIDIPacketList buffers in BOTH layouts by hand and checks the parser
recovers the exact messages from each, plus that malformed input is refused
rather than followed off the end of the buffer.

It does NOT exercise Apple's own struct construction. An in-process CoreMIDI
loopback receives nothing (CoreMIDI does not deliver a virtual endpoint's
traffic back to its creating client), and cross-process virtual endpoints did
not deliver in this environment either. The real device remains the final
check -- but the parser is now fail-safe: bad input yields no output instead of
a crash.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midimix as M  # noqa: E402


def make_list(messages, first_offset, align):
    """Hand-build a MIDIPacketList; `first_offset` 4 = arm64 pack(4), 8 = natural."""
    buf = bytearray(struct.pack("<I", len(messages)))
    buf += b"\x00" * (first_offset - len(buf))
    for msg in messages:
        buf += struct.pack("<Q", 0)            # timeStamp
        buf += struct.pack("<H", len(msg))     # length
        buf += msg
        while len(buf) % align:                # pad to the next packet boundary
            buf += b"\x00"
    buf += b"\x00" * 64                        # slack, so an overrun is detectable
    return bytes(buf)


def parse(blob):
    import ctypes
    arr = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    return list(M._iter_packets(ctypes.addressof(arr)))


MESSAGES = [
    bytes([0xB0, 0x16, 0x7F]),
    bytes([0xB3, 0x16, 0x00]),
    bytes([0xB7, 0x2A, 0x40]),
    bytes([0x90, 0x3C, 0x64]),
    bytes([0x80, 0x3C, 0x00]),
]

failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def main():
    print("packet layouts")
    for label, off in [("arm64 pack(4), packet[0] @ 4", 4),
                       ("natural alignment, packet[0] @ 8", 8)]:
        got = parse(make_list(MESSAGES, off, 4))
        check(label, got == MESSAGES, f"{len(got)}/{len(MESSAGES)} messages")

    print("\nsingle packet, both layouts")
    for off in (4, 8):
        got = parse(make_list([MESSAGES[0]], off, 4))
        check(f"one packet @ offset {off}", got == [MESSAGES[0]])

    print("\nmalformed input is refused, not followed")
    check("zero-filled buffer yields nothing", parse(bytes(128)) == [])
    check("implausible numPackets refused",
          parse(struct.pack("<I", 999999) + bytes(128)) == [])
    check("length beyond 256 refused",
          parse(struct.pack("<I", 1) + struct.pack("<Q", 0)
                + struct.pack("<H", 9999) + bytes(64)) == [])
    check("non-status first byte refused",
          parse(struct.pack("<I", 1) + struct.pack("<Q", 0)
                + struct.pack("<H", 3) + bytes([0x00, 0x00, 0x00]) + bytes(64)) == [])
    check("null pointer refused", list(M._iter_packets(0)) == [])

    print("\noutput packets are built at the same pack(4) offsets")
    # _packet_list once built at natural alignment, so CoreMIDI read the length
    # out of the zero half of the timestamp and sent a zero-length packet: no
    # error, no data. Every flash and every LED message silently did nothing.
    import ctypes as _c
    for m in MESSAGES:
        buf = M._packet_list(m)
        got = list(M._iter_packets(_c.addressof(buf)))
        check(f"_packet_list round-trips {m.hex(' ')}", got == [m], f"got {got}")

    print("\nmessage decoding")
    check("CC decodes with channel and value",
          "ch4" in M.describe(bytes([0xB3, 0x16, 0x00]), {})
          and "CC22" in M.describe(bytes([0xB3, 0x16, 0x00]), {}))
    check("NoteOn is flagged as a note",
          "NOTE" in M.describe(bytes([0x90, 0x3C, 0x64]), {}))
    labels = {(3, 22): "knob row1 strip1"}
    check("known address gets its label",
          "knob row1 strip1" in M.describe(bytes([0xB3, 0x16, 0x40]), labels))
    check("unknown address is flagged",
          "NOT IN PRESET" in M.describe(bytes([0xB9, 0x7F, 0x40]), labels))

    print("\npreset round-trip")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("presets/mgb-mode.midimix", "presets/logic-mode.midimix"):
        path = os.path.join(here, name)
        if not os.path.exists(path):
            continue
        k, f, b = M.parse_preset(path)
        rebuilt = M.build_preset(k, f, b)
        check(f"{name} re-encodes byte-identically",
              rebuilt == open(path, "rb").read())

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("PASS: all checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
