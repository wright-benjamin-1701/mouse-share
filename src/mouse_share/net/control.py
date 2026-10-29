"""TCP control channel for handshake, configuration, clipboard, and latency measurement.

Uses length-prefixed JSON messages (see net.protocol).
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import time
from typing import Any

from mouse_share.net.protocol import (
    DEFAULT_TCP_PORT,
    PROTOCOL_VERSION,
    ControlMessageType,
    decode_control_message,
    encode_control_message,
    read_length_prefixed,
)
from mouse_share.net.sockopt import SocketOptions, apply_tcp_opts


class ControlConnection:
    """A single TCP control channel to a peer.

    Handles sending/receiving control messages and tracks latency.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._peer_info: dict[str, Any] = {}
        self._latency_ms: float | None = None
        self._ping_sent_at: float | None = None
        self._handlers: dict[ControlMessageType, list[Any]] = {}
        self._closed = False

    @property
    def peer_info(self) -> dict[str, Any]:
        return self._peer_info

    @property
    def latency_ms(self) -> float | None:
        return self._latency_ms

    @property
    def closed(self) -> bool:
        return self._closed

    def on(self, msg_type: ControlMessageType, handler: Any) -> None:
        """Register a handler for a message type. Handler signature: async (payload) -> None."""
        self._handlers.setdefault(msg_type, []).append(handler)

    async def send(self, msg_type: ControlMessageType, payload: dict[str, Any] | None = None) -> None:
        """Send a control message to the peer."""
        if self._closed:
            raise ConnectionError("Connection is closed")
        data = encode_control_message(msg_type, payload or {})
        self._writer.write(data)
        await self._writer.drain()

    async def send_hello(self, screen_width: int, screen_height: int) -> None:
        """Send a hello handshake message."""
        await self.send(ControlMessageType.HELLO, {
            "version": PROTOCOL_VERSION,
            "hostname": platform.node(),
            "platform": platform.system().lower(),
            "screen": {"width": screen_width, "height": screen_height},
        })

    async def send_ping(self) -> None:
        """Send a ping for latency measurement."""
        self._ping_sent_at = time.monotonic()
        await self.send(ControlMessageType.PING, {"timestamp": self._ping_sent_at})

    async def send_switch_focus(self, target_peer: str, entry_x: int, entry_y: int) -> None:
        """Notify peer of an edge-crossing focus switch."""
        await self.send(ControlMessageType.SWITCH_FOCUS, {
            "target": target_peer,
            "entry_x": entry_x,
            "entry_y": entry_y,
        })

    async def send_clipboard(self, content: str, content_type: str = "text/plain") -> None:
        """Send clipboard content to the peer."""
        await self.send(ControlMessageType.CLIPBOARD_UPDATE, {
            "content": content,
            "content_type": content_type,
        })

    async def run(self) -> None:
        """Read and dispatch messages until the connection is closed."""
        try:
            while not self._closed:
                data = await read_length_prefixed(self._reader)
                msg_type, payload = decode_control_message(data)

                # Built-in handling for hello and ping/pong
                if msg_type == ControlMessageType.HELLO:
                    self._peer_info = payload
                elif msg_type == ControlMessageType.PONG:
                    if self._ping_sent_at is not None:
                        self._latency_ms = (time.monotonic() - self._ping_sent_at) * 1000
                        self._ping_sent_at = None
                elif msg_type == ControlMessageType.PING:
                    await self.send(ControlMessageType.PONG, payload)

                # Dispatch to registered handlers
                for handler in self._handlers.get(msg_type, []):
                    await handler(payload)

        except (asyncio.IncompleteReadError, ConnectionError):
            pass  # Peer disconnected
        finally:
            self._closed = True

    async def close(self) -> None:
        """Close the connection."""
        self._closed = True
        self._writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await self._writer.wait_closed()


class ControlServer:
    """TCP server accepting control connections from peers."""

    def __init__(self, on_connection: Any, sock_opts: SocketOptions | None = None) -> None:
        self._on_connection = on_connection
        self._sock_opts = sock_opts
        self._server: asyncio.Server | None = None

    async def start(self, host: str = "0.0.0.0", port: int = DEFAULT_TCP_PORT) -> None:
        self._server = await asyncio.start_server(self._handle_client, host, port)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        if sock is not None:
            apply_tcp_opts(sock, self._sock_opts)
        conn = ControlConnection(reader, writer)
        await self._on_connection(conn)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


async def connect_to_peer(
    host: str,
    port: int = DEFAULT_TCP_PORT,
    sock_opts: SocketOptions | None = None,
) -> ControlConnection:
    """Establish a TCP control connection to a peer with LAN-optimized socket options."""
    reader, writer = await asyncio.open_connection(host, port)
    sock = writer.get_extra_info("socket")
    if sock is not None:
        apply_tcp_opts(sock, sock_opts)
    return ControlConnection(reader, writer)
