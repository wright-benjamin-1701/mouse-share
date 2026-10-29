"""Tests for scancode mapping tables."""

from mouse_share.event.scancode import (
    HID_A,
    HID_ENTER,
    HID_ESCAPE,
    HID_LCTRL,
    HID_SPACE,
    evdev_to_hid,
    hid_to_evdev,
    hid_to_macos,
    hid_to_windows,
    macos_to_hid,
    windows_to_hid,
)


class TestEvdevMapping:
    def test_a_key(self) -> None:
        assert evdev_to_hid(30) == HID_A

    def test_escape(self) -> None:
        assert evdev_to_hid(1) == HID_ESCAPE

    def test_enter(self) -> None:
        assert evdev_to_hid(28) == HID_ENTER

    def test_round_trip(self) -> None:
        assert hid_to_evdev(evdev_to_hid(30)) == 30  # type: ignore[arg-type]

    def test_unknown_returns_none(self) -> None:
        assert evdev_to_hid(9999) is None
        assert hid_to_evdev(0xFF) is None


class TestMacOSMapping:
    def test_a_key(self) -> None:
        assert macos_to_hid(0x00) == HID_A

    def test_space(self) -> None:
        assert macos_to_hid(0x31) == HID_SPACE

    def test_round_trip(self) -> None:
        assert hid_to_macos(macos_to_hid(0x00)) == 0x00  # type: ignore[arg-type]

    def test_unknown_returns_none(self) -> None:
        assert macos_to_hid(0xFF) is None


class TestWindowsMapping:
    def test_a_key(self) -> None:
        assert windows_to_hid(0x41) == HID_A

    def test_ctrl(self) -> None:
        assert windows_to_hid(0x11) == HID_LCTRL

    def test_round_trip(self) -> None:
        assert hid_to_windows(windows_to_hid(0x41)) == 0x41  # type: ignore[arg-type]

    def test_unknown_returns_none(self) -> None:
        assert windows_to_hid(0x00) is None


class TestCrossplatformConsistency:
    def test_a_maps_to_same_hid(self) -> None:
        """All platforms should map their 'A' key to the same HID code."""
        assert evdev_to_hid(30) == macos_to_hid(0x00) == windows_to_hid(0x41) == HID_A

    def test_space_maps_to_same_hid(self) -> None:
        assert evdev_to_hid(57) == macos_to_hid(0x31) == windows_to_hid(0x20) == HID_SPACE

    def test_enter_maps_to_same_hid(self) -> None:
        assert evdev_to_hid(28) == macos_to_hid(0x24) == windows_to_hid(0x0D) == HID_ENTER
