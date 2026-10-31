"""Edge detector — tracks cursor position and detects screen-boundary crossings."""

from __future__ import annotations

import logging

from mouse_share.edge.layout import Edge, EdgeCrossing, ScreenInfo, ScreenLayout

log = logging.getLogger(__name__)


class EdgeDetector:
    """Tracks the cursor across the local monitors and detects when it is
    pushed against an edge that has a remote screen on the other side.

    Positions are in layout coordinates, which for local monitors are the
    OS's native desktop coordinates. Relative deltas are accumulated; the
    cursor moves freely between local monitors and is clamped to the
    monitor it is on otherwise (mirroring what the OS does). A crossing is
    reported when the cursor sits on an edge pixel while moving outward,
    because the OS never lets the real cursor go past the last pixel.
    """

    def __init__(self, layout: ScreenLayout, screens: list[ScreenInfo]) -> None:
        if not screens:
            raise ValueError("EdgeDetector needs at least one local screen")
        self._layout = layout
        self._screens = list(screens)
        self._local_ids = {s.peer_id for s in screens}
        first = self._screens[0]
        self._current = first
        self._x = first.x + first.width // 2
        self._y = first.y + first.height // 2
        # Last dead edge logged, so pushing against it logs once, not per move
        self._logged_edge: tuple[str, Edge] | None = None

    @classmethod
    def from_layout(cls, layout: ScreenLayout, local_peer_id: str) -> EdgeDetector:
        """Build an EdgeDetector from the layout's ``local_peer_id:N`` screens."""
        screens = [
            s for key, s in layout.screens.items()
            if key.startswith(f"{local_peer_id}:")
        ]
        return cls(layout, screens)

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    def reset(self, x: int, y: int) -> None:
        """Set the absolute cursor position (e.g. synced from the OS)."""
        screen = self._screen_at(x, y)
        if screen is None:
            screen = self._nearest_screen(x, y)
        self._current = screen
        self._x, self._y = _clamp_to(screen, x, y)

    def update(self, dx: int, dy: int) -> EdgeCrossing | None:
        """Apply a relative delta and check for an edge crossing.

        Returns an :class:`EdgeCrossing` if the cursor is pushed against an
        edge with an adjacent remote screen, otherwise ``None``.
        """
        new_x = self._x + dx
        new_y = self._y + dy

        screen = self._screen_at(new_x, new_y)
        if screen is not None:
            self._current = screen
            self._x, self._y = new_x, new_y
        else:
            self._x, self._y = _clamp_to(self._current, new_x, new_y)

        return self._check_edge(dx, dy)

    def observe(self, x: int, y: int, dx: int, dy: int) -> EdgeCrossing | None:
        """Like :meth:`update`, but with the resulting absolute position known.

        Used when the move was injected and the OS reports where the cursor
        actually ended up (after acceleration and clamping).
        """
        self.reset(x, y)
        return self._check_edge(dx, dy)

    def _check_edge(self, dx: int, dy: int) -> EdgeCrossing | None:
        s = self._current
        edge: Edge | None = None
        if dx > 0 and self._x >= s.x + s.width - 1:
            edge = Edge.RIGHT
        elif dx < 0 and self._x <= s.x:
            edge = Edge.LEFT
        elif dy > 0 and self._y >= s.y + s.height - 1:
            edge = Edge.BOTTOM
        elif dy < 0 and self._y <= s.y:
            edge = Edge.TOP
        if edge is None:
            self._logged_edge = None
            return None

        along = self._y - s.y if edge in (Edge.LEFT, Edge.RIGHT) else self._x - s.x
        crossing = self._layout.map_edge_crossing(s.peer_id, edge, along)
        if crossing is None or crossing.target_peer_id in self._local_ids:
            if self._logged_edge != (s.peer_id, edge):
                self._logged_edge = (s.peer_id, edge)
                log.debug(
                    "Hit %s edge of %s at (%d, %d): no remote neighbour",
                    edge.value, s.peer_id, self._x, self._y,
                )
            return None
        self._logged_edge = None
        return crossing

    def _screen_at(self, x: int, y: int) -> ScreenInfo | None:
        for s in self._screens:
            if s.x <= x < s.x + s.width and s.y <= y < s.y + s.height:
                return s
        return None

    def _nearest_screen(self, x: int, y: int) -> ScreenInfo:
        def dist(s: ScreenInfo) -> int:
            cx, cy = _clamp_to(s, x, y)
            return (cx - x) ** 2 + (cy - y) ** 2

        return min(self._screens, key=dist)


def _clamp_to(screen: ScreenInfo, x: int, y: int) -> tuple[int, int]:
    return (
        max(screen.x, min(x, screen.x + screen.width - 1)),
        max(screen.y, min(y, screen.y + screen.height - 1)),
    )
