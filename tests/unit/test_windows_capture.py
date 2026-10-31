"""Tests for capture/windows.py — mock ctypes, delta computation, injected flag.

These tests only run on Windows.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


@pytest.fixture
def capture():
    from mouse_share.capture.windows import WindowsCapture

    return WindowsCapture()


class TestDeltaComputation:
    """Test mouse delta computation from absolute positions."""

    def test_first_move_returns_zero_delta(self, capture) -> None:
        """First absolute position produces no delta (no prior reference)."""
        import ctypes.wintypes

        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_MOUSEMOVE

        info = MSLLHOOKSTRUCT()
        info.pt = ctypes.wintypes.POINT(500, 300)
        info.flags = 0

        event = capture._parse_mouse_event(WM_MOUSEMOVE, info)
        assert event is None  # (0,0) delta is suppressed

    def test_second_move_computes_delta(self, capture) -> None:
        import ctypes.wintypes

        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_MOUSEMOVE
        from mouse_share.event.types import MouseMove

        # First move sets baseline
        info1 = MSLLHOOKSTRUCT()
        info1.pt = ctypes.wintypes.POINT(500, 300)
        info1.flags = 0
        capture._parse_mouse_event(WM_MOUSEMOVE, info1)

        # Second move produces delta
        info2 = MSLLHOOKSTRUCT()
        info2.pt = ctypes.wintypes.POINT(510, 305)
        info2.flags = 0
        event = capture._parse_mouse_event(WM_MOUSEMOVE, info2)
        assert isinstance(event, MouseMove)
        assert event.dx == 10
        assert event.dy == 5


class TestButtonParsing:
    def test_left_button_down(self, capture) -> None:
        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_LBUTTONDOWN
        from mouse_share.event.types import MouseButton, MouseButtonCode

        info = MSLLHOOKSTRUCT()
        info.flags = 0
        event = capture._parse_mouse_event(WM_LBUTTONDOWN, info)
        assert isinstance(event, MouseButton)
        assert event.button == MouseButtonCode.LEFT
        assert event.pressed is True

    def test_right_button_up(self, capture) -> None:
        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_RBUTTONUP
        from mouse_share.event.types import MouseButton, MouseButtonCode

        info = MSLLHOOKSTRUCT()
        info.flags = 0
        event = capture._parse_mouse_event(WM_RBUTTONUP, info)
        assert isinstance(event, MouseButton)
        assert event.button == MouseButtonCode.RIGHT
        assert event.pressed is False


class TestScrollParsing:
    def test_vertical_scroll(self, capture) -> None:
        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_MOUSEWHEEL
        from mouse_share.event.types import MouseScroll

        info = MSLLHOOKSTRUCT()
        info.flags = 0
        info.mouseData = 120 << 16  # WHEEL_DELTA in high word
        event = capture._parse_mouse_event(WM_MOUSEWHEEL, info)
        assert isinstance(event, MouseScroll)
        assert event.dy == 120
        assert event.dx == 0

    def test_horizontal_scroll(self, capture) -> None:
        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_MOUSEHWHEEL
        from mouse_share.event.types import MouseScroll

        info = MSLLHOOKSTRUCT()
        info.flags = 0
        info.mouseData = 120 << 16
        event = capture._parse_mouse_event(WM_MOUSEHWHEEL, info)
        assert isinstance(event, MouseScroll)
        assert event.dx == 120
        assert event.dy == 0


class TestSuppressing:
    @pytest.fixture(autouse=True)
    def _fake_user32(self, monkeypatch):
        from unittest.mock import MagicMock

        import mouse_share.capture.windows as w

        fake = MagicMock()
        fake.cursor = [3439, 300]
        fake.GetSystemMetrics.side_effect = lambda idx: (3440, 1440)[idx]

        def get_cursor_pos(ref):
            ref._obj.x, ref._obj.y = fake.cursor
            return 1

        def set_cursor_pos(x, y):
            fake.cursor = [x, y]
            return 1

        fake.GetCursorPos.side_effect = get_cursor_pos
        fake.SetCursorPos.side_effect = set_cursor_pos
        monkeypatch.setattr(w, "user32", fake)
        return fake

    @staticmethod
    def _move(capture, x, y):
        import ctypes.wintypes

        from mouse_share.capture.windows import MSLLHOOKSTRUCT, WM_MOUSEMOVE

        info = MSLLHOOKSTRUCT()
        info.pt = ctypes.wintypes.POINT(x, y)
        return capture._parse_mouse_event(WM_MOUSEMOVE, info)

    def test_suppressing_toggle(self, capture) -> None:
        assert capture._suppressing is False
        capture.set_suppressing(True)
        assert capture._suppressing is True
        capture.set_suppressing(False)
        assert capture._suppressing is False

    def test_suppressed_delta_measured_from_real_cursor(self, capture, _fake_user32) -> None:
        """Cursor still at the crossing edge: no phantom offset from the centre."""
        capture.set_suppressing(True)
        event = self._move(capture, 3430, 305)
        assert (event.dx, event.dy) == (-9, 5)

    def test_suppressed_moves_park_cursor_mid_screen(self, capture, _fake_user32) -> None:
        capture.set_suppressing(True)
        self._move(capture, 3430, 305)
        assert _fake_user32.cursor == [1720, 720]
        # Subsequent swallowed moves are measured from the parked position
        event = self._move(capture, 1730, 720)
        assert (event.dx, event.dy) == (10, 0)
        event = self._move(capture, 1730, 720)
        assert (event.dx, event.dy) == (10, 0)

    def test_unsuppress_resets_baseline(self, capture, _fake_user32) -> None:
        capture.set_suppressing(True)
        self._move(capture, 1730, 720)
        capture.set_suppressing(False)
        # First move after returning sets the baseline only
        assert self._move(capture, 3439, 500) is None
        event = self._move(capture, 3430, 500)
        assert (event.dx, event.dy) == (-9, 0)
