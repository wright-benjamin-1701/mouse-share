"""Multi-monitor detection — auto-detect connected displays on Linux (X11) and Windows."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """A single physical monitor's geometry in desktop coordinates."""

    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool


def detect_monitors() -> list[MonitorInfo]:
    """Auto-detect all connected monitors.

    Returns an empty list on failure or unsupported platforms — the caller
    should fall back to config defaults.
    """
    try:
        if sys.platform == "linux":
            return _detect_x11()
        if sys.platform == "win32":
            return _detect_windows()
    except Exception:
        log.debug("Monitor detection failed", exc_info=True)
    return []


def _detect_x11() -> list[MonitorInfo]:
    """Detect monitors via Xlib RandR extension."""
    from Xlib import display as xdisplay  # type: ignore[import-untyped]
    from Xlib.ext import randr  # type: ignore[import-untyped]

    d = xdisplay.Display()
    try:
        root = d.screen().root
        res = randr.get_screen_resources(root)

        # Map output IDs to names
        output_names: dict[int, str] = {}
        primary_output = randr.get_output_primary(root).output
        for output_id in res.outputs:
            info = randr.get_output_info(root, output_id, res.config_timestamp)
            output_names[output_id] = info.name

        monitors: list[MonitorInfo] = []
        for crtc_id in res.crtcs:
            crtc = randr.get_crtc_info(root, crtc_id, res.config_timestamp)
            if crtc.width == 0 or crtc.height == 0:
                continue  # inactive CRTC

            # Find the output name for this CRTC
            name = "unknown"
            is_primary = False
            for output_id in crtc.outputs:
                if output_id in output_names:
                    name = output_names[output_id]
                    if output_id == primary_output:
                        is_primary = True
                    break

            monitors.append(MonitorInfo(
                name=name,
                x=crtc.x,
                y=crtc.y,
                width=crtc.width,
                height=crtc.height,
                is_primary=is_primary,
            ))

        return monitors
    finally:
        d.close()


def _detect_windows() -> list[MonitorInfo]:
    """Detect monitors via Win32 EnumDisplayMonitors + GetMonitorInfoW."""
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    monitors: list[MonitorInfo] = []

    monitorinfof_primary = 0x00000001

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.wintypes.DWORD),
            ("rcMonitor", ctypes.wintypes.RECT),
            ("rcWork", ctypes.wintypes.RECT),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szDevice", ctypes.c_wchar * 32),
        ]

    monitor_enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )

    def _enum_callback(
        hmonitor: int,
        _hdc: int,
        _lprect: ctypes.wintypes.RECT,
        _lparam: int,
    ) -> int:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rc = info.rcMonitor
            monitors.append(MonitorInfo(
                name=info.szDevice.rstrip("\x00"),
                x=rc.left,
                y=rc.top,
                width=rc.right - rc.left,
                height=rc.bottom - rc.top,
                is_primary=bool(info.dwFlags & monitorinfof_primary),
            ))
        return 1  # continue enumeration

    callback = monitor_enum_proc(_enum_callback)
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return monitors
