"""Windows input emulation using SendInput."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import TYPE_CHECKING

from mouse_share.event.scancode import hid_to_windows
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

# SendInput constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
KEYEVENTF_KEYUP = 0x0002
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

user32 = ctypes.windll.user32  # type: ignore[attr-defined]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _InputUnion),
    ]


_BUTTON_DOWN_FLAGS: dict[MouseButtonCode, tuple[int, int]] = {
    MouseButtonCode.LEFT: (MOUSEEVENTF_LEFTDOWN, 0),
    MouseButtonCode.RIGHT: (MOUSEEVENTF_RIGHTDOWN, 0),
    MouseButtonCode.MIDDLE: (MOUSEEVENTF_MIDDLEDOWN, 0),
    MouseButtonCode.BACK: (MOUSEEVENTF_XDOWN, XBUTTON1),
    MouseButtonCode.FORWARD: (MOUSEEVENTF_XDOWN, XBUTTON2),
}

_BUTTON_UP_FLAGS: dict[MouseButtonCode, tuple[int, int]] = {
    MouseButtonCode.LEFT: (MOUSEEVENTF_LEFTUP, 0),
    MouseButtonCode.RIGHT: (MOUSEEVENTF_RIGHTUP, 0),
    MouseButtonCode.MIDDLE: (MOUSEEVENTF_MIDDLEUP, 0),
    MouseButtonCode.BACK: (MOUSEEVENTF_XUP, XBUTTON1),
    MouseButtonCode.FORWARD: (MOUSEEVENTF_XUP, XBUTTON2),
}


def _make_mouse_input(dx: int, dy: int, flags: int, data: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = dx
    inp.union.mi.dy = dy
    inp.union.mi.dwFlags = flags
    inp.union.mi.mouseData = data
    return inp


def _make_kb_input(vk: int, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = flags
    return inp


def _send(inp: INPUT) -> None:
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


class WindowsEmulate:
    """Inject input events on Windows using ``SendInput``."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def inject(self, event: InputEvent) -> None:
        if isinstance(event, MouseMove):
            _send(_make_mouse_input(event.dx, event.dy, MOUSEEVENTF_MOVE))

        elif isinstance(event, MouseButton):
            table = _BUTTON_DOWN_FLAGS if event.pressed else _BUTTON_UP_FLAGS
            flags, data = table[event.button]
            _send(_make_mouse_input(0, 0, flags, data))

        elif isinstance(event, MouseScroll):
            if event.dy:
                _send(_make_mouse_input(0, 0, MOUSEEVENTF_WHEEL, event.dy))
            if event.dx:
                _send(_make_mouse_input(0, 0, MOUSEEVENTF_HWHEEL, event.dx))

        elif isinstance(event, KeyPress):
            vk = hid_to_windows(event.scancode)
            if vk is not None:
                _send(_make_kb_input(vk))

        elif isinstance(event, KeyRelease):
            vk = hid_to_windows(event.scancode)
            if vk is not None:
                _send(_make_kb_input(vk, KEYEVENTF_KEYUP))

    def warp(self, x: int, y: int) -> None:
        user32.SetCursorPos(x, y)

    def cursor_position(self) -> tuple[int, int] | None:
        pt = ctypes.wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return pt.x, pt.y
