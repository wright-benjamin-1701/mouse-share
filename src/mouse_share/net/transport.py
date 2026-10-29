"""Async UDP transport with event batching.

Coalesces mouse events at ~125Hz flush rate to reduce syscall overhead
while keeping latency under 8ms. Uses asyncio DatagramProtocol.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from mouse_share.event.codec import MAX_EVENTS_PER_BATCH, decode_batch, encode_batch
from mouse_share.event.types import InputEvent, MouseMove
from mouse_share.net.protocol import DEFAULT_UDP_PORT
from mouse_share.net.sockopt import SocketOptions, apply_udp_opts

if TYPE_CHECKING:
    from collections.abc import Callable

# Flush interval in seconds (~125Hz)
FLUSH_INTERVAL = 0.008


class UDPTransport(asyncio.DatagramProtocol):
    """Async UDP transport for batched input events.

    Outbound: events are queued and flushed at FLUSH_INTERVAL.
    Mouse moves are coalesced (deltas accumulated) to reduce packet count.

    Inbound: datagrams are decoded and passed to a callback.
    """

    def __init__(
        self,
        on_events: Callable[[list[InputEvent]], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._on_events = on_events
        self._on_error = on_error
        self._transport: asyncio.DatagramTransport | None = None
        self._send_queue: list[InputEvent] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._target: tuple[str, int] | None = None
        self._coalesce_dx: int = 0
        self._coalesce_dy: int = 0
        self._has_coalesced_move: bool = False

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            _version, _flags, events = decode_batch(data)
            self._on_events(events)
        except ValueError as e:
            if self._on_error:
                self._on_error(e)

    def error_received(self, exc: Exception) -> None:
        if self._on_error:
            self._on_error(exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()

    def set_target(self, host: str, port: int = DEFAULT_UDP_PORT) -> None:
        """Set the target peer address for sending events."""
        self._target = (host, port)

    def queue_event(self, event: InputEvent) -> None:
        """Queue an event for batched sending.

        MouseMove events are coalesced: their deltas are accumulated
        and emitted as a single event at flush time.
        """
        if isinstance(event, MouseMove):
            self._coalesce_dx += event.dx
            self._coalesce_dy += event.dy
            self._has_coalesced_move = True
        else:
            self._send_queue.append(event)

    def start_flush_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start the periodic flush task."""
        self._flush_task = loop.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        """Periodically flush queued events."""
        try:
            while True:
                await asyncio.sleep(FLUSH_INTERVAL)
                self._flush()
        except asyncio.CancelledError:
            self._flush()  # Final flush on shutdown

    def _flush(self) -> None:
        """Encode and send all queued events."""
        if self._transport is None or self._target is None:
            return

        # Prepend coalesced mouse move if present
        if self._has_coalesced_move:
            move = MouseMove(dx=self._coalesce_dx, dy=self._coalesce_dy)
            self._send_queue.insert(0, move)
            self._coalesce_dx = 0
            self._coalesce_dy = 0
            self._has_coalesced_move = False

        if not self._send_queue:
            return

        # Split into batches if needed (unlikely at 125Hz)
        while self._send_queue:
            batch = self._send_queue[:MAX_EVENTS_PER_BATCH]
            self._send_queue = self._send_queue[MAX_EVENTS_PER_BATCH:]
            try:
                data = encode_batch(batch)
                self._transport.sendto(data, self._target)
            except (ValueError, OSError):
                pass  # Drop on encode/send failure; fire-and-forget

    async def stop(self) -> None:
        """Stop the flush loop and close the transport."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
        if self._transport:
            self._transport.close()


async def create_udp_transport(
    on_events: Callable[[list[InputEvent]], None],
    bind_host: str = "0.0.0.0",
    bind_port: int = DEFAULT_UDP_PORT,
    on_error: Callable[[Exception], None] | None = None,
    sock_opts: SocketOptions | None = None,
) -> tuple[asyncio.DatagramTransport, UDPTransport]:
    """Create and bind a UDP transport with LAN-optimized socket options.

    Returns (asyncio_transport, protocol) tuple.
    Call protocol.start_flush_loop(loop) to begin batched sending.
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPTransport(on_events=on_events, on_error=on_error),
        local_addr=(bind_host, bind_port),
    )
    # Apply low-latency socket options to the underlying socket
    sock = transport.get_extra_info("socket")
    if sock is not None:
        apply_udp_opts(sock, sock_opts)
    protocol.start_flush_loop(loop)
    return transport, protocol  # type: ignore[return-value]
