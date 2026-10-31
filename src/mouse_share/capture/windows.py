"""Windows input capture using low-level hooks (SetWindowsHookEx).

Runs a Win32 message pump in a dedicated thread. Keyboard and mouse
hooks convert native events to HID-based InputEvents.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes
import logging
import threading
from typing import TYPE_CHECKING

from mouse_share.event.scancode import windows_to_hid
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

    from mouse_share.event.types import InputEvent

log = logging.getLogger(__name__)

# Win32 constants
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLMHF_INJECTED = 0x01
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# ctypes function signatures
user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

# Work in physical pixels: hook coordinates are always physical, but cursor
# and monitor APIs are scaled for DPI-unaware processes. -4 is
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+).
with contextlib.suppress(AttributeError, OSError):
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

# Without explicit signatures ctypes assumes 32-bit int arguments/returns,
# which truncates handles and LPARAM pointers on 64-bit Python.
kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, ctypes.wintypes.HINSTANCE, ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]
user32.CallNextHookEx.restype = ctypes.wintypes.LPARAM
user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


_BUTTON_MAP: dict[int, tuple[MouseButtonCode, bool]] = {
    WM_LBUTTONDOWN: (MouseButtonCode.LEFT, True),
    WM_LBUTTONUP: (MouseButtonCode.LEFT, False),
    WM_RBUTTONDOWN: (MouseButtonCode.RIGHT, True),
    WM_RBUTTONUP: (MouseButtonCode.RIGHT, False),
    WM_MBUTTONDOWN: (MouseButtonCode.MIDDLE, True),
    WM_MBUTTONUP: (MouseButtonCode.MIDDLE, False),
}


class WindowsCapture:
    """Low-level mouse and keyboard capture on Windows.

    Uses ``SetWindowsHookEx`` with ``WH_MOUSE_LL`` and ``WH_KEYBOARD_LL``.
    A dedicated thread runs the Win32 message pump.

    When suppressing, the hook returns 1 to swallow events from the local OS.
    """

    def __init__(self) -> None:
        self._on_event: Callable[[InputEvent], None] | None = None
        self._suppressing = False
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._mouse_hook: ctypes.wintypes.HHOOK | None = None
        self._kb_hook: ctypes.wintypes.HHOOK | None = None
        self._last_x: int | None = None
        self._last_y: int | None = None
        self._hotkey = HotkeyDetector()
        self._escape_cb: Callable[[], None] | None = None

        # Must store HOOKPROC references to prevent garbage collection
        self._mouse_proc = HOOKPROC(self._mouse_hook_callback)
        self._kb_proc = HOOKPROC(self._keyboard_hook_callback)

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        self._on_event = on_event
        self._thread = threading.Thread(target=self._pump_thread, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._thread_id = None

    def set_suppressing(self, suppressing: bool) -> None:
        if not suppressing and self._suppressing:
            # The cursor is about to be warped to the entry point; don't
            # measure the next move from wherever it was parked.
            self._last_x = self._last_y = None
        self._suppressing = suppressing

    @staticmethod
    def _screen_center() -> tuple[int, int]:
        return (
            user32.GetSystemMetrics(SM_CXSCREEN) // 2,
            user32.GetSystemMetrics(SM_CYSCREEN) // 2,
        )

    def set_escape_callback(self, callback: Callable[[], None]) -> None:
        self._escape_cb = callback

    def cursor_position(self) -> tuple[int, int] | None:
        pt = ctypes.wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return pt.x, pt.y

    def _pump_thread(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()

        h_inst = kernel32.GetModuleHandleW(None)
        self._mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, h_inst, 0,
        )
        self._kb_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kb_proc, h_inst, 0,
        )
        if not self._mouse_hook or not self._kb_hook:
            log.error(
                "Failed to install input hooks (error %d)", ctypes.get_last_error(),
            )

        try:
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
                self._mouse_hook = None
            if self._kb_hook:
                user32.UnhookWindowsHookEx(self._kb_hook)
                self._kb_hook = None

    def _mouse_hook_callback(
        self,
        n_code: int,
        w_param: int,
        l_param: int,
    ) -> int:
        if n_code >= 0 and self._on_event is not None:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents

            # Skip injected events to avoid capturing our own SendInput output
            if info.flags & LLMHF_INJECTED:
                return user32.CallNextHookEx(None, n_code, w_param, l_param)

            event = self._parse_mouse_event(w_param, info)
            if event is not None:
                self._on_event(event)

            if self._suppressing:
                return 1

        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _parse_mouse_event(
        self,
        w_param: int,
        info: MSLLHOOKSTRUCT,
    ) -> InputEvent | None:
        if w_param == WM_MOUSEMOVE:
            x, y = info.pt.x, info.pt.y
            if self._suppressing:
                dx, dy = self._suppressed_delta(x, y)
            elif self._last_x is not None and self._last_y is not None:
                dx = x - self._last_x
                dy = y - self._last_y
                self._last_x, self._last_y = x, y
            else:
                dx, dy = 0, 0
                self._last_x, self._last_y = x, y
            if dx == 0 and dy == 0:
                return None
            return MouseMove(dx=dx, dy=dy)

        if w_param in _BUTTON_MAP:
            button, pressed = _BUTTON_MAP[w_param]
            return MouseButton(button=button, pressed=pressed)

        if w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            hi_word = (info.mouseData >> 16) & 0xFFFF
            pressed = w_param == WM_XBUTTONDOWN
            if hi_word == XBUTTON1:
                return MouseButton(button=MouseButtonCode.BACK, pressed=pressed)
            if hi_word == XBUTTON2:
                return MouseButton(button=MouseButtonCode.FORWARD, pressed=pressed)
            return None

        if w_param == WM_MOUSEWHEEL:
            delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
            return MouseScroll(dx=0, dy=delta)

        if w_param == WM_MOUSEHWHEEL:
            delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
            return MouseScroll(dx=delta, dy=0)

        return None

    def _suppressed_delta(self, x: int, y: int) -> tuple[int, int]:
        """Delta of a swallowed move, measured from the real cursor.

        Swallowed moves never reach the cursor, so *x*, *y* is "where it
        is now" plus the motion. Measuring from the actual position (not
        an assumed one) can't drift. The cursor is also kept parked at the
        screen centre so motion toward any edge isn't clamped to zero;
        this runs on the hook thread, so it can't race other moves.
        """
        cur = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cur))
        cx, cy = self._screen_center()
        if (cur.x, cur.y) != (cx, cy):
            user32.SetCursorPos(cx, cy)
        return x - cur.x, y - cur.y

    def _keyboard_hook_callback(
        self,
        n_code: int,
        w_param: int,
        l_param: int,
    ) -> int:
        if n_code >= 0 and self._on_event is not None:
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

            if info.flags & LLMHF_INJECTED:
                return user32.CallNextHookEx(None, n_code, w_param, l_param)

            hid = windows_to_hid(info.vkCode)
            if hid is not None:
                pressed = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if self._hotkey.key_event(hid, pressed) and self._escape_cb is not None:
                    self._escape_cb()
                    return user32.CallNextHookEx(None, n_code, w_param, l_param)

                if pressed:
                    self._on_event(KeyPress(scancode=hid))
                elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                    self._on_event(KeyRelease(scancode=hid))

            if self._suppressing:
                return 1

        return user32.CallNextHookEx(None, n_code, w_param, l_param)
