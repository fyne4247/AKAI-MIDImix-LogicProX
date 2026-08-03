#!/usr/bin/env python3
"""Small ctypes wrapper for the CoreMIDI features used by the mixer bridge.

This is runtime plumbing, not a general MIDI utility.  It intentionally
contains no preset flashing, device inspection, monitoring, or command-line
interface.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform


DEVICE_NAME = "MIDI Mix"
UTF8 = 0x08000100

# CoreMIDI's object/client/port/endpoint references are UInt32 values, not
# pointers.  Explicit argtypes are essential on a 64-bit process: otherwise
# ctypes may truncate CoreFoundation pointers passed to CoreMIDI.
Ref = ctypes.c_uint32
RefP = ctypes.POINTER(Ref)
OSStatus = ctypes.c_int32
READ_PROC = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_NOTIFY_PROC = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


def _load_framework(name: str, fallback: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name) or fallback
    try:
        return ctypes.CDLL(path)
    except OSError as exc:
        raise RuntimeError(f"{name} is unavailable; this bridge requires macOS") from exc


_cm = _load_framework(
    "CoreMIDI", "/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI"
)
_cf = _load_framework(
    "CoreFoundation",
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
)


_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFStringCreateWithCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint32,
]
_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFStringGetCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_long,
    ctypes.c_uint32,
]
_cf.CFRelease.restype = None
_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFRunLoopRunInMode.restype = ctypes.c_int32
_cf.CFRunLoopRunInMode.argtypes = [
    ctypes.c_void_p,
    ctypes.c_double,
    ctypes.c_bool,
]


for _name, _result, _arguments in [
    ("MIDIGetNumberOfSources", ctypes.c_ulong, []),
    ("MIDIGetSource", Ref, [ctypes.c_ulong]),
    ("MIDIGetNumberOfDestinations", ctypes.c_ulong, []),
    ("MIDIGetDestination", Ref, [ctypes.c_ulong]),
    (
        "MIDIObjectGetStringProperty",
        OSStatus,
        [Ref, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
    ),
    (
        "MIDIClientCreate",
        OSStatus,
        [ctypes.c_void_p, _NOTIFY_PROC, ctypes.c_void_p, RefP],
    ),
    (
        "MIDIInputPortCreate",
        OSStatus,
        [Ref, ctypes.c_void_p, READ_PROC, ctypes.c_void_p, RefP],
    ),
    ("MIDIOutputPortCreate", OSStatus, [Ref, ctypes.c_void_p, RefP]),
    ("MIDIPortConnectSource", OSStatus, [Ref, Ref, ctypes.c_void_p]),
    ("MIDISend", OSStatus, [Ref, Ref, ctypes.c_void_p]),
    ("MIDIClientDispose", OSStatus, [Ref]),
    ("MIDIPacketListInit", ctypes.c_void_p, [ctypes.c_void_p]),
    (
        "MIDIPacketListAdd",
        ctypes.c_void_p,
        [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ubyte),
        ],
    ),
]:
    function = getattr(_cm, _name)
    function.restype = _result
    function.argtypes = _arguments


_kName = ctypes.c_void_p.in_dll(_cm, "kMIDIPropertyName")
_NULL_NOTIFY = ctypes.cast(None, _NOTIFY_PROC)
_RUN_LOOP_DEFAULT_MODE = ctypes.c_void_p.in_dll(_cf, "kCFRunLoopDefaultMode")


def _cfstr(value: str) -> int:
    """Create a CFStringRef suitable for the short-lived bridge setup calls."""
    result = _cf.CFStringCreateWithCString(None, value.encode("utf-8"), UTF8)
    if not result:
        raise RuntimeError("CFStringCreateWithCString failed")
    return result


def _obj_name(ref: Ref) -> str:
    """Return a CoreMIDI object's display name, or ``?`` when unavailable."""
    value = ctypes.c_void_p()
    if _cm.MIDIObjectGetStringProperty(ref, _kName, ctypes.byref(value)) != 0:
        return "?"
    if not value.value:
        return "?"

    try:
        size = 256
        buffer = ctypes.create_string_buffer(size)
        if not _cf.CFStringGetCString(value.value, buffer, size, UTF8):
            return "?"
        return buffer.value.decode("utf-8", errors="replace")
    finally:
        _cf.CFRelease(value.value)


def find_endpoint(kind: str) -> Ref:
    """Find the physical MIDI Mix source or destination endpoint."""
    if kind == "source":
        count = _cm.MIDIGetNumberOfSources()
        get_endpoint = _cm.MIDIGetSource
    elif kind == "dest":
        count = _cm.MIDIGetNumberOfDestinations()
        get_endpoint = _cm.MIDIGetDestination
    else:
        raise ValueError("kind must be 'source' or 'dest'")

    found_names = []
    for index in range(count):
        endpoint = get_endpoint(index)
        name = _obj_name(endpoint)
        found_names.append(name)
        if name == DEVICE_NAME:
            return endpoint

    raise SystemExit(
        f"No CoreMIDI {kind} named {DEVICE_NAME!r}. "
        f"Found: {found_names or 'nothing'}\n"
        "Is the MIDI Mix connected and powered?"
    )


# MIDIPacketList begins with UInt32 numPackets, followed by a pack(4)
# MIDIPacket (timestamp, length, data).  CoreMIDI's MIDIPacketNext rule then
# differs by CPU: ARM rounds each following packet to a four-byte boundary;
# Intel leaves following packets unaligned.
_MAX_PACKET_LENGTH = 0xFFFF
_MAX_PACKET_COUNT = 256
_MAX_LIST_OFFSET = 0x10000
_ARM_PACKET_ALIGNMENT = platform.machine().lower() in {
    "arm",
    "arm64",
    "aarch64",
}


def _valid_packet_at(base, offset: int) -> bool:
    length = ctypes.cast(
        ctypes.byref(base.contents, offset + 8),
        ctypes.POINTER(ctypes.c_uint16),
    )[0]
    if not 1 <= length <= _MAX_PACKET_LENGTH:
        return False
    # Running status is not permitted in a CoreMIDI packet.
    return base[offset + 10] >= 0x80


def _iter_packets(packet_list_ptr):
    """Yield each MIDI byte string in a CoreMIDI MIDIPacketList callback."""
    if not packet_list_ptr:
        return

    base = ctypes.cast(packet_list_ptr, ctypes.POINTER(ctypes.c_ubyte))
    count = ctypes.cast(packet_list_ptr, ctypes.POINTER(ctypes.c_uint32))[0]
    if not 1 <= count <= _MAX_PACKET_COUNT:
        return

    # Current Apple headers pack packet[0] at byte 4.  Retaining byte 8 as a
    # fallback keeps compatibility with packet lists produced by older wrappers
    # that used the platform's natural UInt64 alignment.
    offset = next(
        (candidate for candidate in (4, 8) if _valid_packet_at(base, candidate)),
        None,
    )
    if offset is None:
        return

    for _ in range(count):
        length = ctypes.cast(
            ctypes.byref(base.contents, offset + 8),
            ctypes.POINTER(ctypes.c_uint16),
        )[0]
        if not 1 <= length <= _MAX_PACKET_LENGTH:
            return

        yield bytes(base[offset + 10 : offset + 10 + length])
        offset += 10 + length
        if _ARM_PACKET_ALIGNMENT:
            offset = (offset + 3) & ~3
        if offset > _MAX_LIST_OFFSET:
            return


def _packet_list(message: bytes):
    """Build a one-packet MIDIPacketList for MIDISend or MIDIReceived.

    Delegating the ABI layout to CoreMIDI avoids hard-coding the ARM/Intel
    packet-alignment difference.
    """
    message = bytes(message)
    if not message:
        raise ValueError("MIDI message must not be empty")
    if len(message) > _MAX_PACKET_LENGTH:
        raise ValueError("MIDI message exceeds CoreMIDI's UInt16 packet length")

    capacity = len(message) + 32
    buffer = ctypes.create_string_buffer(capacity)
    packet = _cm.MIDIPacketListInit(buffer)
    data = (ctypes.c_ubyte * len(message)).from_buffer_copy(message)
    added = _cm.MIDIPacketListAdd(
        buffer,
        capacity,
        packet,
        0,
        len(message),
        data,
    )
    if not added:
        raise RuntimeError("MIDIPacketListAdd failed")
    return buffer


def _pump(seconds: float) -> None:
    """Run the CoreFoundation loop so CoreMIDI can deliver callbacks."""
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    _cf.CFRunLoopRunInMode(_RUN_LOOP_DEFAULT_MODE, seconds, False)


__all__ = [
    "OSStatus",
    "READ_PROC",
    "Ref",
    "RefP",
    "_NULL_NOTIFY",
    "_cfstr",
    "_cm",
    "_iter_packets",
    "_obj_name",
    "_packet_list",
    "_pump",
    "find_endpoint",
]
