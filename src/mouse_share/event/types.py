"""Frozen dataclasses representing input events.

All events use USB HID scancodes as the canonical keycode space.
Coordinates are relative (deltas) for mouse movement and scroll.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class EventType(IntEnum):
    """Wire-format event type tags."""

    MOUSE_MOVE = 0x01
    MOUSE_BUTTON = 0x03
    MOUSE_SCROLL = 0x04
    KEY_PRESS = 0x10
    KEY_RELEASE = 0x11


class MouseButtonCode(IntEnum):
    """Standard mouse button codes."""

    LEFT = 1
    RIGHT = 2
    MIDDLE = 3
    BACK = 4
    FORWARD = 5


@dataclass(frozen=True, slots=True)
class MouseMove:
    """Relative mouse movement."""

    dx: int
    dy: int
    event_type: EventType = EventType.MOUSE_MOVE


@dataclass(frozen=True, slots=True)
class MouseButton:
    """Mouse button press or release."""

    button: MouseButtonCode
    pressed: bool
    event_type: EventType = EventType.MOUSE_BUTTON


@dataclass(frozen=True, slots=True)
class MouseScroll:
    """Relative scroll (high-resolution)."""

    dx: int
    dy: int
    event_type: EventType = EventType.MOUSE_SCROLL


@dataclass(frozen=True, slots=True)
class KeyPress:
    """Key press (USB HID scancode)."""

    scancode: int
    event_type: EventType = EventType.KEY_PRESS


@dataclass(frozen=True, slots=True)
class KeyRelease:
    """Key release (USB HID scancode)."""

    scancode: int
    event_type: EventType = EventType.KEY_RELEASE


InputEvent = MouseMove | MouseButton | MouseScroll | KeyPress | KeyRelease
