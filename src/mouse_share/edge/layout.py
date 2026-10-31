"""Screen layout model and edge-crossing geometry.

Defines how screens are arranged relative to each other and computes
where the cursor should enter an adjacent screen when crossing an edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mouse_share.screen import MonitorInfo


class Edge(Enum):
    """Screen edge direction."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


@dataclass(frozen=True, slots=True)
class ScreenInfo:
    """A peer's screen in the layout grid."""

    peer_id: str
    width: int
    height: int
    x: int = 0
    y: int = 0


@dataclass(frozen=True, slots=True)
class EdgeCrossing:
    """Result of a cursor crossing a screen boundary."""

    target_peer_id: str
    entry_x: int
    entry_y: int
    entry_edge: Edge


class ScreenLayout:
    """Stores screen arrangement and computes edge adjacency.

    Screens are placed in a virtual coordinate space. Adjacency is
    determined by matching edges that overlap in the perpendicular axis.
    """

    def __init__(self) -> None:
        self._screens: dict[str, ScreenInfo] = {}

    def add_screen(self, screen: ScreenInfo) -> None:
        self._screens[screen.peer_id] = screen

    @property
    def screens(self) -> dict[str, ScreenInfo]:
        return dict(self._screens)

    def get_screen(self, peer_id: str) -> ScreenInfo | None:
        return self._screens.get(peer_id)

    def add_peer_monitors(
        self,
        peer_id: str,
        monitors: list[MonitorInfo],
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> None:
        """Bulk-add a peer's monitors as individual ScreenInfo entries.

        Each monitor is keyed as ``"peer_id:0"``, ``"peer_id:1"``, etc.
        The *offset_x*/*offset_y* translate monitor coordinates into the
        virtual layout space.
        """
        for idx, mon in enumerate(monitors):
            key = f"{peer_id}:{idx}"
            self._screens[key] = ScreenInfo(
                peer_id=key,
                width=mon.width,
                height=mon.height,
                x=mon.x + offset_x,
                y=mon.y + offset_y,
            )

    def remove_peer(self, peer_id: str) -> None:
        """Remove every screen belonging to *peer_id* (``peer_id`` or ``peer_id:N``)."""
        for key in list(self._screens):
            if key == peer_id or key.startswith(f"{peer_id}:"):
                del self._screens[key]

    def rightmost_x(self) -> int:
        """Return the maximum x + width across all screens (for auto-placement)."""
        if not self._screens:
            return 0
        return max(s.x + s.width for s in self._screens.values())

    def get_adjacent(self, peer_id: str, edge: Edge) -> ScreenInfo | None:
        """Find the screen adjacent to *peer_id* on the given *edge*.

        Returns ``None`` if no screen is adjacent (edges must overlap
        in the perpendicular axis).
        """
        source = self._screens.get(peer_id)
        if source is None:
            return None

        for candidate in self._screens.values():
            if candidate.peer_id == peer_id:
                continue
            if self._edges_touch(source, candidate, edge):
                return candidate
        return None

    def map_edge_crossing(
        self,
        source_peer_id: str,
        edge: Edge,
        position_along_edge: int,
    ) -> EdgeCrossing | None:
        """Compute where the cursor enters the adjacent screen.

        *position_along_edge* is the cursor offset along the crossed edge
        (y for LEFT/RIGHT, x for TOP/BOTTOM) in source-screen coordinates
        relative to the source screen's origin.

        The position is proportionally mapped to the target screen's
        dimensions and clamped to valid bounds.
        """
        source = self._screens.get(source_peer_id)
        if source is None:
            return None

        target = self.get_adjacent(source_peer_id, edge)
        if target is None:
            return None

        if edge in (Edge.LEFT, Edge.RIGHT):
            source_extent = source.height
            target_extent = target.height
        else:
            source_extent = source.width
            target_extent = target.width

        # Proportional mapping, clamped to [0, target_extent - 1]
        if source_extent <= 0:
            mapped = 0
        else:
            ratio = position_along_edge / source_extent
            mapped = int(ratio * target_extent)
        mapped = max(0, min(mapped, target_extent - 1))

        if edge == Edge.RIGHT:
            return EdgeCrossing(target.peer_id, 0, mapped, Edge.LEFT)
        if edge == Edge.LEFT:
            return EdgeCrossing(target.peer_id, target.width - 1, mapped, Edge.RIGHT)
        if edge == Edge.BOTTOM:
            return EdgeCrossing(target.peer_id, mapped, 0, Edge.TOP)
        # Edge.TOP
        return EdgeCrossing(target.peer_id, mapped, target.height - 1, Edge.BOTTOM)

    @staticmethod
    def _edges_touch(source: ScreenInfo, candidate: ScreenInfo, edge: Edge) -> bool:
        """Check if *candidate* is directly adjacent to *source* on *edge*."""
        if edge == Edge.RIGHT:
            if candidate.x != source.x + source.width:
                return False
            return _ranges_overlap(
                source.y, source.y + source.height,
                candidate.y, candidate.y + candidate.height,
            )
        if edge == Edge.LEFT:
            if source.x != candidate.x + candidate.width:
                return False
            return _ranges_overlap(
                source.y, source.y + source.height,
                candidate.y, candidate.y + candidate.height,
            )
        if edge == Edge.BOTTOM:
            if candidate.y != source.y + source.height:
                return False
            return _ranges_overlap(
                source.x, source.x + source.width,
                candidate.x, candidate.x + candidate.width,
            )
        # Edge.TOP
        if source.y != candidate.y + candidate.height:
            return False
        return _ranges_overlap(
            source.x, source.x + source.width,
            candidate.x, candidate.x + candidate.width,
        )


def _ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Check if two 1-D ranges overlap (exclusive endpoints)."""
    return a_start < b_end and b_start < a_end


def default_offset(
    local: list[MonitorInfo], peer: list[MonitorInfo], side: Edge,
) -> tuple[int, int]:
    """Offset placing *peer*'s bounding box on *side* of *local*'s, tops aligned.

    For LEFT/RIGHT the tops are aligned; for TOP/BOTTOM the left edges are.
    """
    lx0 = min((m.x for m in local), default=0)
    ly0 = min((m.y for m in local), default=0)
    lx1 = max((m.x + m.width for m in local), default=0)
    ly1 = max((m.y + m.height for m in local), default=0)
    px0 = min(m.x for m in peer)
    py0 = min(m.y for m in peer)
    px1 = max(m.x + m.width for m in peer)
    py1 = max(m.y + m.height for m in peer)
    if side == Edge.RIGHT:
        return lx1 - px0, ly0 - py0
    if side == Edge.LEFT:
        return lx0 - px1, ly0 - py0
    if side == Edge.BOTTOM:
        return lx0 - px0, ly1 - py0
    return lx0 - px0, ly0 - py1


def snap_offset(
    local: list[MonitorInfo], peer: list[MonitorInfo], offset_x: int, offset_y: int,
) -> tuple[int, int]:
    """Snap a proposed peer offset to the nearest position where the peer
    touches a local monitor edge-to-edge without overlapping any of them.

    Every (local monitor, peer monitor, side) pairing yields a candidate,
    slid along the shared edge just enough to keep at least one pixel of
    overlap, so the layout finds a neighbour. Returns the proposed offset
    unchanged if there is nothing to snap to.
    """
    best: tuple[int, int] | None = None
    best_dist = 0
    for lm in local:
        for pm in peer:
            for cx, cy in _touching_offsets(lm, pm, offset_x, offset_y):
                if _overlaps_any(local, peer, cx, cy):
                    continue
                dist = (cx - offset_x) ** 2 + (cy - offset_y) ** 2
                if best is None or dist < best_dist:
                    best, best_dist = (cx, cy), dist
    return best if best is not None else (offset_x, offset_y)


def _touching_offsets(
    lm: MonitorInfo, pm: MonitorInfo, ox: int, oy: int,
) -> list[tuple[int, int]]:
    """Offsets putting *pm* flush against each side of *lm*, nearest to (ox, oy)."""
    # Range keeping >= 1 px of overlap along the shared edge
    oy_lo, oy_hi = lm.y - pm.y - pm.height + 1, lm.y + lm.height - pm.y - 1
    ox_lo, ox_hi = lm.x - pm.x - pm.width + 1, lm.x + lm.width - pm.x - 1
    sy = max(oy_lo, min(oy, oy_hi))
    sx = max(ox_lo, min(ox, ox_hi))
    return [
        (lm.x + lm.width - pm.x, sy),   # peer to the right
        (lm.x - pm.x - pm.width, sy),   # peer to the left
        (sx, lm.y + lm.height - pm.y),  # peer below
        (sx, lm.y - pm.y - pm.height),  # peer above
    ]


def _overlaps_any(local: list[MonitorInfo], peer: list[MonitorInfo], ox: int, oy: int) -> bool:
    for lm in local:
        for pm in peer:
            if _ranges_overlap(lm.x, lm.x + lm.width, pm.x + ox, pm.x + ox + pm.width) and \
                    _ranges_overlap(lm.y, lm.y + lm.height, pm.y + oy, pm.y + oy + pm.height):
                return True
    return False
