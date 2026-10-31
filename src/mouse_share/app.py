"""Application orchestrator — wires capture, network, emulation, and edge detection.

State machine:
  IDLE → CONNECTING → ACTIVE_LOCAL → ACTIVE_REMOTE

A peer that accepts a connection is driven by the peer that connected: on
SWITCH_FOCUS it enters CONTROLLED, injecting the controller's input, and
hands focus back when the injected cursor is pushed off the edge facing
the controller.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from mouse_share.config import PlacementConfig, load_config, save_config
from mouse_share.edge.detector import EdgeDetector
from mouse_share.edge.layout import Edge, ScreenInfo, ScreenLayout, default_offset
from mouse_share.event.held import HeldInput
from mouse_share.event.types import InputEvent, MouseMove
from mouse_share.net.control import (
    ControlConnection,
    ControlServer,
    connect_to_peer,
)
from mouse_share.net.link_selector import run_probe_responder, select_best_link
from mouse_share.net.protocol import (
    DEFAULT_TCP_PORT,
    MAX_CONTROL_MESSAGE_SIZE,
    ControlMessageType,
)
from mouse_share.net.transport import UDPTransport, create_udp_transport
from mouse_share.screen import MonitorInfo, detect_monitors

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mouse_share.capture.base import CaptureBackend
    from mouse_share.clipboard.base import ClipboardBackend
    from mouse_share.config import AppConfig
    from mouse_share.emulate.base import EmulateBackend

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeerLayout:
    """A connected peer's native monitors and where they sit in our layout."""

    peer_id: str
    monitors: tuple[MonitorInfo, ...]
    offset_x: int
    offset_y: int


@dataclass(frozen=True, slots=True)
class LayoutSnapshot:
    """Immutable view of the arrangement, safe to read from any thread."""

    local: tuple[MonitorInfo, ...] = ()
    peers: tuple[PeerLayout, ...] = ()


class AppState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    ACTIVE_LOCAL = auto()
    ACTIVE_REMOTE = auto()
    CONTROLLED = auto()


class App:
    """Top-level orchestrator that ties all subsystems together."""

    def __init__(
        self,
        config: AppConfig,
        capture: CaptureBackend,
        emulate: EmulateBackend,
        *,
        no_detect: bool = False,
        config_path: Path | None = None,
        clipboard: ClipboardBackend | None = None,
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._clipboard = clipboard
        self._capture = capture
        self._emulate = emulate
        self._no_detect = no_detect
        self._state = AppState.IDLE
        self._loop: asyncio.AbstractEventLoop | None = None
        self._run_task: asyncio.Task[Any] | None = None

        # Networking
        self._control_server: ControlServer | None = None
        self._peer_connections: dict[str, ControlConnection] = {}
        self._inbound_connections: dict[str, ControlConnection] = {}
        self._udp_transport: UDPTransport | None = None
        self._udp_asyncio_transport: asyncio.DatagramTransport | None = None
        self._probe_transport: asyncio.DatagramTransport | None = None

        # Edge detection
        self._layout = ScreenLayout()
        self._edge_detector: EdgeDetector | None = None

        # Local monitors (detected or from config)
        self._local_monitors: list[MonitorInfo] = []

        # Peer arrangement: native monitors and offset into our layout space
        self._peer_monitors: dict[str, list[MonitorInfo]] = {}
        self._peer_offsets: dict[str, tuple[int, int]] = {}  # offsets in use
        self._placements: dict[str, tuple[int, int]] = {
            p.peer_id: (p.offset_x, p.offset_y) for p in config.placements
        }
        self._layout_listeners: list[Callable[[LayoutSnapshot], None]] = []
        self._snapshot = LayoutSnapshot()

        # Track which peer currently has focus
        self._remote_peer_id: str | None = None
        self._seen_mouse_move = False

        # The peer currently driving us (CONTROLLED state), if any
        self._controller_id: str | None = None
        self._controller_conn: ControlConnection | None = None

        # Held keys/buttons, so whichever side loses focus can release them:
        # physical input reaching our OS, input sent to the remote peer, and
        # input injected here by a controller.
        self._local_held = HeldInput()
        self._sent_held = HeldInput()
        self._injected_held = HeldInput()

        # Last clipboard text sent or received, to stop relay loops
        self._last_clipboard: str | None = None

    @property
    def state(self) -> AppState:
        return self._state

    # -- Arrangement API (safe to call from the GUI thread) ------------------

    def layout_snapshot(self) -> LayoutSnapshot:
        """The current arrangement; replaced atomically on every change."""
        return self._snapshot

    def add_layout_listener(self, callback: Callable[[LayoutSnapshot], None]) -> None:
        """Register *callback*, invoked on the event loop thread after each change."""
        self._layout_listeners.append(callback)

    def request_placement(self, peer_id: str, offset_x: int, offset_y: int) -> None:
        """Move *peer_id* to the given offset, persist it, and tell the peer."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._apply_placement, peer_id, offset_x, offset_y)

    def request_stop(self) -> None:
        """Cancel :meth:`run` from another thread."""
        if self._loop is not None and self._run_task is not None:
            self._loop.call_soon_threadsafe(self._run_task.cancel)

    def _detect_local_monitors(self) -> list[MonitorInfo]:
        """Detect local monitors, falling back to config defaults."""
        if not self._no_detect:
            monitors = detect_monitors()
            if monitors:
                log.info(
                    "Detected %d monitor(s): %s",
                    len(monitors),
                    ", ".join(f"{m.name} {m.width}x{m.height}+{m.x}+{m.y}" for m in monitors),
                )
                return monitors

        # Fall back to config monitors list
        if self._config.monitors:
            return [
                MonitorInfo(
                    name=m.peer_id,
                    x=m.x,
                    y=m.y,
                    width=m.width,
                    height=m.height,
                    is_primary=(i == 0),
                )
                for i, m in enumerate(self._config.monitors)
            ]

        # Final fallback: single monitor from screen_width/screen_height
        log.info(
            "Using default screen size %dx%d",
            self._config.screen_width,
            self._config.screen_height,
        )
        return [
            MonitorInfo(
                name="default",
                x=0,
                y=0,
                width=self._config.screen_width,
                height=self._config.screen_height,
                is_primary=True,
            ),
        ]

    async def run(self, connect_host: str | None = None) -> None:
        """Start the app and run until cancelled."""
        self._loop = asyncio.get_running_loop()
        self._run_task = asyncio.current_task()

        # Detect local monitors
        self._local_monitors = self._detect_local_monitors()

        # Build screen layout from detected monitors
        self._setup_layout()

        self._rebuild_edge_detector()
        self._notify_layout()

        # Start emulation backend
        self._emulate.start()

        # Start capture in pass-through mode (not suppressing)
        self._capture.set_suppressing(False)
        self._capture.set_escape_callback(self._on_escape_hotkey)
        self._capture.start(self._on_capture_event)
        self._sync_cursor()

        if self._clipboard is not None:
            self._clipboard.start(self._on_local_clipboard)

        # Start networking
        tcp_port = self._config.tcp_port
        udp_port = self._config.udp_port

        self._control_server = ControlServer(self._on_inbound_connection)
        await self._control_server.start(port=tcp_port)
        log.info("Control server listening on port %d", tcp_port)

        # Start probe responder
        self._probe_transport, _ = await run_probe_responder()

        # Start UDP transport
        self._udp_asyncio_transport, self._udp_transport = await create_udp_transport(
            on_events=self._on_remote_events,
            bind_port=udp_port,
        )

        self._state = AppState.ACTIVE_LOCAL
        log.info("Ready — local focus active (%s)", self._config.local_peer_id)

        # Connect to a specified peer if provided
        if connect_host is not None:
            self._state = AppState.CONNECTING
            await self._connect_to_peer(connect_host, tcp_port)
            self._state = AppState.ACTIVE_LOCAL

        # Run until cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Cleanly shut down all subsystems."""
        self._state = AppState.IDLE
        self._capture.stop()
        self._emulate.stop()

        for conn in list(self._peer_connections.values()):
            await conn.close()
        self._peer_connections.clear()

        if self._control_server is not None:
            await self._control_server.stop()
        if self._udp_transport is not None:
            await self._udp_transport.stop()
        if self._probe_transport is not None:
            self._probe_transport.close()

    def _setup_layout(self) -> None:
        """Build the ScreenLayout from detected monitors and config."""
        # Add local monitors
        self._layout.add_peer_monitors(
            self._config.local_peer_id,
            self._local_monitors,
        )

        # Add configured screens (backward compat)
        for sc in self._config.screens:
            self._layout.add_screen(ScreenInfo(
                peer_id=sc.peer_id,
                width=sc.width,
                height=sc.height,
                x=sc.x,
                y=sc.y,
            ))

    async def _connect_to_peer(self, host: str, port: int = DEFAULT_TCP_PORT) -> None:
        """Establish a TCP control connection to a peer."""
        log.info("Connecting to %s:%d...", host, port)
        conn = await connect_to_peer(host, port)

        # Exchange hellos with monitor info
        await conn.send_hello(self._local_monitors)

        # Register handlers; the peer id is only known once its hello arrives
        conn.on(ControlMessageType.SWITCH_FOCUS, self._on_switch_focus)
        self._handle_clipboard(conn, host)

        async def on_screen_config(payload: dict[str, Any]) -> None:
            self._on_screen_config(
                _hostname_of(conn, host), payload, _monitors_from_hello(conn), persist=True,
            )

        conn.on(ControlMessageType.SCREEN_CONFIG, on_screen_config)

        # Start reading messages in background
        run_task = asyncio.create_task(conn.run())

        if not await _await_hello(conn):
            log.warning("Peer at %s did not send hello in time", host)
            await conn.close()
            return

        peer_id = _hostname_of(conn, host)
        log.info("Connected to peer: %s", peer_id)

        # Run link probing to find the fastest path
        peer_nics = conn.peer_nics
        if peer_nics:
            link = await select_best_link(peer_nics)
            if link is not None:
                log.info(
                    "Best link: %s → %s (%.0f μs median RTT)",
                    link.local_ip, link.remote_ip, link.median_rtt_us,
                )
                # Point UDP transport at the peer's best IP
                self._udp_transport.set_target(link.remote_ip, self._config.udp_port)  # type: ignore[union-attr]
            else:
                log.warning("No reachable link to peer; using TCP host for UDP")
                self._udp_transport.set_target(host, self._config.udp_port)  # type: ignore[union-attr]
        else:
            self._udp_transport.set_target(host, self._config.udp_port)  # type: ignore[union-attr]

        self._peer_connections[peer_id] = conn
        run_task.add_done_callback(lambda _: self._on_outbound_closed(peer_id, conn))

        # Place the peer (saved placement, else to our right) and tell it
        # where it sits, so its mirrored layout matches ours exactly.
        offset = self._place_peer(peer_id, _monitors_from_hello(conn), Edge.RIGHT)
        if offset is not None:
            await conn.send_screen_config(*offset)
        self._sync_cursor()

    def _on_outbound_closed(self, peer_id: str, conn: ControlConnection) -> None:
        """A peer we connected to went away: drop its screens."""
        if self._peer_connections.get(peer_id) is not conn:
            return
        log.info("Connection to %s closed", peer_id)
        del self._peer_connections[peer_id]
        if self._remote_peer_id == peer_id:
            self._state = AppState.ACTIVE_LOCAL
            self._remote_peer_id = None
            self._capture.set_suppressing(False)
            self._sent_held.clear()
        self._unplace_peer(peer_id)
        self._sync_cursor()

    def _place_peer(
        self, peer_id: str, monitors: list[MonitorInfo], default_side: Edge,
    ) -> tuple[int, int] | None:
        """(Re)add *peer_id*'s monitors to the layout at its placement.

        Uses the saved placement if there is one, otherwise puts the peer's
        bounding box on *default_side* of ours. Returns the offset used, or
        ``None`` if the peer reported no monitors.
        """
        if not monitors:
            return None
        offset = self._placements.get(peer_id)
        if offset is None:
            offset = default_offset(self._local_monitors, monitors, default_side)
        self._peer_monitors[peer_id] = list(monitors)
        self._peer_offsets[peer_id] = offset
        self._layout.remove_peer(peer_id)
        self._layout.add_peer_monitors(peer_id, monitors, offset_x=offset[0], offset_y=offset[1])
        self._rebuild_edge_detector()
        log.info(
            "Placed %s: %d monitor(s) at offset (%d, %d)",
            peer_id, len(monitors), offset[0], offset[1],
        )
        self._log_layout()
        self._notify_layout()
        return offset

    def _unplace_peer(self, peer_id: str) -> None:
        self._peer_monitors.pop(peer_id, None)
        self._peer_offsets.pop(peer_id, None)
        self._layout.remove_peer(peer_id)
        self._rebuild_edge_detector()
        self._notify_layout()

    def _apply_placement(self, peer_id: str, offset_x: int, offset_y: int) -> None:
        """A local placement change (from the GUI): apply, persist, and sync."""
        self._placements[peer_id] = (offset_x, offset_y)
        self._persist_placements()
        monitors = self._peer_monitors.get(peer_id)
        if monitors:
            self._place_peer(peer_id, monitors, Edge.RIGHT)
            self._sync_cursor()
        conn = self._peer_connections.get(peer_id) or self._inbound_connections.get(peer_id)
        if conn is not None and not conn.closed and self._loop is not None:
            self._loop.create_task(conn.send_screen_config(offset_x, offset_y))

    def _on_screen_config(
        self,
        peer_id: str,
        payload: dict[str, Any],
        monitors: list[MonitorInfo],
        *,
        persist: bool,
    ) -> None:
        """The peer told us where *our* monitors sit in its space; mirror it.

        Only the connecting side's saved placement is used at connect time
        (it always sends it), so only that side needs to persist.
        """
        try:
            offset = (-int(payload["offset_x"]), -int(payload["offset_y"]))
        except (KeyError, TypeError, ValueError):
            log.warning("Ignoring malformed screen_config from %s: %s", peer_id, payload)
            return
        log.info("Peer %s set our placement; mirroring at (%d, %d)", peer_id, *offset)
        changed = self._placements.get(peer_id) != offset
        self._placements[peer_id] = offset
        if persist and changed:
            self._persist_placements()
        self._place_peer(peer_id, monitors, Edge.RIGHT)

    def _persist_placements(self) -> None:
        """Write placements to the config file, leaving its other keys alone."""
        placements = [PlacementConfig(p, x, y) for p, (x, y) in sorted(self._placements.items())]
        self._config = dataclasses.replace(self._config, placements=placements)
        try:
            on_disk = load_config(self._config_path)
            save_config(dataclasses.replace(on_disk, placements=placements), self._config_path)
        except (OSError, ValueError, TypeError):
            log.warning("Could not save placements to config", exc_info=True)

    def _notify_layout(self) -> None:
        self._snapshot = LayoutSnapshot(
            local=tuple(self._local_monitors),
            peers=tuple(
                PeerLayout(pid, tuple(self._peer_monitors[pid]), ox, oy)
                for pid, (ox, oy) in self._peer_offsets.items()
            ),
        )
        for callback in self._layout_listeners:
            try:
                callback(self._snapshot)
            except Exception:
                log.exception("Layout listener failed")

    # -- Clipboard sharing ----------------------------------------------------

    def _handle_clipboard(self, conn: ControlConnection, fallback_id: object) -> None:
        async def on_clipboard(payload: dict[str, Any]) -> None:
            self._on_remote_clipboard(conn, _hostname_of(conn, fallback_id), payload)

        conn.on(ControlMessageType.CLIPBOARD_UPDATE, on_clipboard)

    def _on_local_clipboard(self, text: str) -> None:
        """Clipboard backend callback (any thread): text was copied here."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._broadcast_clipboard, text, None)

    def _broadcast_clipboard(self, text: str, source: ControlConnection | None) -> None:
        """Send *text* to every connected peer except *source*."""
        self._last_clipboard = text
        # JSON-escaped size, so the peer's message size limit can't drop the
        # connection on a huge copy
        if len(json.dumps(text)) > MAX_CONTROL_MESSAGE_SIZE - 1024:
            log.info("Clipboard too large to share (%d chars); not sent", len(text))
            return
        conns = {*self._peer_connections.values(), *self._inbound_connections.values()}
        for conn in conns:
            if conn is not source and not conn.closed and self._loop is not None:
                self._loop.create_task(_send_clipboard(conn, text))

    def _on_remote_clipboard(
        self, conn: ControlConnection, peer_id: str, payload: dict[str, Any],
    ) -> None:
        """A peer copied text: put it on our clipboard and pass it on."""
        text = payload.get("content")
        if not isinstance(text, str) or payload.get("content_type", "text/plain") != "text/plain":
            return
        if text == self._last_clipboard:
            return  # already have it; relaying again could loop around peers
        log.debug("Clipboard from %s (%d chars)", peer_id, len(text))
        if self._clipboard is not None:
            self._clipboard.set_text(text)
        # Peers that aren't connected to the source directly still get it
        self._broadcast_clipboard(text, conn)

    def _log_layout(self) -> None:
        for key, s in self._layout.screens.items():
            log.debug("Layout: %s %dx%d at (%d, %d)", key, s.width, s.height, s.x, s.y)

    def _rebuild_edge_detector(self) -> None:
        """Recreate the edge detector from the local screens in the layout."""
        self._edge_detector = EdgeDetector.from_layout(
            self._layout, self._config.local_peer_id,
        )

    def _sync_cursor(self) -> None:
        """Align the edge detector with the real OS cursor position."""
        pos = self._capture.cursor_position()
        log.debug("OS cursor position: %s", pos)
        if pos is not None and self._edge_detector is not None:
            self._edge_detector.reset(*pos)

    async def _on_inbound_connection(self, conn: ControlConnection) -> None:
        """Handle an incoming TCP control connection."""
        peer = conn.peername
        log.info("Inbound control connection from %s", peer)
        await conn.send_hello(self._local_monitors)

        async def on_switch_focus(payload: dict[str, Any]) -> None:
            # The hello precedes SWITCH_FOCUS on the stream, so peer_info is set
            self._on_focus_from_controller(
                conn, str(conn.peer_info.get("hostname", peer)), payload,
            )

        conn.on(ControlMessageType.SWITCH_FOCUS, on_switch_focus)
        self._handle_clipboard(conn, peer)

        async def on_screen_config(payload: dict[str, Any]) -> None:
            # May arrive before our hello wait below finishes; the hello
            # precedes it on the stream, so the monitors are already known.
            self._on_screen_config(
                _hostname_of(conn, peer), payload, _monitors_from_hello(conn), persist=False,
            )

        conn.on(ControlMessageType.SCREEN_CONFIG, on_screen_config)
        run_task = asyncio.create_task(conn.run())

        peer_id: str | None = None
        if await _await_hello(conn):
            peer_id = _hostname_of(conn, peer)
            self._inbound_connections[peer_id] = conn
            # Placed to our left by default, mirroring the connector's
            # default; the connector's screen_config then confirms it.
            self._place_peer(peer_id, _monitors_from_hello(conn), Edge.LEFT)

        try:
            await run_task
        finally:
            log.info("Control connection from %s closed", peer)
            if peer_id is not None:
                if self._inbound_connections.get(peer_id) is conn:
                    del self._inbound_connections[peer_id]
                self._unplace_peer(peer_id)
            if self._controller_conn is conn:
                self._release_injected()  # its releases will never arrive now
                self._state = AppState.ACTIVE_LOCAL
                self._controller_id = None
                self._controller_conn = None

    def _on_escape_hotkey(self) -> None:
        """Called from capture thread when Ctrl+Alt+Escape is detected."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._force_local_focus)

    def _force_local_focus(self) -> None:
        """Force focus back to local — escape hatch for stuck remote state."""
        if self._state != AppState.ACTIVE_REMOTE:
            return
        log.warning("Escape hotkey pressed — forcing local focus")
        # The hotkey's own Ctrl+Alt already went to the peer; release them
        # (and anything else held) there before we stop sending.
        releases = self._sent_held.release_events()
        if releases and self._udp_transport is not None:
            for release in releases:
                self._udp_transport.queue_event(release)
            self._udp_transport.flush_now()
        self._state = AppState.ACTIVE_LOCAL
        self._remote_peer_id = None
        self._capture.set_suppressing(False)
        self._sync_cursor()

    def _on_capture_event(self, event: InputEvent) -> None:
        """Callback from the capture thread — marshals to the event loop."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._handle_captured_event, event)

    def _handle_captured_event(self, event: InputEvent) -> None:
        """Process a captured event on the event loop."""
        if isinstance(event, MouseMove) and not self._seen_mouse_move:
            self._seen_mouse_move = True
            log.debug("Capture is delivering mouse moves (first: %s)", event)

        if self._state == AppState.ACTIVE_LOCAL:
            # In ACTIVE_LOCAL, events pass through to local OS (not suppressed)
            self._local_held.update(event)
            # Edge detection: only mouse moves can trigger crossings
            if isinstance(event, MouseMove) and self._edge_detector is not None:
                crossing = self._edge_detector.update(event.dx, event.dy)
                if crossing is not None and self._local_held.buttons:
                    # Mid-drag: the drag can't follow to another machine, and
                    # its release would land there, leaving ours held down.
                    log.debug("Not crossing while %s held", sorted(self._local_held.buttons))
                elif crossing is not None:
                    self._initiate_focus_switch(crossing.target_peer_id, crossing.entry_x, crossing.entry_y)

        elif self._state == AppState.ACTIVE_REMOTE and self._udp_transport is not None:
            self._sent_held.update(event)
            self._udp_transport.queue_event(event)

    def _initiate_focus_switch(self, target_screen_id: str, entry_x: int, entry_y: int) -> None:
        """Switch focus to a remote peer.

        *target_screen_id* is a layout key (``"peer:N"``); *entry_x*/*entry_y*
        are relative to that monitor's origin.
        """
        peer_id = _peer_of(target_screen_id)
        conn = self._peer_connections.get(peer_id)
        if conn is None:
            # e.g. our own mouse pushing toward a controller we don't drive
            log.debug("No outbound connection to %s for focus switch", peer_id)
            return

        self._state = AppState.ACTIVE_REMOTE
        self._remote_peer_id = peer_id
        self._capture.set_suppressing(True)
        # Keys still held (e.g. a modifier) would otherwise stay down here:
        # their physical release is about to be swallowed and sent away.
        for release in self._local_held.release_events():
            self._emulate.inject(release)
        self._sent_held.clear()
        log.info("Focus → %s (entry: %d, %d)", target_screen_id, entry_x, entry_y)

        # Send SWITCH_FOCUS over TCP (fire-and-forget from sync context)
        if self._loop is not None:
            self._loop.create_task(conn.send_switch_focus(target_screen_id, entry_x, entry_y))

    async def _on_switch_focus(self, payload: dict[str, Any]) -> None:
        """Focus handed back to us by a peer we were driving."""
        log.info("Focus returned on %s", payload.get("target"))
        self._state = AppState.ACTIVE_LOCAL
        self._remote_peer_id = None
        self._capture.set_suppressing(False)
        self._sent_held.clear()  # the peer released them when handing back
        self._enter_at(payload)

    def _on_focus_from_controller(
        self, conn: ControlConnection, peer_id: str, payload: dict[str, Any],
    ) -> None:
        """A connecting peer moved its cursor onto our screen."""
        log.info("Received focus from %s on %s", peer_id, payload.get("target"))
        self._release_injected()  # anything left from a previous visit
        self._state = AppState.CONTROLLED
        self._controller_id = peer_id
        self._controller_conn = conn
        self._enter_at(payload)

    def _enter_at(self, payload: dict[str, Any]) -> None:
        """Warp the cursor to a SWITCH_FOCUS entry point."""
        entry_x = payload.get("entry_x", 0)
        entry_y = payload.get("entry_y", 0)

        # Entry is relative to the target monitor; convert to desktop coords
        monitor = self._target_monitor(payload.get("target"))
        if monitor is not None:
            entry_x += monitor.x
            entry_y += monitor.y
        self._emulate.warp(entry_x, entry_y)

        if self._edge_detector is not None:
            self._edge_detector.reset(entry_x, entry_y)

    def _target_monitor(self, target: object) -> MonitorInfo | None:
        """Resolve a ``"peer:N"`` target to local monitor N."""
        if not isinstance(target, str) or ":" not in target:
            return None
        idx = target.rsplit(":", 1)[1]
        if not idx.isdigit() or int(idx) >= len(self._local_monitors):
            return None
        return self._local_monitors[int(idx)]

    def _on_remote_events(self, events: list[InputEvent]) -> None:
        """Handle events received from the remote peer via UDP."""
        for event in events:
            self._emulate.inject(event)
            self._injected_held.update(event)
            if self._state == AppState.CONTROLLED and isinstance(event, MouseMove):
                self._check_return_to_controller(event)

    def _release_injected(self) -> None:
        """Release keys/buttons the controller left held on this machine."""
        for release in self._injected_held.release_events():
            self._emulate.inject(release)

    def _check_return_to_controller(self, move: MouseMove) -> None:
        """Hand focus back if the injected cursor crossed toward the controller."""
        if self._edge_detector is None or self._controller_conn is None:
            return
        if self._injected_held.buttons:
            return  # mid-drag: keep the drag (and its release) on this machine
        # Ask the OS where the cursor really is: injected moves are subject
        # to acceleration and clamping, so summing deltas would drift.
        pos = self._emulate.cursor_position()
        if pos is not None:
            crossing = self._edge_detector.observe(pos[0], pos[1], move.dx, move.dy)
        else:
            crossing = self._edge_detector.update(move.dx, move.dy)
        if crossing is None or _peer_of(crossing.target_peer_id) != self._controller_id:
            return

        log.info(
            "Focus ← %s (entry: %d, %d)",
            crossing.target_peer_id, crossing.entry_x, crossing.entry_y,
        )
        conn = self._controller_conn
        self._state = AppState.ACTIVE_LOCAL
        self._controller_id = None
        self._controller_conn = None
        # Held modifiers would stay down here; the controller's physical
        # release now goes to its own OS.
        self._release_injected()
        if self._loop is not None:
            self._loop.create_task(conn.send_switch_focus(
                crossing.target_peer_id, crossing.entry_x, crossing.entry_y,
            ))


async def _await_hello(conn: ControlConnection, timeout: float = 5.0) -> bool:
    """Wait until the peer's hello has been received."""
    for _ in range(int(timeout / 0.1)):
        if conn.peer_info:
            return True
        await asyncio.sleep(0.1)
    return bool(conn.peer_info)


async def _send_clipboard(conn: ControlConnection, text: str) -> None:
    try:
        await conn.send_clipboard(text)
    except (ConnectionError, OSError):
        log.debug("Could not send clipboard; connection closed")


def _hostname_of(conn: ControlConnection, fallback: object) -> str:
    """The peer id a connection's hello announced."""
    return str(conn.peer_info.get("hostname", fallback))


def _monitors_from_hello(conn: ControlConnection) -> list[MonitorInfo]:
    """The peer's monitors, falling back to the legacy single ``screen`` key."""
    monitors = conn.peer_monitors
    if monitors:
        return monitors
    screen = conn.peer_info.get("screen")
    if not screen:
        return []
    return [MonitorInfo(
        name="screen",
        x=0,
        y=0,
        width=screen.get("width", 1920),
        height=screen.get("height", 1080),
        is_primary=True,
    )]


def _peer_of(screen_id: str) -> str:
    """Strip the ``:N`` monitor suffix from a layout key."""
    return screen_id.rsplit(":", 1)[0] if ":" in screen_id else screen_id
