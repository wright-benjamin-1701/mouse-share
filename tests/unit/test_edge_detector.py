"""Tests for edge/detector.py — delta accumulation, crossing detection, reset."""

import pytest

from mouse_share.edge.detector import EdgeDetector
from mouse_share.edge.layout import Edge, ScreenInfo, ScreenLayout
from mouse_share.screen import MonitorInfo


def _simple_layout() -> ScreenLayout:
    """Two peers: local (1920×1080 at 0,0) + remote (1920×1080 at 1920,0)."""
    layout = ScreenLayout()
    layout.add_peer_monitors("local", [MonitorInfo("M1", 0, 0, 1920, 1080, True)])
    layout.add_peer_monitors(
        "remote", [MonitorInfo("R1", 0, 0, 1920, 1080, True)], offset_x=1920,
    )
    return layout


def _detector(layout: ScreenLayout | None = None, peer: str = "local") -> EdgeDetector:
    return EdgeDetector.from_layout(layout or _simple_layout(), peer)


class TestDeltaAccumulation:
    def test_initial_position_is_center(self) -> None:
        det = _detector()
        assert det.x == 960
        assert det.y == 540

    def test_move_updates_position(self) -> None:
        det = _detector()
        det.update(10, 20)
        assert det.x == 970
        assert det.y == 560

    def test_clamps_to_zero(self) -> None:
        det = _detector()
        det.update(-2000, -2000)
        assert det.x == 0
        assert det.y == 0

    def test_clamps_to_max(self) -> None:
        det = _detector()
        det.update(2000, 2000)
        assert det.x == 1919
        assert det.y == 1079


class TestCrossingDetection:
    def test_no_crossing_in_bounds(self) -> None:
        assert _detector().update(10, 10) is None

    def test_crossing_right_edge(self) -> None:
        crossing = _detector().update(1000, 0)
        assert crossing is not None
        assert crossing.target_peer_id == "remote:0"
        assert crossing.entry_edge == Edge.LEFT
        assert crossing.entry_x == 0
        assert crossing.entry_y == 540

    def test_crossing_when_landing_on_edge_pixel(self) -> None:
        """The OS never moves the cursor past the last pixel; reaching it counts."""
        det = _detector()
        det.reset(1900, 540)
        assert det.update(19, 0) is not None

    def test_no_crossing_one_pixel_short(self) -> None:
        det = _detector()
        det.reset(1900, 540)
        assert det.update(18, 0) is None

    def test_no_crossing_moving_along_edge(self) -> None:
        det = _detector()
        det.reset(1919, 540)
        assert det.update(0, 10) is None

    def test_no_crossing_left_without_neighbor(self) -> None:
        det = _detector()
        assert det.update(-2000, 0) is None
        assert det.x == 0  # clamped

    def test_crossing_from_remote_screen_left(self) -> None:
        """Remote screen has local to its left."""
        det = _detector(peer="remote")
        crossing = det.update(-2000, 0)
        assert crossing is not None
        assert crossing.target_peer_id == "local:0"
        assert crossing.entry_edge == Edge.RIGHT

    def test_no_crossing_top_without_neighbor(self) -> None:
        assert _detector().update(0, -2000) is None

    def test_no_crossing_bottom_without_neighbor(self) -> None:
        assert _detector().update(0, 2000) is None


class TestMultiMonitor:
    def _layout(self) -> ScreenLayout:
        layout = ScreenLayout()
        layout.add_peer_monitors("local", [
            MonitorInfo("M1", 0, 0, 1920, 1080, True),
            MonitorInfo("M2", 1920, 0, 2560, 1440, False),
        ])
        layout.add_peer_monitors(
            "remote", [MonitorInfo("R1", 0, 0, 1920, 1080, True)], offset_x=4480,
        )
        return layout

    def test_moves_between_local_monitors_without_crossing(self) -> None:
        det = _detector(self._layout())
        det.reset(1900, 500)
        assert det.update(100, 0) is None
        assert det.x == 2000

    def test_crossing_from_second_monitor(self) -> None:
        det = _detector(self._layout())
        det.reset(4400, 720)
        crossing = det.update(200, 0)
        assert crossing is not None
        assert crossing.target_peer_id == "remote:0"
        # 720 / 1440 of the way down maps to 540 / 1080
        assert crossing.entry_y == 540

    def test_no_crossing_below_shorter_neighbor(self) -> None:
        """Gap below M1 (1080..1440) clamps to the current monitor."""
        det = _detector(self._layout())
        det.reset(1000, 1000)
        assert det.update(0, 200) is None
        assert det.y == 1079


class TestNegativeCoordinates:
    def test_monitor_left_of_primary(self) -> None:
        layout = ScreenLayout()
        layout.add_peer_monitors("local", [
            MonitorInfo("M1", 0, 0, 1920, 1080, True),
            MonitorInfo("M2", -1920, 0, 1920, 1080, False),
        ])
        det = _detector(layout)
        det.reset(100, 500)
        det.update(-1000, 0)
        assert det.x == -900


class TestReset:
    def test_reset_sets_position(self) -> None:
        det = _detector()
        det.reset(100, 200)
        assert det.x == 100
        assert det.y == 200

    def test_reset_clamps(self) -> None:
        det = _detector()
        det.reset(-10, 3000)
        assert det.x == 0
        assert det.y == 1079

    def test_reset_then_update(self) -> None:
        det = _detector()
        det.reset(0, 540)
        det.update(10, 0)
        assert det.x == 10
        assert det.y == 540


class TestObserve:
    def test_observed_position_on_edge_crosses(self) -> None:
        det = _detector()
        crossing = det.observe(1919, 300, 5, 0)
        assert crossing is not None
        assert crossing.target_peer_id == "remote:0"

    def test_observed_position_inside_does_not_cross(self) -> None:
        det = _detector()
        assert det.observe(1000, 300, 500, 0) is None
        assert (det.x, det.y) == (1000, 300)


class TestFromLayout:
    def test_ignores_non_local_screens(self) -> None:
        det = _detector()
        det.update(5000, 0)
        assert det.x == 1919  # clamped to local, not moved onto remote

    def test_no_local_screens_raises(self) -> None:
        layout = ScreenLayout()
        layout.add_screen(ScreenInfo("other", 800, 600, 0, 0))
        with pytest.raises(ValueError):
            EdgeDetector.from_layout(layout, "local")
