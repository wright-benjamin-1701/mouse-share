"""Tests for screen.py — multi-monitor detection with mocked platform APIs."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from mouse_share.screen import MonitorInfo, detect_monitors


class TestDetectMonitors:
    @patch("mouse_share.screen.sys")
    def test_fallback_on_unsupported_platform(self, mock_sys: MagicMock) -> None:
        mock_sys.platform = "freebsd"
        assert detect_monitors() == []

    @patch("mouse_share.screen.sys")
    @patch("mouse_share.screen._detect_x11")
    def test_calls_x11_on_linux(self, mock_x11: MagicMock, mock_sys: MagicMock) -> None:
        mock_sys.platform = "linux"
        expected = [MonitorInfo("HDMI-1", 0, 0, 1920, 1080, True)]
        mock_x11.return_value = expected
        result = detect_monitors()
        assert result == expected
        mock_x11.assert_called_once()

    @patch("mouse_share.screen.sys")
    @patch("mouse_share.screen._detect_windows")
    def test_calls_windows_on_win32(self, mock_win: MagicMock, mock_sys: MagicMock) -> None:
        mock_sys.platform = "win32"
        expected = [MonitorInfo(r"\\.\DISPLAY1", 0, 0, 1920, 1080, True)]
        mock_win.return_value = expected
        result = detect_monitors()
        assert result == expected
        mock_win.assert_called_once()

    @patch("mouse_share.screen.sys")
    @patch("mouse_share.screen._detect_x11", side_effect=ImportError("no Xlib"))
    def test_returns_empty_on_exception(self, _mock_x11: MagicMock, mock_sys: MagicMock) -> None:
        mock_sys.platform = "linux"
        assert detect_monitors() == []


class TestDetectX11:
    def test_two_monitors_skip_inactive(self) -> None:
        """Mock Xlib RandR to return two active CRTCs and one inactive."""
        mock_display_instance = MagicMock()
        mock_root = MagicMock()
        mock_display_instance.screen.return_value.root = mock_root

        # Screen resources
        mock_res = MagicMock()
        mock_res.outputs = [101, 102, 103]
        mock_res.crtcs = [1, 2, 3]
        mock_res.config_timestamp = 12345

        # Output info — can't use MagicMock(name=...) because `name` is a
        # special MagicMock constructor arg, so set .name after creation.
        oi_101 = MagicMock()
        oi_101.name = "HDMI-1"
        oi_102 = MagicMock()
        oi_102.name = "DP-1"
        oi_103 = MagicMock()
        oi_103.name = "VGA-1"
        output_infos = {101: oi_101, 102: oi_102, 103: oi_103}

        # Primary output
        mock_primary = MagicMock()
        mock_primary.output = 101

        # CRTC info: two active, one inactive
        crtc_infos = {
            1: MagicMock(x=0, y=0, width=1920, height=1080, outputs=[101]),
            2: MagicMock(x=1920, y=0, width=2560, height=1440, outputs=[102]),
            3: MagicMock(x=0, y=0, width=0, height=0, outputs=[103]),  # inactive
        }

        # Build mock Xlib modules
        mock_randr = MagicMock()
        mock_randr.get_screen_resources.return_value = mock_res
        mock_randr.get_output_primary.return_value = mock_primary
        mock_randr.get_output_info.side_effect = lambda _root, oid, _ts: output_infos[oid]
        mock_randr.get_crtc_info.side_effect = lambda _root, cid, _ts: crtc_infos[cid]

        mock_xdisplay = MagicMock()
        mock_xdisplay.Display.return_value = mock_display_instance

        # Inject fake Xlib modules into sys.modules so the local import resolves
        fake_xlib = ModuleType("Xlib")
        fake_xlib_display = mock_xdisplay
        fake_xlib_ext = ModuleType("Xlib.ext")
        fake_xlib_ext_randr = mock_randr

        modules_patch = {
            "Xlib": fake_xlib,
            "Xlib.display": fake_xlib_display,
            "Xlib.ext": fake_xlib_ext,
            "Xlib.ext.randr": fake_xlib_ext_randr,
        }

        with patch.dict(sys.modules, modules_patch):
            # Re-import to pick up the patched modules
            from mouse_share.screen import _detect_x11
            result = _detect_x11()

        assert len(result) == 2
        assert result[0] == MonitorInfo("HDMI-1", 0, 0, 1920, 1080, True)
        assert result[1] == MonitorInfo("DP-1", 1920, 0, 2560, 1440, False)
