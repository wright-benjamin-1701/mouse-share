"""Screen arrangement editor — drag connected peers around the local screens.

The scene works in layout pixels: local monitors sit at their native
desktop coordinates, and each peer's monitors at native + offset. Each peer
moves as one block and snaps flush against a local monitor on release.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mouse_share.edge.layout import snap_offset

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QCloseEvent, QResizeEvent

    from mouse_share.app import App, LayoutSnapshot, PeerLayout
    from mouse_share.screen import MonitorInfo

_LOCAL_COLOR = QColor("#9e9e9e")
_PEER_COLORS = [QColor(c) for c in ("#4f8ff7", "#43a86b", "#e08a3c", "#a463d8", "#d65a6f")]


class LayoutBridge(QObject):
    """Carries layout snapshots from the event-loop thread to the Qt thread."""

    changed = Signal(object)


def _monitor_item(mon: MonitorInfo, x: int, y: int, color: QColor, label: str) -> QGraphicsRectItem:
    rect = QGraphicsRectItem(QRectF(x, y, mon.width, mon.height))
    rect.setBrush(QBrush(color.lighter(130)))
    pen = QPen(color.darker(150))
    pen.setCosmetic(True)
    pen.setWidth(2)
    rect.setPen(pen)
    text = QGraphicsSimpleTextItem(f"{label}\n{mon.width}×{mon.height}", rect)
    text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
    text.setPos(x + mon.width * 0.05, y + mon.height * 0.05)
    return rect


class _PeerGroup(QGraphicsItemGroup):
    """A peer's monitors, dragged together and snapped on release."""

    def __init__(
        self,
        peer: PeerLayout,
        local: list[MonitorInfo],
        color: QColor,
        on_release: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_release = on_release
        self.peer_id = peer.peer_id
        self.base_offset = (peer.offset_x, peer.offset_y)
        self._monitors = list(peer.monitors)
        self._local = local
        for idx, mon in enumerate(peer.monitors):
            label = f"{peer.peer_id}" if len(peer.monitors) == 1 else f"{peer.peer_id} #{idx}"
            self.addToGroup(_monitor_item(
                mon, mon.x + peer.offset_x, mon.y + peer.offset_y, color, label,
            ))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(1)

    @property
    def offset(self) -> tuple[int, int]:
        pos = self.pos()
        return (self.base_offset[0] + round(pos.x()), self.base_offset[1] + round(pos.y()))

    def set_offset(self, offset: tuple[int, int]) -> None:
        self.setPos(offset[0] - self.base_offset[0], offset[1] - self.base_offset[1])

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802 (Qt override)
        super().mouseReleaseEvent(event)
        self.set_offset(snap_offset(self._local, self._monitors, *self.offset))
        self._on_release()


class ArrangeWindow(QWidget):
    """Shows local and peer monitors; Apply sends moved peers to the app."""

    def __init__(self, app: App, on_close: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._app = app
        self._on_close = on_close
        self._groups: dict[str, _PeerGroup] = {}
        self._deferred: LayoutSnapshot | None = None  # arrived mid-drag
        self.setWindowTitle("mouse-share — Arrange screens")
        self.resize(720, 460)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hint = QLabel()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(lambda: self._rebuild(self._app.layout_snapshot(), keep=False))

        buttons = QHBoxLayout()
        buttons.addWidget(self._hint, 1)
        buttons.addWidget(reset_btn)
        buttons.addWidget(apply_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)

        # Emitted on the event-loop thread; a slot on this widget makes the
        # connection queued, so the rebuild runs on the Qt thread.
        self._bridge = LayoutBridge()
        self._bridge.changed.connect(self._on_layout_changed)
        app.add_layout_listener(self._bridge.changed.emit)
        self._rebuild(app.layout_snapshot(), keep=False)

    @Slot(object)
    def _on_layout_changed(self, snapshot: LayoutSnapshot) -> None:
        if self._scene.mouseGrabberItem() is not None:
            self._deferred = snapshot  # don't delete the item being dragged
            return
        self._rebuild(snapshot, keep=True)

    def _on_drag_released(self) -> None:
        if self._deferred is not None:
            snapshot, self._deferred = self._deferred, None
            self._rebuild(snapshot, keep=True)

    def _rebuild(self, snapshot: LayoutSnapshot, *, keep: bool) -> None:
        """Redraw from *snapshot*; with *keep*, unapplied drags survive."""
        pending = {
            pid: (g.base_offset, g.offset) for pid, g in self._groups.items()
            if keep and g.offset != g.base_offset
        }
        self._scene.clear()
        self._groups.clear()
        local = list(snapshot.local)

        for idx, mon in enumerate(local):
            item = _monitor_item(mon, mon.x, mon.y, _LOCAL_COLOR, f"This PC #{idx}: {mon.name}")
            self._scene.addItem(item)

        for idx, peer in enumerate(snapshot.peers):
            group = _PeerGroup(
                peer, local, _PEER_COLORS[idx % len(_PEER_COLORS)], self._on_drag_released,
            )
            self._scene.addItem(group)
            self._groups[peer.peer_id] = group
            base, moved = pending.get(peer.peer_id, (None, None))
            if moved is not None and base == group.base_offset:
                group.set_offset(moved)

        self._hint.setText(
            "Drag a computer to any side, then Apply." if snapshot.peers
            else "No computers connected — connect a peer to arrange it.",
        )
        # Leave room to drag a peer anywhere around the local screens
        bounds = self._scene.itemsBoundingRect()
        margin = max(bounds.width(), bounds.height()) * 0.5
        self._scene.setSceneRect(bounds.adjusted(-margin, -margin, margin, margin))
        self._fit()

    def _apply(self) -> None:
        for group in self._groups.values():
            if group.offset != group.base_offset:
                self._app.request_placement(group.peer_id, *group.offset)

    def _fit(self) -> None:
        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._fit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)
