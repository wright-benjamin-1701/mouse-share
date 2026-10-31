"""Tests for edge/layout.py — screen adjacency and proportional mapping."""

from mouse_share.edge.layout import Edge, ScreenInfo, ScreenLayout
from mouse_share.screen import MonitorInfo


def _two_screen_layout() -> ScreenLayout:
    """Two 1920×1080 screens side by side (left at 0,0 — right at 1920,0)."""
    layout = ScreenLayout()
    layout.add_screen(ScreenInfo("left", 1920, 1080, 0, 0))
    layout.add_screen(ScreenInfo("right", 1920, 1080, 1920, 0))
    return layout


class TestAdjacency:
    def test_right_adjacent(self) -> None:
        layout = _two_screen_layout()
        adj = layout.get_adjacent("left", Edge.RIGHT)
        assert adj is not None
        assert adj.peer_id == "right"

    def test_left_adjacent(self) -> None:
        layout = _two_screen_layout()
        adj = layout.get_adjacent("right", Edge.LEFT)
        assert adj is not None
        assert adj.peer_id == "left"

    def test_no_adjacent_top(self) -> None:
        layout = _two_screen_layout()
        assert layout.get_adjacent("left", Edge.TOP) is None

    def test_no_adjacent_bottom(self) -> None:
        layout = _two_screen_layout()
        assert layout.get_adjacent("left", Edge.BOTTOM) is None

    def test_no_adjacent_off_edge(self) -> None:
        layout = _two_screen_layout()
        assert layout.get_adjacent("right", Edge.RIGHT) is None

    def test_unknown_peer(self) -> None:
        layout = _two_screen_layout()
        assert layout.get_adjacent("unknown", Edge.RIGHT) is None

    def test_vertical_layout(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("top", 1920, 1080, 0, 0))
        layout.add_screen(ScreenInfo("bottom", 1920, 1080, 0, 1080))
        assert layout.get_adjacent("top", Edge.BOTTOM) is not None
        assert layout.get_adjacent("bottom", Edge.TOP) is not None
        assert layout.get_adjacent("top", Edge.RIGHT) is None

    def test_non_overlapping_screens_not_adjacent(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("a", 1920, 1080, 0, 0))
        layout.add_screen(ScreenInfo("b", 1920, 1080, 1920, 2000))  # y-offset, no overlap
        assert layout.get_adjacent("a", Edge.RIGHT) is None


class TestEdgeCrossing:
    def test_right_crossing_midpoint(self) -> None:
        layout = _two_screen_layout()
        crossing = layout.map_edge_crossing("left", Edge.RIGHT, 540)
        assert crossing is not None
        assert crossing.target_peer_id == "right"
        assert crossing.entry_x == 0
        assert crossing.entry_edge == Edge.LEFT
        # 540/1080 = 50% → 540 on target (same height)
        assert crossing.entry_y == 540

    def test_left_crossing(self) -> None:
        layout = _two_screen_layout()
        crossing = layout.map_edge_crossing("right", Edge.LEFT, 540)
        assert crossing is not None
        assert crossing.target_peer_id == "left"
        assert crossing.entry_x == 1919  # right edge of target
        assert crossing.entry_edge == Edge.RIGHT

    def test_proportional_mapping_different_resolutions(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("4k", 3840, 2160, 0, 0))
        layout.add_screen(ScreenInfo("1080p", 1920, 1080, 3840, 0))
        # Cross right at 50% height: 1080 / 2160 = 50% → 540 on 1080p
        crossing = layout.map_edge_crossing("4k", Edge.RIGHT, 1080)
        assert crossing is not None
        assert crossing.entry_y == 540

    def test_clamping_at_bounds(self) -> None:
        layout = _two_screen_layout()
        # Position at max height → should clamp to height-1
        crossing = layout.map_edge_crossing("left", Edge.RIGHT, 1080)
        assert crossing is not None
        assert crossing.entry_y == 1079  # clamped

    def test_zero_position(self) -> None:
        layout = _two_screen_layout()
        crossing = layout.map_edge_crossing("left", Edge.RIGHT, 0)
        assert crossing is not None
        assert crossing.entry_y == 0

    def test_no_crossing_when_no_adjacent(self) -> None:
        layout = _two_screen_layout()
        assert layout.map_edge_crossing("left", Edge.TOP, 960) is None

    def test_bottom_crossing(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("top", 1920, 1080, 0, 0))
        layout.add_screen(ScreenInfo("bottom", 1920, 1080, 0, 1080))
        crossing = layout.map_edge_crossing("top", Edge.BOTTOM, 960)
        assert crossing is not None
        assert crossing.target_peer_id == "bottom"
        assert crossing.entry_y == 0
        assert crossing.entry_edge == Edge.TOP
        assert crossing.entry_x == 960

    def test_top_crossing(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("top", 1920, 1080, 0, 0))
        layout.add_screen(ScreenInfo("bottom", 1920, 1080, 0, 1080))
        crossing = layout.map_edge_crossing("bottom", Edge.TOP, 960)
        assert crossing is not None
        assert crossing.target_peer_id == "top"
        assert crossing.entry_y == 1079  # bottom edge of target
        assert crossing.entry_edge == Edge.BOTTOM


class TestAddPeerMonitors:
    def test_adds_monitors_with_offset(self) -> None:
        layout = ScreenLayout()
        monitors = [
            MonitorInfo("HDMI-1", 0, 0, 1920, 1080, True),
            MonitorInfo("DP-1", 1920, 0, 2560, 1440, False),
        ]
        layout.add_peer_monitors("remote", monitors, offset_x=1920, offset_y=0)
        s0 = layout.get_screen("remote:0")
        s1 = layout.get_screen("remote:1")
        assert s0 is not None
        assert s0.x == 1920
        assert s0.width == 1920
        assert s1 is not None
        assert s1.x == 1920 + 1920
        assert s1.width == 2560
        assert s1.height == 1440

    def test_add_peer_monitors_keying(self) -> None:
        layout = ScreenLayout()
        monitors = [MonitorInfo("M", 0, 0, 800, 600, True)]
        layout.add_peer_monitors("p1", monitors)
        assert layout.get_screen("p1:0") is not None
        assert layout.get_screen("p1") is None

    def test_multi_monitor_adjacency(self) -> None:
        """Two local monitors, one remote monitor to the right of the second."""
        layout = ScreenLayout()
        local = [
            MonitorInfo("L1", 0, 0, 1920, 1080, True),
            MonitorInfo("L2", 1920, 0, 1920, 1080, False),
        ]
        layout.add_peer_monitors("local", local)
        remote = [MonitorInfo("R1", 0, 0, 1920, 1080, True)]
        layout.add_peer_monitors("remote", remote, offset_x=3840)
        # local:1 right edge is at 3840, remote:0 x is 3840 → adjacent
        adj = layout.get_adjacent("local:1", Edge.RIGHT)
        assert adj is not None
        assert adj.peer_id == "remote:0"


class TestRightmostX:
    def test_empty_layout(self) -> None:
        layout = ScreenLayout()
        assert layout.rightmost_x() == 0

    def test_single_screen(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("a", 1920, 1080, 0, 0))
        assert layout.rightmost_x() == 1920

    def test_multiple_screens(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("a", 1920, 1080, 0, 0))
        layout.add_screen(ScreenInfo("b", 2560, 1440, 1920, 0))
        assert layout.rightmost_x() == 1920 + 2560


class TestRemovePeer:
    def test_removes_only_that_peer(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("pc:0", 1920, 1080, 0, 0))
        layout.add_screen(ScreenInfo("pc:1", 1920, 1080, 1920, 0))
        layout.add_screen(ScreenInfo("pc2:0", 1920, 1080, 3840, 0))
        layout.remove_peer("pc")
        assert set(layout.screens) == {"pc2:0"}
