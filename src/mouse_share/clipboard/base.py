"""Protocol definition for clipboard backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class ClipboardBackend(Protocol):
    """Reads and writes the local clipboard's text."""

    def start(self, on_change: Callable[[str], None]) -> None:
        """Report local text changes to *on_change* (from any thread)."""
        ...

    def set_text(self, text: str) -> None:
        """Replace the clipboard text. Must be safe to call from any thread."""
        ...
