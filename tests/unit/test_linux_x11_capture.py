"""Tests for capture/linux_x11.py — keycode offset, button mapping.

These tests only run on Linux with python-xlib available.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")


class TestKeycodeOffset:
    """X11 keycode = evdev keycode + 8."""

    def test_evdev_to_x11_offset(self) -> None:
        # evdev KEY_A = 30, X11 keycode should be 38
        from mouse_share.event.scancode import HID_A, evdev_to_hid

        hid = evdev_to_hid(30)
        assert hid == HID_A

    def test_x11_keycode_minus_8_gives_evdev(self) -> None:
        from mouse_share.event.scancode import HID_A, evdev_to_hid

        x11_keycode = 38  # KEY_A on X11
        evdev_code = x11_keycode - 8
        assert evdev_to_hid(evdev_code) == HID_A


class TestButtonMapping:
    def test_x11_button_map_covers_standard_buttons(self) -> None:
        from mouse_share.capture.linux_x11 import _X11_BUTTON_MAP
        from mouse_share.event.types import MouseButtonCode

        # Standard buttons: left(1), middle(2), right(3)
        assert _X11_BUTTON_MAP[1] == MouseButtonCode.LEFT
        assert _X11_BUTTON_MAP[2] == MouseButtonCode.MIDDLE
        assert _X11_BUTTON_MAP[3] == MouseButtonCode.RIGHT

    def test_scroll_buttons_not_in_button_map(self) -> None:
        from mouse_share.capture.linux_x11 import _X11_BUTTON_MAP

        # Scroll buttons (4,5,6,7) should NOT be in the button map
        # because they're handled as scroll events
        assert 4 not in _X11_BUTTON_MAP
        assert 5 not in _X11_BUTTON_MAP
        assert 6 not in _X11_BUTTON_MAP
        assert 7 not in _X11_BUTTON_MAP

    def test_back_forward_buttons(self) -> None:
        from mouse_share.capture.linux_x11 import _X11_BUTTON_MAP
        from mouse_share.event.types import MouseButtonCode

        assert _X11_BUTTON_MAP[8] == MouseButtonCode.BACK
        assert _X11_BUTTON_MAP[9] == MouseButtonCode.FORWARD
