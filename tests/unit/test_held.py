"""Tests for held key/button tracking."""

from mouse_share.event.held import HeldInput
from mouse_share.event.types import KeyPress, KeyRelease, MouseButton, MouseButtonCode, MouseMove


def test_tracks_presses_and_releases() -> None:
    held = HeldInput()
    held.update(KeyPress(scancode=0xE0))  # left ctrl
    held.update(MouseButton(MouseButtonCode.LEFT, pressed=True))
    held.update(MouseMove(dx=5, dy=0))
    assert held.keys == {0xE0}
    assert held.buttons == {MouseButtonCode.LEFT}

    held.update(MouseButton(MouseButtonCode.LEFT, pressed=False))
    held.update(KeyRelease(scancode=0xE0))
    assert not held.keys
    assert not held.buttons


def test_release_events_releases_everything_once() -> None:
    held = HeldInput()
    held.update(KeyPress(scancode=0x06))
    held.update(KeyPress(scancode=0xE0))
    held.update(MouseButton(MouseButtonCode.RIGHT, pressed=True))

    assert held.release_events() == [
        MouseButton(MouseButtonCode.RIGHT, pressed=False),
        KeyRelease(scancode=0x06),
        KeyRelease(scancode=0xE0),
    ]
    assert held.release_events() == []


def test_release_without_press_is_ignored() -> None:
    held = HeldInput()
    held.update(KeyRelease(scancode=0x04))
    held.update(MouseButton(MouseButtonCode.LEFT, pressed=False))
    assert held.release_events() == []
