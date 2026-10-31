"""Tests for emulate/windows.py — INPUT struct packing.

These tests only run on Windows.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


class TestInputPacking:
    def test_make_mouse_input(self) -> None:
        from mouse_share.emulate.windows import INPUT_MOUSE, MOUSEEVENTF_MOVE, _make_mouse_input

        inp = _make_mouse_input(10, -5, MOUSEEVENTF_MOVE)
        assert inp.type == INPUT_MOUSE
        assert inp.union.mi.dx == 10
        assert inp.union.mi.dy == -5
        assert inp.union.mi.dwFlags == MOUSEEVENTF_MOVE

    def test_make_kb_input(self) -> None:
        from mouse_share.emulate.windows import INPUT_KEYBOARD, KEYEVENTF_KEYUP, _make_kb_input

        inp = _make_kb_input(0x41, KEYEVENTF_KEYUP)
        assert inp.type == INPUT_KEYBOARD
        assert inp.union.ki.wVk == 0x41
        assert inp.union.ki.dwFlags == KEYEVENTF_KEYUP

    def test_make_kb_input_keydown(self) -> None:
        from mouse_share.emulate.windows import INPUT_KEYBOARD, _make_kb_input

        inp = _make_kb_input(0x41)
        assert inp.type == INPUT_KEYBOARD
        assert inp.union.ki.wVk == 0x41
        assert inp.union.ki.dwFlags == 0

    def test_button_flag_tables_complete(self) -> None:
        from mouse_share.emulate.windows import _BUTTON_DOWN_FLAGS, _BUTTON_UP_FLAGS
        from mouse_share.event.types import MouseButtonCode

        for btn in MouseButtonCode:
            assert btn in _BUTTON_DOWN_FLAGS, f"Missing down flags for {btn}"
            assert btn in _BUTTON_UP_FLAGS, f"Missing up flags for {btn}"
