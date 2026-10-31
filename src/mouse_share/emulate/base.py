"""Protocol definitions for input emulation backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mouse_share.event.types import InputEvent


@runtime_checkable
class EmulateBackend(Protocol):
    """Platform-specific input emulation.

    Injects input events into the local OS so they appear as real
    keyboard/mouse activity.
    """

    def start(self) -> None:
        """Initialise any OS resources needed for injection."""
        ...

    def stop(self) -> None:
        """Release OS resources."""
        ...

    def inject(self, event: InputEvent) -> None:
        """Inject a single input event into the local OS."""
        ...

    def warp(self, x: int, y: int) -> None:
        """Move the cursor to absolute desktop coordinates (*x*, *y*)."""
        ...

    def cursor_position(self) -> tuple[int, int] | None:
        """Cursor position after previously injected events, or None if unknown."""
        ...
