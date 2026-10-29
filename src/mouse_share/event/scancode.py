"""USB HID scancode ↔ platform keycode mapping tables.

The canonical keycode space is USB HID Usage Tables (Keyboard/Keypad page 0x07).
Each platform maps to/from this space, giving N×2 mappings instead of N×N.

References:
- USB HID Usage Tables 1.4, Section 10 (Keyboard/Keypad Page)
- Linux: include/uapi/linux/input-event-codes.h
- macOS: Carbon HIToolbox/Events.h (kVK_* constants)
- Windows: WinUser.h (VK_* constants)
"""

from __future__ import annotations

# USB HID scancode constants (Keyboard/Keypad page 0x07)
# fmt: off
HID_A           = 0x04
HID_B           = 0x05
HID_C           = 0x06
HID_D           = 0x07
HID_E           = 0x08
HID_F           = 0x09
HID_G           = 0x0A
HID_H           = 0x0B
HID_I           = 0x0C
HID_J           = 0x0D
HID_K           = 0x0E
HID_L           = 0x0F
HID_M           = 0x10
HID_N           = 0x11
HID_O           = 0x12
HID_P           = 0x13
HID_Q           = 0x14
HID_R           = 0x15
HID_S           = 0x16
HID_T           = 0x17
HID_U           = 0x18
HID_V           = 0x19
HID_W           = 0x1A
HID_X           = 0x1B
HID_Y           = 0x1C
HID_Z           = 0x1D
HID_1           = 0x1E
HID_2           = 0x1F
HID_3           = 0x20
HID_4           = 0x21
HID_5           = 0x22
HID_6           = 0x23
HID_7           = 0x24
HID_8           = 0x25
HID_9           = 0x26
HID_0           = 0x27
HID_ENTER       = 0x28
HID_ESCAPE      = 0x29
HID_BACKSPACE   = 0x2A
HID_TAB         = 0x2B
HID_SPACE       = 0x2C
HID_MINUS       = 0x2D
HID_EQUAL       = 0x2E
HID_LBRACKET    = 0x2F
HID_RBRACKET    = 0x30
HID_BACKSLASH   = 0x31
HID_SEMICOLON   = 0x33
HID_APOSTROPHE  = 0x34
HID_GRAVE       = 0x35
HID_COMMA       = 0x36
HID_PERIOD      = 0x37
HID_SLASH       = 0x38
HID_CAPSLOCK    = 0x39
HID_F1          = 0x3A
HID_F2          = 0x3B
HID_F3          = 0x3C
HID_F4          = 0x3D
HID_F5          = 0x3E
HID_F6          = 0x3F
HID_F7          = 0x40
HID_F8          = 0x41
HID_F9          = 0x42
HID_F10         = 0x43
HID_F11         = 0x44
HID_F12         = 0x45
HID_PRINTSCREEN = 0x46
HID_SCROLLLOCK  = 0x47
HID_PAUSE       = 0x48
HID_INSERT      = 0x49
HID_HOME        = 0x4A
HID_PAGEUP      = 0x4B
HID_DELETE      = 0x4C
HID_END         = 0x4D
HID_PAGEDOWN    = 0x4E
HID_RIGHT       = 0x4F
HID_LEFT        = 0x50
HID_DOWN        = 0x51
HID_UP          = 0x52
HID_NUMLOCK     = 0x53
HID_KP_DIVIDE   = 0x54
HID_KP_MULTIPLY = 0x55
HID_KP_MINUS    = 0x56
HID_KP_PLUS     = 0x57
HID_KP_ENTER    = 0x58
HID_KP_1        = 0x59
HID_KP_2        = 0x5A
HID_KP_3        = 0x5B
HID_KP_4        = 0x5C
HID_KP_5        = 0x5D
HID_KP_6        = 0x5E
HID_KP_7        = 0x5F
HID_KP_8        = 0x60
HID_KP_9        = 0x61
HID_KP_0        = 0x62
HID_KP_PERIOD   = 0x63
HID_LCTRL       = 0xE0
HID_LSHIFT      = 0xE1
HID_LALT        = 0xE2
HID_LMETA       = 0xE3
HID_RCTRL       = 0xE4
HID_RSHIFT      = 0xE5
HID_RALT        = 0xE6
HID_RMETA       = 0xE7
# fmt: on

# ---------------------------------------------------------------------------
# Linux evdev keycode → USB HID scancode
# Source: linux/input-event-codes.h (KEY_* constants)
# ---------------------------------------------------------------------------
_EVDEV_TO_HID: dict[int, int] = {
    1: HID_ESCAPE, 2: HID_1, 3: HID_2, 4: HID_3, 5: HID_4,
    6: HID_5, 7: HID_6, 8: HID_7, 9: HID_8, 10: HID_9,
    11: HID_0, 12: HID_MINUS, 13: HID_EQUAL, 14: HID_BACKSPACE,
    15: HID_TAB, 16: HID_Q, 17: HID_W, 18: HID_E, 19: HID_R,
    20: HID_T, 21: HID_Y, 22: HID_U, 23: HID_I, 24: HID_O,
    25: HID_P, 26: HID_LBRACKET, 27: HID_RBRACKET, 28: HID_ENTER,
    29: HID_LCTRL, 30: HID_A, 31: HID_S, 32: HID_D, 33: HID_F,
    34: HID_G, 35: HID_H, 36: HID_J, 37: HID_K, 38: HID_L,
    39: HID_SEMICOLON, 40: HID_APOSTROPHE, 41: HID_GRAVE,
    42: HID_LSHIFT, 43: HID_BACKSLASH, 44: HID_Z, 45: HID_X,
    46: HID_C, 47: HID_V, 48: HID_B, 49: HID_N, 50: HID_M,
    51: HID_COMMA, 52: HID_PERIOD, 53: HID_SLASH, 54: HID_RSHIFT,
    55: HID_KP_MULTIPLY, 56: HID_LALT, 57: HID_SPACE, 58: HID_CAPSLOCK,
    59: HID_F1, 60: HID_F2, 61: HID_F3, 62: HID_F4, 63: HID_F5,
    64: HID_F6, 65: HID_F7, 66: HID_F8, 67: HID_F9, 68: HID_F10,
    69: HID_NUMLOCK, 70: HID_SCROLLLOCK, 71: HID_KP_7, 72: HID_KP_8,
    73: HID_KP_9, 74: HID_KP_MINUS, 75: HID_KP_4, 76: HID_KP_5,
    77: HID_KP_6, 78: HID_KP_PLUS, 79: HID_KP_1, 80: HID_KP_2,
    81: HID_KP_3, 82: HID_KP_0, 83: HID_KP_PERIOD,
    87: HID_F11, 88: HID_F12,
    96: HID_KP_ENTER, 97: HID_RCTRL, 98: HID_KP_DIVIDE,
    99: HID_PRINTSCREEN, 100: HID_RALT,
    102: HID_HOME, 103: HID_UP, 104: HID_PAGEUP, 105: HID_LEFT,
    106: HID_RIGHT, 107: HID_END, 108: HID_DOWN, 109: HID_PAGEDOWN,
    110: HID_INSERT, 111: HID_DELETE,
    119: HID_PAUSE,
    125: HID_LMETA, 126: HID_RMETA,
}

# ---------------------------------------------------------------------------
# macOS virtual keycode (kVK_*) → USB HID scancode
# Source: Carbon HIToolbox/Events.h
# ---------------------------------------------------------------------------
_MACOS_TO_HID: dict[int, int] = {
    0x00: HID_A, 0x01: HID_S, 0x02: HID_D, 0x03: HID_F,
    0x04: HID_H, 0x05: HID_G, 0x06: HID_Z, 0x07: HID_X,
    0x08: HID_C, 0x09: HID_V, 0x0B: HID_B, 0x0C: HID_Q,
    0x0D: HID_W, 0x0E: HID_E, 0x0F: HID_R, 0x10: HID_Y,
    0x11: HID_T, 0x12: HID_1, 0x13: HID_2, 0x14: HID_3,
    0x15: HID_4, 0x16: HID_6, 0x17: HID_5, 0x18: HID_EQUAL,
    0x19: HID_9, 0x1A: HID_7, 0x1B: HID_MINUS, 0x1C: HID_8,
    0x1D: HID_0, 0x1E: HID_RBRACKET, 0x1F: HID_O, 0x20: HID_U,
    0x21: HID_LBRACKET, 0x22: HID_I, 0x23: HID_P,
    0x24: HID_ENTER, 0x25: HID_L, 0x26: HID_J, 0x27: HID_APOSTROPHE,
    0x28: HID_K, 0x29: HID_SEMICOLON, 0x2A: HID_BACKSLASH,
    0x2B: HID_COMMA, 0x2C: HID_SLASH, 0x2D: HID_N, 0x2E: HID_M,
    0x2F: HID_PERIOD, 0x30: HID_TAB, 0x31: HID_SPACE,
    0x32: HID_GRAVE, 0x33: HID_BACKSPACE, 0x35: HID_ESCAPE,
    0x36: HID_RMETA, 0x37: HID_LMETA, 0x38: HID_LSHIFT,
    0x39: HID_CAPSLOCK, 0x3A: HID_LALT, 0x3B: HID_LCTRL,
    0x3C: HID_RSHIFT, 0x3D: HID_RALT, 0x3E: HID_RCTRL,
    0x41: HID_KP_PERIOD, 0x43: HID_KP_MULTIPLY,
    0x45: HID_KP_PLUS, 0x47: HID_NUMLOCK,
    0x4B: HID_KP_DIVIDE, 0x4C: HID_KP_ENTER, 0x4E: HID_KP_MINUS,
    0x51: HID_KP_ENTER, 0x52: HID_KP_0, 0x53: HID_KP_1,
    0x54: HID_KP_2, 0x55: HID_KP_3, 0x56: HID_KP_4,
    0x57: HID_KP_5, 0x58: HID_KP_6, 0x59: HID_KP_7,
    0x5B: HID_KP_8, 0x5C: HID_KP_9,
    0x60: HID_F5, 0x61: HID_F6, 0x62: HID_F7, 0x63: HID_F3,
    0x64: HID_F8, 0x65: HID_F9, 0x67: HID_F11, 0x69: HID_PRINTSCREEN,
    0x6B: HID_SCROLLLOCK, 0x6D: HID_F10,
    0x6F: HID_F12, 0x71: HID_PAUSE,
    0x72: HID_INSERT, 0x73: HID_HOME, 0x74: HID_PAGEUP,
    0x75: HID_DELETE, 0x76: HID_F4, 0x77: HID_END,
    0x78: HID_F2, 0x79: HID_PAGEDOWN, 0x7A: HID_F1,
    0x7B: HID_LEFT, 0x7C: HID_RIGHT, 0x7D: HID_DOWN, 0x7E: HID_UP,
}

# ---------------------------------------------------------------------------
# Windows virtual-key code (VK_*) → USB HID scancode
# Source: WinUser.h
# ---------------------------------------------------------------------------
_WINDOWS_TO_HID: dict[int, int] = {
    0x08: HID_BACKSPACE, 0x09: HID_TAB, 0x0D: HID_ENTER,
    0x10: HID_LSHIFT, 0x11: HID_LCTRL, 0x12: HID_LALT,
    0x13: HID_PAUSE, 0x14: HID_CAPSLOCK, 0x1B: HID_ESCAPE,
    0x20: HID_SPACE, 0x21: HID_PAGEUP, 0x22: HID_PAGEDOWN,
    0x23: HID_END, 0x24: HID_HOME, 0x25: HID_LEFT, 0x26: HID_UP,
    0x27: HID_RIGHT, 0x28: HID_DOWN, 0x2C: HID_PRINTSCREEN,
    0x2D: HID_INSERT, 0x2E: HID_DELETE,
    0x30: HID_0, 0x31: HID_1, 0x32: HID_2, 0x33: HID_3,
    0x34: HID_4, 0x35: HID_5, 0x36: HID_6, 0x37: HID_7,
    0x38: HID_8, 0x39: HID_9,
    0x41: HID_A, 0x42: HID_B, 0x43: HID_C, 0x44: HID_D,
    0x45: HID_E, 0x46: HID_F, 0x47: HID_G, 0x48: HID_H,
    0x49: HID_I, 0x4A: HID_J, 0x4B: HID_K, 0x4C: HID_L,
    0x4D: HID_M, 0x4E: HID_N, 0x4F: HID_O, 0x50: HID_P,
    0x51: HID_Q, 0x52: HID_R, 0x53: HID_S, 0x54: HID_T,
    0x55: HID_U, 0x56: HID_V, 0x57: HID_W, 0x58: HID_X,
    0x59: HID_Y, 0x5A: HID_Z,
    0x5B: HID_LMETA, 0x5C: HID_RMETA,
    0x60: HID_KP_0, 0x61: HID_KP_1, 0x62: HID_KP_2, 0x63: HID_KP_3,
    0x64: HID_KP_4, 0x65: HID_KP_5, 0x66: HID_KP_6, 0x67: HID_KP_7,
    0x68: HID_KP_8, 0x69: HID_KP_9,
    0x6A: HID_KP_MULTIPLY, 0x6B: HID_KP_PLUS, 0x6D: HID_KP_MINUS,
    0x6E: HID_KP_PERIOD, 0x6F: HID_KP_DIVIDE,
    0x70: HID_F1, 0x71: HID_F2, 0x72: HID_F3, 0x73: HID_F4,
    0x74: HID_F5, 0x75: HID_F6, 0x76: HID_F7, 0x77: HID_F8,
    0x78: HID_F9, 0x79: HID_F10, 0x7A: HID_F11, 0x7B: HID_F12,
    0x90: HID_NUMLOCK, 0x91: HID_SCROLLLOCK,
    0xA0: HID_LSHIFT, 0xA1: HID_RSHIFT, 0xA2: HID_LCTRL,
    0xA3: HID_RCTRL, 0xA4: HID_LALT, 0xA5: HID_RALT,
    0xBA: HID_SEMICOLON, 0xBB: HID_EQUAL, 0xBC: HID_COMMA,
    0xBD: HID_MINUS, 0xBE: HID_PERIOD, 0xBF: HID_SLASH,
    0xC0: HID_GRAVE, 0xDB: HID_LBRACKET, 0xDC: HID_BACKSLASH,
    0xDD: HID_RBRACKET, 0xDE: HID_APOSTROPHE,
}

# Build reverse lookup tables
_HID_TO_EVDEV: dict[int, int] = {v: k for k, v in _EVDEV_TO_HID.items()}
_HID_TO_MACOS: dict[int, int] = {v: k for k, v in _MACOS_TO_HID.items()}
_HID_TO_WINDOWS: dict[int, int] = {v: k for k, v in _WINDOWS_TO_HID.items()}


def evdev_to_hid(evdev_code: int) -> int | None:
    """Convert Linux evdev keycode to USB HID scancode."""
    return _EVDEV_TO_HID.get(evdev_code)


def hid_to_evdev(hid_code: int) -> int | None:
    """Convert USB HID scancode to Linux evdev keycode."""
    return _HID_TO_EVDEV.get(hid_code)


def macos_to_hid(macos_code: int) -> int | None:
    """Convert macOS virtual keycode to USB HID scancode."""
    return _MACOS_TO_HID.get(macos_code)


def hid_to_macos(hid_code: int) -> int | None:
    """Convert USB HID scancode to macOS virtual keycode."""
    return _HID_TO_MACOS.get(hid_code)


def windows_to_hid(windows_code: int) -> int | None:
    """Convert Windows virtual-key code to USB HID scancode."""
    return _WINDOWS_TO_HID.get(windows_code)


def hid_to_windows(hid_code: int) -> int | None:
    """Convert USB HID scancode to Windows virtual-key code."""
    return _HID_TO_WINDOWS.get(hid_code)
