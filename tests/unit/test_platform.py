"""Tests for platform.py — mock sys.platform for backend selection."""

from unittest.mock import patch

import pytest

from mouse_share.platform import create_capture_backend, create_emulate_backend


class TestPlatformDetection:
    def test_unsupported_platform_capture(self) -> None:
        with patch("mouse_share.platform.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            with pytest.raises(RuntimeError, match="Unsupported platform"):
                create_capture_backend()

    def test_unsupported_platform_emulate(self) -> None:
        with patch("mouse_share.platform.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            with pytest.raises(RuntimeError, match="Unsupported platform"):
                create_emulate_backend()

    def test_darwin_not_implemented_capture(self) -> None:
        with patch("mouse_share.platform.sys") as mock_sys:
            mock_sys.platform = "darwin"
            with pytest.raises(RuntimeError, match="macOS"):
                create_capture_backend()

    def test_darwin_not_implemented_emulate(self) -> None:
        with patch("mouse_share.platform.sys") as mock_sys:
            mock_sys.platform = "darwin"
            with pytest.raises(RuntimeError, match="macOS"):
                create_emulate_backend()

    def test_wayland_not_supported_capture(self) -> None:
        with (
            patch("mouse_share.platform.sys") as mock_sys,
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}),
        ):
            mock_sys.platform = "linux"
            with pytest.raises(RuntimeError, match="Wayland"):
                create_capture_backend()

    def test_wayland_not_supported_emulate(self) -> None:
        with (
            patch("mouse_share.platform.sys") as mock_sys,
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}),
        ):
            mock_sys.platform = "linux"
            with pytest.raises(RuntimeError, match="Wayland"):
                create_emulate_backend()
