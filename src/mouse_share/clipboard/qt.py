"""Clipboard access through Qt, for text sharing between peers.

QClipboard must be used on the Qt (main) thread. ``set_text`` may be called
from any thread; it is forwarded through a queued signal. Local changes are
reported to the callback on the Qt thread.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


class QtClipboard(QObject):
    """Watches the system clipboard and sets it on request.

    Text that came from a peer is remembered, so the change notification
    it causes is not sent straight back (or on to the next peer twice).
    Create on the Qt thread, after the QGuiApplication.
    """

    _set_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._clipboard = QGuiApplication.clipboard()
        self._on_change: Callable[[str], None] | None = None
        self._last: str | None = None  # last text known to be in sync
        self._set_requested.connect(self._set_on_qt_thread)
        self._clipboard.dataChanged.connect(self._on_data_changed)

    def start(self, on_change: Callable[[str], None]) -> None:
        """Report local text changes to *on_change* (called on the Qt thread)."""
        self._on_change = on_change

    def set_text(self, text: str) -> None:
        """Replace the clipboard text; safe to call from any thread."""
        self._set_requested.emit(text)

    @Slot(str)
    def _set_on_qt_thread(self, text: str) -> None:
        self._last = text
        self._clipboard.setText(text)

    @Slot()
    def _on_data_changed(self) -> None:
        text = self._clipboard.text()
        # Non-text content (images, files) reads as ""; X11 also re-signals
        # on ownership changes without new content.
        if not text or text == self._last:
            return
        self._last = text
        if self._on_change is not None:
            self._on_change(text)
