"""Linux X11 input emulation using XTest.

HID scancodes are converted to evdev and then to X11 keycodes (+8).
Mouse scroll is synthesised as button 4/5/6/7 press+release pairs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Xlib import X, display
from Xlib.ext import xtest

from mouse_share.event.scancode import hid_to_evdev
from mouse_share.event.types import (
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
    MouseMove,
    MouseScroll,
)

if TYPE_CHECKING:
    from mouse_share.event.types import InputEvent

# X11 button numbers
_X11_BTN_LEFT = 1
_X11_BTN_MIDDLE = 2
_X11_BTN_RIGHT = 3
_X11_BTN_SCROLL_UP = 4
_X11_BTN_SCROLL_DOWN = 5
_X11_BTN_SCROLL_LEFT = 6
_X11_BTN_SCROLL_RIGHT = 7
_X11_BTN_BACK = 8
_X11_BTN_FORWARD = 9

_BUTTON_MAP: dict[MouseButtonCode, int] = {
    MouseButtonCode.LEFT: _X11_BTN_LEFT,
    MouseButtonCode.MIDDLE: _X11_BTN_MIDDLE,
    MouseButtonCode.RIGHT: _X11_BTN_RIGHT,
    MouseButtonCode.BACK: _X11_BTN_BACK,
    MouseButtonCode.FORWARD: _X11_BTN_FORWARD,
}


class X11Emulate:
    """Inject input events on Linux X11 using XTest."""

    def __init__(self) -> None:
        self._display: display.Display | None = None

    def start(self) -> None:
        self._display = display.Display()

    def stop(self) -> None:
        if self._display is not None:
            self._display.close()
            self._display = None

    def inject(self, event: InputEvent) -> None:
        if self._display is None:
            return

        if isinstance(event, MouseMove):
            xtest.fake_input(
                self._display,
                X.MotionNotify,
                detail=1,  # relative motion
                x=event.dx,
                y=event.dy,
            )
            self._display.flush()

        elif isinstance(event, MouseButton):
            x11_btn = _BUTTON_MAP.get(event.button)
            if x11_btn is None:
                return
            event_type = X.ButtonPress if event.pressed else X.ButtonRelease
            xtest.fake_input(self._display, event_type, detail=x11_btn)
            self._display.flush()

        elif isinstance(event, MouseScroll):
            self._inject_scroll(event.dx, event.dy)

        elif isinstance(event, KeyPress):
            keycode = self._hid_to_x11_keycode(event.scancode)
            if keycode is not None:
                xtest.fake_input(self._display, X.KeyPress, detail=keycode)
                self._display.flush()

        elif isinstance(event, KeyRelease):
            keycode = self._hid_to_x11_keycode(event.scancode)
            if keycode is not None:
                xtest.fake_input(self._display, X.KeyRelease, detail=keycode)
                self._display.flush()

    def warp(self, x: int, y: int) -> None:
        if self._display is None:
            return
        self._display.screen().root.warp_pointer(x, y)
        self._display.flush()

    def cursor_position(self) -> tuple[int, int] | None:
        if self._display is None:
            return None
        # Same connection as the injected events, so the server has already
        # applied them when it answers this round-trip.
        pointer = self._display.screen().root.query_pointer()
        return pointer.root_x, pointer.root_y

    def _inject_scroll(self, dx: int, dy: int) -> None:
        if self._display is None:
            return

        # Vertical scroll: button 4 (up) / 5 (down)
        if dy != 0:
            btn = _X11_BTN_SCROLL_UP if dy > 0 else _X11_BTN_SCROLL_DOWN
            clicks = abs(dy) // 120 or 1
            for _ in range(clicks):
                xtest.fake_input(self._display, X.ButtonPress, detail=btn)
                xtest.fake_input(self._display, X.ButtonRelease, detail=btn)

        # Horizontal scroll: button 6 (left) / 7 (right)
        if dx != 0:
            btn = _X11_BTN_SCROLL_RIGHT if dx > 0 else _X11_BTN_SCROLL_LEFT
            clicks = abs(dx) // 120 or 1
            for _ in range(clicks):
                xtest.fake_input(self._display, X.ButtonPress, detail=btn)
                xtest.fake_input(self._display, X.ButtonRelease, detail=btn)

        self._display.flush()

    @staticmethod
    def _hid_to_x11_keycode(hid_code: int) -> int | None:
        evdev_code = hid_to_evdev(hid_code)
        if evdev_code is None:
            return None
        return evdev_code + 8
