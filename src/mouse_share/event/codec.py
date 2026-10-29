"""Binary codec for UDP wire format using struct.Struct.

Wire format per the spec:
  Header (4 bytes): version:u8 | flags:u8 | count:u16 (LE)
  Per event:
    MouseMove:    0x01 | dx:i16 | dy:i16        (5 bytes)
    MouseButton:  0x03 | button:u8 | pressed:u8 (3 bytes)
    MouseScroll:  0x04 | dx:i16 | dy:i16        (5 bytes)
    KeyPress:     0x10 | scancode:u16            (3 bytes)
    KeyRelease:   0x11 | scancode:u16            (3 bytes)
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from mouse_share.event.types import (
    EventType,
    InputEvent,
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
    MouseMove,
    MouseScroll,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

PROTOCOL_VERSION = 1
MAX_EVENTS_PER_BATCH = 64

# Pre-compiled struct formats for zero per-call overhead
_HEADER = struct.Struct("<BBH")  # version, flags, count
_MOUSE_MOVE = struct.Struct("<Bhh")  # type, dx, dy
_MOUSE_BUTTON = struct.Struct("<BBB")  # type, button, pressed
_MOUSE_SCROLL = struct.Struct("<Bhh")  # type, dx, dy
_KEY_EVENT = struct.Struct("<BH")  # type, scancode

# Map event type tag → (struct, size)
_DECODERS: dict[int, tuple[struct.Struct, int]] = {
    EventType.MOUSE_MOVE: (_MOUSE_MOVE, _MOUSE_MOVE.size),
    EventType.MOUSE_BUTTON: (_MOUSE_BUTTON, _MOUSE_BUTTON.size),
    EventType.MOUSE_SCROLL: (_MOUSE_SCROLL, _MOUSE_SCROLL.size),
    EventType.KEY_PRESS: (_KEY_EVENT, _KEY_EVENT.size),
    EventType.KEY_RELEASE: (_KEY_EVENT, _KEY_EVENT.size),
}


def encode_batch(events: Sequence[InputEvent], flags: int = 0) -> bytes:
    """Encode a batch of events into a single UDP datagram.

    Raises ValueError if batch exceeds MAX_EVENTS_PER_BATCH.
    """
    count = len(events)
    if count > MAX_EVENTS_PER_BATCH:
        raise ValueError(f"Batch size {count} exceeds max {MAX_EVENTS_PER_BATCH}")
    if count == 0:
        raise ValueError("Cannot encode empty batch")

    parts: list[bytes] = [_HEADER.pack(PROTOCOL_VERSION, flags, count)]

    for event in events:
        match event:
            case MouseMove(dx=dx, dy=dy):
                parts.append(_MOUSE_MOVE.pack(EventType.MOUSE_MOVE, dx, dy))
            case MouseButton(button=button, pressed=pressed):
                parts.append(_MOUSE_BUTTON.pack(EventType.MOUSE_BUTTON, button, int(pressed)))
            case MouseScroll(dx=dx, dy=dy):
                parts.append(_MOUSE_SCROLL.pack(EventType.MOUSE_SCROLL, dx, dy))
            case KeyPress(scancode=sc):
                parts.append(_KEY_EVENT.pack(EventType.KEY_PRESS, sc))
            case KeyRelease(scancode=sc):
                parts.append(_KEY_EVENT.pack(EventType.KEY_RELEASE, sc))
            case _:
                raise ValueError(f"Unknown event type: {type(event)}")

    return b"".join(parts)


def decode_batch(data: bytes) -> tuple[int, int, list[InputEvent]]:
    """Decode a UDP datagram into a list of events.

    Returns (version, flags, events).
    Raises ValueError on malformed data.
    """
    if len(data) < _HEADER.size:
        raise ValueError(f"Datagram too short: {len(data)} bytes")

    version, flags, count = _HEADER.unpack_from(data, 0)
    if count == 0 or count > MAX_EVENTS_PER_BATCH:
        raise ValueError(f"Invalid event count: {count}")

    events: list[InputEvent] = []
    offset = _HEADER.size

    for _ in range(count):
        if offset >= len(data):
            raise ValueError("Datagram truncated: ran out of data")

        tag = data[offset]
        decoder_info = _DECODERS.get(tag)
        if decoder_info is None:
            raise ValueError(f"Unknown event type tag: 0x{tag:02X}")

        fmt, size = decoder_info
        if offset + size > len(data):
            raise ValueError("Datagram truncated: insufficient bytes for event")

        fields = fmt.unpack_from(data, offset)
        offset += size

        match tag:
            case EventType.MOUSE_MOVE:
                events.append(MouseMove(dx=fields[1], dy=fields[2]))
            case EventType.MOUSE_BUTTON:
                events.append(MouseButton(button=MouseButtonCode(fields[1]), pressed=bool(fields[2])))
            case EventType.MOUSE_SCROLL:
                events.append(MouseScroll(dx=fields[1], dy=fields[2]))
            case EventType.KEY_PRESS:
                events.append(KeyPress(scancode=fields[1]))
            case EventType.KEY_RELEASE:
                events.append(KeyRelease(scancode=fields[1]))

    return version, flags, events
