"""Tests for emulate/linux_x11.py — keycode conversion, button mapping, scroll synthesis.

These tests only run on Linux with python-xlib available.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")


class TestHidToX11Keycode:
    def test_hid_a_to_x11(self) -> None:
        from mouse_share.emulate.linux_x11 import X11Emulate
        from mouse_share.event.scancode import HID_A

        keycode = X11Emulate._hid_to_x11_keycode(HID_A)
        assert keycode == 38  # evdev 30 + 8

    def test_unknown_hid_returns_none(self) -> None:
        from mouse_share.emulate.linux_x11 import X11Emulate

        assert X11Emulate._hid_to_x11_keycode(0xFF) is None


class TestButtonMapping:
    def test_all_standard_buttons_mapped(self) -> None:
        from mouse_share.emulate.linux_x11 import _BUTTON_MAP
        from mouse_share.event.types import MouseButtonCode

        for btn in MouseButtonCode:
            assert btn in _BUTTON_MAP, f"Missing mapping for {btn}"

    def test_left_button_is_1(self) -> None:
        from mouse_share.emulate.linux_x11 import _BUTTON_MAP
        from mouse_share.event.types import MouseButtonCode

        assert _BUTTON_MAP[MouseButtonCode.LEFT] == 1

    def test_right_button_is_3(self) -> None:
        from mouse_share.emulate.linux_x11 import _BUTTON_MAP
        from mouse_share.event.types import MouseButtonCode

        assert _BUTTON_MAP[MouseButtonCode.RIGHT] == 3


class TestMouseMove:
    def test_relative_motion_args(self, monkeypatch) -> None:
        """fake_input takes x/y (not root_x/root_y); detail=1 means relative."""
        import inspect
        from unittest.mock import MagicMock

        from Xlib import X
        from Xlib.ext import xtest

        import mouse_share.emulate.linux_x11 as mod
        from mouse_share.event.types import MouseMove

        fake = MagicMock()
        fake.__signature__ = inspect.signature(xtest.fake_input)
        monkeypatch.setattr(mod.xtest, "fake_input", fake)

        emu = mod.X11Emulate()
        emu._display = MagicMock()
        emu.inject(MouseMove(dx=-5, dy=7))

        args, kwargs = fake.call_args
        inspect.signature(xtest.fake_input).bind(*args, **kwargs)
        assert args[1] == X.MotionNotify
        assert kwargs == {"detail": 1, "x": -5, "y": 7}
