"""Tracks which keys and mouse buttons are held down in an event stream.

Used when focus moves between machines: whichever side stops receiving
input releases what it still holds, so nothing is left stuck down.
"""

from __future__ import annotations

from mouse_share.event.types import (
    InputEvent,
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
)


class HeldInput:
    """Set of currently pressed keys (HID scancodes) and mouse buttons."""

    def __init__(self) -> None:
        self._keys: set[int] = set()
        self._buttons: set[MouseButtonCode] = set()

    @property
    def keys(self) -> frozenset[int]:
        return frozenset(self._keys)

    @property
    def buttons(self) -> frozenset[MouseButtonCode]:
        return frozenset(self._buttons)

    def update(self, event: InputEvent) -> None:
        if isinstance(event, KeyPress):
            self._keys.add(event.scancode)
        elif isinstance(event, KeyRelease):
            self._keys.discard(event.scancode)
        elif isinstance(event, MouseButton):
            if event.pressed:
                self._buttons.add(event.button)
            else:
                self._buttons.discard(event.button)

    def release_events(self) -> list[InputEvent]:
        """Releases for everything held (buttons first), and forget it all."""
        events: list[InputEvent] = [
            MouseButton(button=b, pressed=False) for b in sorted(self._buttons)
        ]
        events += [KeyRelease(scancode=k) for k in sorted(self._keys)]
        self._keys.clear()
        self._buttons.clear()
        return events

    def clear(self) -> None:
        self._keys.clear()
        self._buttons.clear()
