"""Platform detection and backend factory functions.

Lazily imports platform-specific modules so they are only loaded when
actually needed (avoids import errors on the wrong OS).
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mouse_share.capture.base import CaptureBackend
    from mouse_share.emulate.base import EmulateBackend


def create_capture_backend() -> CaptureBackend:
    """Create the appropriate capture backend for the current platform."""
    if sys.platform == "win32":
        from mouse_share.capture.windows import WindowsCapture

        return WindowsCapture()

    if sys.platform == "linux":
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            raise RuntimeError(
                "Wayland capture is not yet supported. "
                "Run under X11 or Xwayland (XDG_SESSION_TYPE=x11)."
            )
        from mouse_share.capture.linux_x11 import X11Capture

        return X11Capture()

    if sys.platform == "darwin":
        raise RuntimeError("macOS capture is not yet implemented.")

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def create_emulate_backend() -> EmulateBackend:
    """Create the appropriate emulation backend for the current platform."""
    if sys.platform == "win32":
        from mouse_share.emulate.windows import WindowsEmulate

        return WindowsEmulate()

    if sys.platform == "linux":
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            raise RuntimeError(
                "Wayland emulation is not yet supported. "
                "Run under X11 or Xwayland (XDG_SESSION_TYPE=x11)."
            )
        from mouse_share.emulate.linux_x11 import X11Emulate

        return X11Emulate()

    if sys.platform == "darwin":
        raise RuntimeError("macOS emulation is not yet implemented.")

    raise RuntimeError(f"Unsupported platform: {sys.platform}")
