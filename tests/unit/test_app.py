"""Tests for app.py â€” state transitions with mock backends, event routing."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from mouse_share.app import App, AppState
from mouse_share.config import AppConfig, PlacementConfig, load_config
from mouse_share.edge.layout import Edge
from mouse_share.event.types import (
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
    MouseMove,
)
from mouse_share.screen import MonitorInfo

if TYPE_CHECKING:
    from pathlib import Path


class MockCapture:
    """Mock capture backend that records calls."""

    def __init__(self) -> None:
        self.on_event = None
        self.started = False
        self.stopped = False
        self.suppressing = False

    def start(self, on_event):
        self.on_event = on_event
        self.started = True

    def stop(self):
        self.stopped = True

    def set_suppressing(self, suppressing):
        self.suppressing = suppressing

    def set_escape_callback(self, callback):
        self.escape_callback = callback

    def cursor_position(self):
        return self.position

    position: tuple[int, int] | None = None


class MockEmulate:
    """Mock emulate backend that records injected events."""

    def __init__(self) -> None:
        self.events: list = []
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def inject(self, event):
        self.events.append(event)

    def warp(self, x, y):
        self.warped = (x, y)
        self.position = (x, y)

    def cursor_position(self):
        return self.position

    position: tuple[int, int] | None = None


def _make_app(
    peer_id: str = "test-local",
    width: int = 1920,
    height: int = 1080,
    *,
    no_detect: bool = True,
    placements: list[PlacementConfig] | None = None,
    config_path: Path | None = None,
) -> tuple[App, MockCapture, MockEmulate]:
    config = AppConfig(
        local_peer_id=peer_id,
        screen_width=width,
        screen_height=height,
        placements=placements or [],
    )
    capture = MockCapture()
    emulate = MockEmulate()
    app = App(
        config=config,
        capture=capture,
        emulate=emulate,
        no_detect=no_detect,
        config_path=config_path,
    )
    return app, capture, emulate


class TestInitialState:
    def test_starts_idle(self) -> None:
        app, _, _ = _make_app()
        assert app.state == AppState.IDLE


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_run_transitions_to_active_local(self) -> None:
        app, capture, emulate = _make_app()

        async def cancel_soon():
            await asyncio.sleep(0.1)
            task.cancel()

        task = asyncio.create_task(app.run())
        asyncio.create_task(cancel_soon())

        await task  # run() catches CancelledError and shuts down cleanly

        assert capture.started
        assert emulate.started


class TestEventRouting:
    def test_handle_captured_event_local_mode_no_crossing(self) -> None:
        """In ACTIVE_LOCAL, mouse moves are processed by edge detector."""
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_LOCAL
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")

        # Small move doesn't cross edge
        app._handle_captured_event(MouseMove(dx=10, dy=0))
        # No state change, no events emulated
        assert app.state == AppState.ACTIVE_LOCAL

    def test_handle_captured_event_remote_queues_to_udp(self) -> None:
        """In ACTIVE_REMOTE, events are forwarded via UDP."""
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_REMOTE
        mock_udp = MagicMock()
        app._udp_transport = mock_udp

        event = MouseMove(dx=5, dy=10)
        app._handle_captured_event(event)
        mock_udp.queue_event.assert_called_once_with(event)

    def test_non_mouse_events_ignored_for_edge_detection(self) -> None:
        """Only MouseMove triggers edge detection."""
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_LOCAL
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")

        # Key press should not crash or trigger crossing
        app._handle_captured_event(KeyPress(scancode=0x04))
        assert app.state == AppState.ACTIVE_LOCAL


class TestRemoteEvents:
    def test_remote_events_injected(self) -> None:
        """Events from UDP are injected via emulate backend."""
        app, capture, emulate = _make_app()
        events = [
            MouseMove(dx=5, dy=10),
            MouseButton(button=MouseButtonCode.LEFT, pressed=True),
        ]
        app._on_remote_events(events)
        assert len(emulate.events) == 2
        assert emulate.events[0] == events[0]
        assert emulate.events[1] == events[1]


class TestFocusSwitch:
    @pytest.mark.asyncio
    async def test_receive_focus_transitions_to_active_local(self) -> None:
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_REMOTE
        capture.suppressing = True
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")

        await app._on_switch_focus({"entry_x": 100, "entry_y": 200})

        assert app.state == AppState.ACTIVE_LOCAL
        assert not capture.suppressing
        assert app._edge_detector.x == 100
        assert app._edge_detector.y == 200

    @pytest.mark.asyncio
    async def test_receive_focus_warps_to_target_monitor(self) -> None:
        """Entry coords are relative to the target monitor index."""
        app, capture, emulate = _make_app()
        app._local_monitors = [
            MonitorInfo("L", -1920, 0, 1920, 1080, False),
            MonitorInfo("P", 0, 0, 2560, 1440, True),
        ]
        app._setup_layout()
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")

        await app._on_switch_focus({"target": "test-local:0", "entry_x": 0, "entry_y": 300})

        assert emulate.warped == (-1920, 300)
        assert app._edge_detector.x == -1920
        assert app._edge_detector.y == 300

    @pytest.mark.asyncio
    async def test_crossing_switches_to_connected_peer(self) -> None:
        """A crossing onto ``peer:N`` uses the connection keyed by ``peer``."""
        app, capture, emulate = _make_app()
        app._loop = asyncio.get_running_loop()
        app._state = AppState.ACTIVE_LOCAL
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        app._layout.add_peer_monitors(
            "remote", [MonitorInfo("R", 0, 0, 1920, 1080, True)], offset_x=1920,
        )
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")
        conn = MagicMock()
        conn.send_switch_focus = AsyncMock()
        app._peer_connections["remote"] = conn

        app._handle_captured_event(MouseMove(dx=2000, dy=0))
        await asyncio.sleep(0)

        assert app.state == AppState.ACTIVE_REMOTE
        assert app._remote_peer_id == "remote"
        assert capture.suppressing
        conn.send_switch_focus.assert_awaited_once_with("remote:0", 0, 540)

    def test_initiate_focus_switch_no_connection(self) -> None:
        """Focus switch to unconnected peer is a no-op."""
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_LOCAL
        # No peer connections
        app._initiate_focus_switch("unknown-peer", 0, 0)
        # Should stay in ACTIVE_LOCAL
        assert app.state == AppState.ACTIVE_LOCAL


class TestControlledReturn:
    """A driven peer hands focus back when its cursor exits toward the controller."""

    def _controlled_app(self):
        app, capture, emulate = _make_app(peer_id="linux", width=3440, height=1440)
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        app._place_peer("pc", [
            MonitorInfo("DISPLAY1", 0, 0, 3440, 1440, True),
            MonitorInfo("DISPLAY5", -2560, 0, 2560, 1440, False),
        ], Edge.LEFT)
        return app, capture, emulate

    def test_controller_screens_placed_to_the_left(self) -> None:
        app, _, _ = self._controlled_app()
        primary = app._layout.get_screen("pc:0")
        side = app._layout.get_screen("pc:1")
        assert primary is not None and side is not None
        # Controller's rightmost edge (DISPLAY1) meets our x=0
        assert primary.x + primary.width == 0
        assert side.x + side.width == primary.x

    @pytest.mark.asyncio
    async def test_push_left_returns_focus(self) -> None:
        app, capture, emulate = self._controlled_app()
        app._loop = asyncio.get_running_loop()
        conn = MagicMock()
        conn.send_switch_focus = AsyncMock()

        app._on_focus_from_controller(
            conn, "pc", {"target": "linux:0", "entry_x": 0, "entry_y": 700},
        )
        assert app.state == AppState.CONTROLLED
        assert emulate.warped == (0, 700)

        # Moving right stays here
        emulate.position = (50, 700)
        app._on_remote_events([MouseMove(dx=50, dy=0)])
        assert app.state == AppState.CONTROLLED

        # Pushing against the left edge hands focus back
        emulate.position = (0, 720)
        app._on_remote_events([MouseMove(dx=-60, dy=20)])
        await asyncio.sleep(0)

        assert app.state == AppState.ACTIVE_LOCAL
        assert app._controller_conn is None
        conn.send_switch_focus.assert_awaited_once_with("pc:0", 3439, 720)

    def test_no_return_when_not_controlled(self) -> None:
        app, capture, emulate = self._controlled_app()
        app._state = AppState.ACTIVE_LOCAL
        emulate.position = (0, 720)
        app._on_remote_events([MouseMove(dx=-60, dy=0)])
        assert app.state == AppState.ACTIVE_LOCAL

    @pytest.mark.asyncio
    async def test_focus_returned_to_controller(self) -> None:
        app, capture, emulate = _make_app(width=3440, height=1440)
        app._state = AppState.ACTIVE_REMOTE
        app._remote_peer_id = "linux"
        capture.suppressing = True
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        app._rebuild_edge_detector()

        await app._on_switch_focus({"target": "test-local:0", "entry_x": 3439, "entry_y": 720})

        assert app.state == AppState.ACTIVE_LOCAL
        assert not capture.suppressing
        assert emulate.warped == (3439, 720)


PEER_MONITORS = [MonitorInfo("R", 0, 0, 1920, 1080, True)]


class TestPlacement:
    """Peer placement: saved offsets, mirroring, and GUI-driven changes."""

    def _app(self, tmp_path: Path, **kwargs):
        app, capture, emulate = _make_app(config_path=tmp_path / "config.json", **kwargs)
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        app._rebuild_edge_detector()
        return app

    def test_default_right_matches_legacy(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        assert app._place_peer("remote", PEER_MONITORS, Edge.RIGHT) == (1920, 0)
        assert app._layout.get_adjacent("test-local:0", Edge.RIGHT) is not None

    def test_saved_placement_wins_over_default(self, tmp_path: Path) -> None:
        app = self._app(tmp_path, placements=[PlacementConfig("remote", 0, -1080)])
        assert app._place_peer("remote", PEER_MONITORS, Edge.RIGHT) == (0, -1080)
        above = app._layout.get_adjacent("test-local:0", Edge.TOP)
        assert above is not None and above.peer_id == "remote:0"

    def test_screen_config_is_mirrored(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        # The peer put us below it, so it sits above us
        app._on_screen_config("remote", {"offset_x": 0, "offset_y": 1080}, PEER_MONITORS,
                              persist=True)
        assert app._peer_offsets["remote"] == (0, -1080)
        assert app._layout.get_adjacent("test-local:0", Edge.TOP) is not None
        saved = load_config(tmp_path / "config.json").placements
        assert saved == [PlacementConfig("remote", 0, -1080)]

    def test_screen_config_not_persisted_on_accepting_side(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app._on_screen_config("remote", {"offset_x": 1920, "offset_y": 0}, PEER_MONITORS,
                              persist=False)
        assert app._peer_offsets["remote"] == (-1920, 0)
        assert not (tmp_path / "config.json").exists()

    def test_malformed_screen_config_ignored(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app._on_screen_config("remote", {"offset_x": "x"}, PEER_MONITORS, persist=True)
        assert "remote" not in app._peer_offsets

    @pytest.mark.asyncio
    async def test_apply_placement_moves_saves_and_syncs(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app._loop = asyncio.get_running_loop()
        app._place_peer("remote", PEER_MONITORS, Edge.RIGHT)
        conn = MagicMock()
        conn.closed = False
        conn.send_screen_config = AsyncMock()
        app._peer_connections["remote"] = conn
        seen = []
        app.add_layout_listener(seen.append)

        app._apply_placement("remote", 0, 1080)
        await asyncio.sleep(0)

        assert app._layout.get_adjacent("test-local:0", Edge.BOTTOM) is not None
        assert app._layout.get_adjacent("test-local:0", Edge.RIGHT) is None
        conn.send_screen_config.assert_awaited_once_with(0, 1080)
        assert load_config(tmp_path / "config.json").placements == [
            PlacementConfig("remote", 0, 1080),
        ]
        assert seen[-1].peers[0].offset_y == 1080

    def test_outbound_close_removes_peer(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        conn = MagicMock()
        app._peer_connections["remote"] = conn
        app._place_peer("remote", PEER_MONITORS, Edge.RIGHT)
        app._state = AppState.ACTIVE_REMOTE
        app._remote_peer_id = "remote"

        app._on_outbound_closed("remote", conn)

        assert app.state == AppState.ACTIVE_LOCAL
        assert app._layout.get_screen("remote:0") is None
        assert app.layout_snapshot().peers == ()


LCTRL = 0xE0
PRESS = MouseButton(button=MouseButtonCode.LEFT, pressed=True)
RELEASE = MouseButton(button=MouseButtonCode.LEFT, pressed=False)


class TestHeldInputAcrossEdges:
    """Drags stay on one machine; nothing is left held when focus moves."""

    def _controller(self):
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_LOCAL
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        app._place_peer("remote", PEER_MONITORS, Edge.RIGHT)
        conn = MagicMock()
        conn.send_switch_focus = AsyncMock()
        app._peer_connections["remote"] = conn
        return app, capture, emulate

    @pytest.mark.asyncio
    async def test_no_crossing_while_dragging(self) -> None:
        app, capture, emulate = self._controller()
        app._loop = asyncio.get_running_loop()

        app._handle_captured_event(PRESS)
        app._handle_captured_event(MouseMove(dx=2000, dy=0))
        assert app.state == AppState.ACTIVE_LOCAL

        app._handle_captured_event(RELEASE)
        app._handle_captured_event(MouseMove(dx=10, dy=0))
        assert app.state == AppState.ACTIVE_REMOTE

    @pytest.mark.asyncio
    async def test_crossing_releases_held_keys_locally(self) -> None:
        app, capture, emulate = self._controller()
        app._loop = asyncio.get_running_loop()

        app._handle_captured_event(KeyPress(scancode=LCTRL))
        app._handle_captured_event(MouseMove(dx=2000, dy=0))

        assert app.state == AppState.ACTIVE_REMOTE
        assert emulate.events == [KeyRelease(scancode=LCTRL)]

    def test_escape_hotkey_releases_keys_on_peer(self) -> None:
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_REMOTE
        app._remote_peer_id = "remote"
        udp = MagicMock()
        app._udp_transport = udp
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        app._rebuild_edge_detector()

        app._handle_captured_event(KeyPress(scancode=LCTRL))
        app._handle_captured_event(KeyPress(scancode=0xE2))  # left alt
        udp.reset_mock()
        app._force_local_focus()

        queued = [c.args[0] for c in udp.queue_event.call_args_list]
        assert queued == [KeyRelease(scancode=LCTRL), KeyRelease(scancode=0xE2)]
        udp.flush_now.assert_called_once()

    @pytest.mark.asyncio
    async def test_controlled_side_keeps_drag_and_releases_on_return(self) -> None:
        app, capture, emulate = TestControlledReturn()._controlled_app()
        app._loop = asyncio.get_running_loop()
        conn = MagicMock()
        conn.send_switch_focus = AsyncMock()
        app._on_focus_from_controller(
            conn, "pc", {"target": "linux:0", "entry_x": 0, "entry_y": 700},
        )

        # Dragging into the controller's edge doesn't hand focus back
        emulate.position = (0, 700)
        app._on_remote_events([PRESS, MouseMove(dx=-60, dy=0)])
        assert app.state == AppState.CONTROLLED

        # Released, with ctrl still held: hands back and releases ctrl here
        app._on_remote_events([RELEASE, KeyPress(scancode=LCTRL)])
        emulate.events.clear()
        app._on_remote_events([MouseMove(dx=-60, dy=0)])
        await asyncio.sleep(0)

        assert app.state == AppState.ACTIVE_LOCAL
        assert emulate.events[-1] == KeyRelease(scancode=LCTRL)


class FakeClipboard:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.on_change = None

    def start(self, on_change) -> None:
        self.on_change = on_change

    def set_text(self, text: str) -> None:
        self.texts.append(text)


def _clip_conn():
    conn = MagicMock()
    conn.closed = False
    conn.send_clipboard = AsyncMock()
    return conn


class TestClipboard:
    def _app(self):
        app, _, _ = _make_app()
        clipboard = FakeClipboard()
        app._clipboard = clipboard
        a, b = _clip_conn(), _clip_conn()
        app._peer_connections["a"] = a
        app._inbound_connections["b"] = b
        return app, clipboard, a, b

    @pytest.mark.asyncio
    async def test_local_copy_sent_to_all_peers(self) -> None:
        app, _, a, b = self._app()
        app._loop = asyncio.get_running_loop()

        app._on_local_clipboard("hello")  # may come from the Qt thread
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        a.send_clipboard.assert_awaited_once_with("hello")
        b.send_clipboard.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_remote_copy_set_locally_and_relayed(self) -> None:
        app, clipboard, a, b = self._app()
        app._loop = asyncio.get_running_loop()

        app._on_remote_clipboard(a, "a", {"content": "from a", "content_type": "text/plain"})
        await asyncio.sleep(0)

        assert clipboard.texts == ["from a"]
        a.send_clipboard.assert_not_awaited()  # not echoed to the source
        b.send_clipboard.assert_awaited_once_with("from a")

        # Seen again (e.g. relayed back around a loop of peers): ignored
        app._on_remote_clipboard(b, "b", {"content": "from a"})
        await asyncio.sleep(0)
        assert clipboard.texts == ["from a"]
        a.send_clipboard.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_text_ignored(self) -> None:
        app, clipboard, a, _ = self._app()
        app._loop = asyncio.get_running_loop()
        app._on_remote_clipboard(a, "a", {"content": "x", "content_type": "image/png"})
        assert clipboard.texts == []

    @pytest.mark.asyncio
    async def test_oversized_copy_not_sent(self) -> None:
        app, _, a, b = self._app()
        app._loop = asyncio.get_running_loop()
        app._broadcast_clipboard("x" * 2_000_000, None)
        await asyncio.sleep(0)
        a.send_clipboard.assert_not_awaited()
        b.send_clipboard.assert_not_awaited()


class TestEscapeHotkey:
    def test_force_local_from_active_remote(self) -> None:
        """Escape hotkey transitions from ACTIVE_REMOTE to ACTIVE_LOCAL."""
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_REMOTE
        app._remote_peer_id = "some-peer"
        capture.suppressing = True
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")

        app._force_local_focus()

        assert app.state == AppState.ACTIVE_LOCAL
        assert app._remote_peer_id is None
        assert not capture.suppressing
        # No OS position available → detector stays where it was
        assert app._edge_detector.x == 960
        assert app._edge_detector.y == 540

    def test_force_local_syncs_to_os_cursor(self) -> None:
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_REMOTE
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        from mouse_share.edge.detector import EdgeDetector

        app._edge_detector = EdgeDetector.from_layout(app._layout, "test-local")
        capture.position = (300, 400)

        app._force_local_focus()

        assert (app._edge_detector.x, app._edge_detector.y) == (300, 400)

    def test_force_local_noop_when_already_local(self) -> None:
        """Escape hotkey is a no-op when not in ACTIVE_REMOTE."""
        app, capture, emulate = _make_app()
        app._state = AppState.ACTIVE_LOCAL

        app._force_local_focus()

        assert app.state == AppState.ACTIVE_LOCAL

    def test_force_local_noop_when_idle(self) -> None:
        """Escape hotkey is a no-op in IDLE state."""
        app, capture, emulate = _make_app()
        assert app.state == AppState.IDLE

        app._force_local_focus()

        assert app.state == AppState.IDLE


class TestMultiMonitorSetup:
    def test_detect_local_monitors_fallback_to_config(self) -> None:
        """With no_detect=True, falls back to config screen_width/screen_height."""
        app, _, _ = _make_app(no_detect=True)
        monitors = app._detect_local_monitors()
        assert len(monitors) == 1
        assert monitors[0].width == 1920
        assert monitors[0].height == 1080
        assert monitors[0].name == "default"

    def test_setup_layout_with_multiple_monitors(self) -> None:
        """Setup layout adds per-monitor screen entries."""
        app, _, _ = _make_app(no_detect=True)
        app._local_monitors = [
            MonitorInfo("HDMI-1", 0, 0, 1920, 1080, True),
            MonitorInfo("DP-1", 1920, 0, 2560, 1440, False),
        ]
        app._setup_layout()
        assert app._layout.get_screen("test-local:0") is not None
        assert app._layout.get_screen("test-local:1") is not None
        assert app._layout.rightmost_x() == 1920 + 2560

    def test_setup_layout_single_fallback_monitor(self) -> None:
        """With no detection and no config monitors, single default is used."""
        app, _, _ = _make_app(no_detect=True)
        app._local_monitors = app._detect_local_monitors()
        app._setup_layout()
        s = app._layout.get_screen("test-local:0")
        assert s is not None
        assert s.width == 1920
        assert s.height == 1080
