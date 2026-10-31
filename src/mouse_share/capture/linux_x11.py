"""Linux X11 input capture using XRecord.

Two X11 display connections are used:
- A *record* display that blocks in ``enable_context`` (runs in a dedicated thread).
- A *control* display for ``XGrabPointer``/``XGrabKeyboard`` (suppression).

X11 keycodes are evdev + 8; we subtract 8 before converting to HID.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from Xlib import X, display
from Xlib.ext import record

from mouse_share.event.scancode import evdev_to_hid
from mouse_share.event.types import (
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
    MouseMove,
    MouseScroll,
)
from mouse_share.hotkey import HotkeyDetector

if TYPE_CHECKING:
    from collections.abc import Callable

    from Xlib.protocol import rq

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

_X11_BUTTON_MAP: dict[int, MouseButtonCode] = {
    _X11_BTN_LEFT: MouseButtonCode.LEFT,
    _X11_BTN_MIDDLE: MouseButtonCode.MIDDLE,
    _X11_BTN_RIGHT: MouseButtonCode.RIGHT,
    _X11_BTN_BACK: MouseButtonCode.BACK,
    _X11_BTN_FORWARD: MouseButtonCode.FORWARD,
}


class X11Capture:
    """Low-level mouse and keyboard capture on Linux X11 using XRecord.

    When suppressing, ``XGrabPointer`` and ``XGrabKeyboard`` are used on the
    control display to prevent events from reaching other X11 clients.
    """

    def __init__(self) -> None:
        self._on_event: Callable[[InputEvent], None] | None = None
        self._suppressing = False
        self._thread: threading.Thread | None = None
        self._record_display: display.Display | None = None
        self._control_display: display.Display | None = None
        self._context: int | None = None
        self._last_x: int | None = None
        self._last_y: int | None = None
        self._running = False
        self._hotkey = HotkeyDetector()
        self._escape_cb: Callable[[], None] | None = None
        # Guards the control display and _last_x/_last_y, which are touched
        # from both the record thread and the event loop thread.
        self._lock = threading.Lock()

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        self._on_event = on_event
        self._record_display = display.Display()
        self._control_display = display.Display()
        self._running = True

        # Create XRecord context for all input events
        ctx = self._record_display.record_create_context(
            0,
            [record.AllClients],
            [{
                "core_requests": (0, 0),
                "core_replies": (0, 0),
                "ext_requests": (0, 0, 0, 0),
                "ext_replies": (0, 0, 0, 0),
                "delivered_events": (0, 0),
                # KeyPress(2)..MotionNotify(6): keys, buttons, and motion
                "device_events": (X.KeyPress, X.MotionNotify),
                "errors": (0, 0),
                "client_started": False,
                "client_died": False,
            }],
        )
        self._context = ctx

        self._thread = threading.Thread(target=self._record_thread, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._context is not None and self._control_display is not None:
            self._control_display.record_disable_context(self._context)
            self._control_display.flush()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._context is not None and self._record_display is not None:
            self._record_display.record_free_context(self._context)
        if self._record_display is not None:
            self._record_display.close()
            self._record_display = None
        if self._control_display is not None:
            self._control_display.close()
            self._control_display = None
        self._context = None

    def set_suppressing(self, suppressing: bool) -> None:
        if suppressing == self._suppressing:
            return

        with self._lock:
            self._suppressing = suppressing
            if self._control_display is None:
                return

            root = self._control_display.screen().root
            if suppressing:
                root.grab_pointer(
                    True,
                    X.PointerMotionMask | X.ButtonPressMask | X.ButtonReleaseMask,
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                    X.NONE,
                    X.NONE,
                    X.CurrentTime,
                )
                root.grab_keyboard(True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
                # Move the cursor off the edge so further motion isn't
                # clamped away by the X server.
                self._recenter_locked()
            else:
                self._control_display.ungrab_pointer(X.CurrentTime)
                self._control_display.ungrab_keyboard(X.CurrentTime)
                # The cursor gets warped to the entry point next; don't
                # measure the next move from the recentred position.
                self._last_x = self._last_y = None
            self._control_display.flush()

    def set_escape_callback(self, callback: Callable[[], None]) -> None:
        self._escape_cb = callback

    def cursor_position(self) -> tuple[int, int] | None:
        with self._lock:
            if self._control_display is None:
                return None
            pointer = self._control_display.screen().root.query_pointer()
            return pointer.root_x, pointer.root_y

    def _center(self) -> tuple[int, int]:
        assert self._control_display is not None
        screen = self._control_display.screen()
        return screen.width_in_pixels // 2, screen.height_in_pixels // 2

    def _recenter_locked(self) -> None:
        """Warp the cursor to the desktop centre. Caller holds ``_lock``."""
        if self._control_display is None:
            return
        cx, cy = self._center()
        self._control_display.screen().root.warp_pointer(cx, cy)
        self._control_display.flush()
        self._last_x, self._last_y = cx, cy

    def _record_thread(self) -> None:
        if self._record_display is None or self._context is None:
            return
        self._record_display.record_enable_context(self._context, self._record_callback)

    def _record_callback(self, reply: rq.Event) -> None:
        if not self._running:
            return
        if reply.category != record.FromServer:
            return
        if reply.client_swapped:
            return

        data = reply.data
        while len(data) > 0:
            event_type = data[0]
            # X11 event data is 32 bytes
            if len(data) < 32:
                break

            self._dispatch_event(event_type, data[:32])
            data = data[32:]

    def _dispatch_event(self, event_type: int, data: bytes) -> None:
        if self._on_event is None:
            return

        if event_type == X.MotionNotify:
            # Root x,y are at bytes 20-21 and 22-23 (big-endian short)
            root_x = int.from_bytes(data[20:22], "little", signed=True)
            root_y = int.from_bytes(data[22:24], "little", signed=True)
            move: MouseMove | None = None
            with self._lock:
                if self._last_x is not None and self._last_y is not None:
                    dx = root_x - self._last_x
                    dy = root_y - self._last_y
                    if dx != 0 or dy != 0:
                        move = MouseMove(dx=dx, dy=dy)
                self._last_x = root_x
                self._last_y = root_y

                # While forwarding to a peer the real cursor still moves (the
                # grab doesn't freeze it); pull it back before it hits an edge.
                if self._suppressing and self._control_display is not None:
                    cx, cy = self._center()
                    if abs(root_x - cx) > cx // 2 or abs(root_y - cy) > cy // 2:
                        self._recenter_locked()
            if move is not None:
                self._on_event(move)

        elif event_type in (X.ButtonPress, X.ButtonRelease):
            button = data[1]
            pressed = event_type == X.ButtonPress

            # Scroll buttons emit scroll events
            if button == _X11_BTN_SCROLL_UP:
                if pressed:
                    self._on_event(MouseScroll(dx=0, dy=120))
            elif button == _X11_BTN_SCROLL_DOWN:
                if pressed:
                    self._on_event(MouseScroll(dx=0, dy=-120))
            elif button == _X11_BTN_SCROLL_LEFT:
                if pressed:
                    self._on_event(MouseScroll(dx=-120, dy=0))
            elif button == _X11_BTN_SCROLL_RIGHT:
                if pressed:
                    self._on_event(MouseScroll(dx=120, dy=0))
            elif button in _X11_BUTTON_MAP:
                self._on_event(MouseButton(
                    button=_X11_BUTTON_MAP[button],
                    pressed=pressed,
                ))

        elif event_type in (X.KeyPress, X.KeyRelease):
            keycode = data[1]
            # X11 keycode = evdev keycode + 8
            evdev_code = keycode - 8
            hid = evdev_to_hid(evdev_code)
            if hid is not None:
                pressed = event_type == X.KeyPress
                if self._hotkey.key_event(hid, pressed) and self._escape_cb is not None:
                    self._escape_cb()
                    return

                if pressed:
                    self._on_event(KeyPress(scancode=hid))
                else:
                    self._on_event(KeyRelease(scancode=hid))
