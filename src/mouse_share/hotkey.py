"""Escape hotkey detector for Ctrl+Alt+Escape.

Tracks modifier key state and detects when the escape combo is fully pressed.
Used inside low-level capture callbacks to break out of input suppression.
"""

from __future__ import annotations

# HID usage codes for the escape combo
_LCTRL: int = 0xE0
_LALT: int = 0xE2
_ESCAPE: int = 0x29

ESCAPE_COMBO: frozenset[int] = frozenset({_LCTRL, _LALT, _ESCAPE})


class HotkeyDetector:
    """Stateless-ish detector that fires when Ctrl+Alt+Escape are all held."""

    def __init__(self) -> None:
        self._pressed: set[int] = set()

    def key_event(self, scancode: int, pressed: bool) -> bool:
        """Track key state; return True when the escape combo is active."""
        if pressed:
            self._pressed.add(scancode)
        else:
            self._pressed.discard(scancode)
        return self._pressed >= ESCAPE_COMBO
