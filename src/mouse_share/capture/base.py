"""Protocol definitions for input capture backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from mouse_share.event.types import InputEvent


@runtime_checkable
class CaptureBackend(Protocol):
    """Platform-specific input capture.

    The capture backend runs in a dedicated OS thread (message pump on Windows,
    XRecord on Linux). Events are delivered via the *on_event* callback passed
    to ``start``.

    Suppression is independent of start/stop — the backend always captures, but
    ``set_suppressing(True)`` prevents events from reaching the local OS (used
    when forwarding to a remote peer).
    """

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        """Begin capturing input events, delivering them to *on_event*."""
        ...

    def stop(self) -> None:
        """Stop capturing and release all OS resources."""
        ...

    def set_suppressing(self, suppressing: bool) -> None:
        """Toggle whether captured events are suppressed from the local OS."""
        ...

    def set_escape_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback fired when the escape hotkey (Ctrl+Alt+Esc) is detected."""
        ...

    def cursor_position(self) -> tuple[int, int] | None:
        """Current cursor position in desktop coordinates, or None if unknown."""
        ...
