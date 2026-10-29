"""Tests for event type dataclasses."""

import pytest

from mouse_share.event.types import (
    EventType,
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
    MouseMove,
    MouseScroll,
)


def test_mouse_move_frozen() -> None:
    m = MouseMove(dx=10, dy=-5)
    assert m.dx == 10
    assert m.dy == -5
    assert m.event_type == EventType.MOUSE_MOVE
    with pytest.raises(AttributeError):
        m.dx = 20  # type: ignore[misc]


def test_mouse_button() -> None:
    b = MouseButton(button=MouseButtonCode.LEFT, pressed=True)
    assert b.button == MouseButtonCode.LEFT
    assert b.pressed is True
    assert b.event_type == EventType.MOUSE_BUTTON


def test_mouse_scroll() -> None:
    s = MouseScroll(dx=0, dy=-120)
    assert s.dy == -120
    assert s.event_type == EventType.MOUSE_SCROLL


def test_key_press_release() -> None:
    kp = KeyPress(scancode=0x04)
    kr = KeyRelease(scancode=0x04)
    assert kp.event_type == EventType.KEY_PRESS
    assert kr.event_type == EventType.KEY_RELEASE
    assert kp.scancode == kr.scancode
