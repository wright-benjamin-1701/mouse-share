"""Fastest-link selection via UDP latency probing.

When two machines share multiple network paths (e.g. ethernet + Wi-Fi),
this module probes each reachable IP pair with timed UDP round-trips
and picks the one with the lowest median latency.

Protocol:
  - Prober sends a 16-byte datagram: b"MSPROBE!" + sequence:u32 + timestamp_ns:u32 (LE)
  - Responder echoes it back unchanged.
  - Prober measures round-trip time from the embedded timestamp.

Probe port is DEFAULT_UDP_PORT + 1 (24802) to avoid conflicting with
the main event transport during probing.
"""

from __future__ import annotations

import asyncio
import statistics
import struct
import time
from dataclasses import dataclass

from mouse_share.net.protocol import DEFAULT_UDP_PORT
from mouse_share.net.sockopt import NICInfo, SocketOptions, list_nics

PROBE_PORT = DEFAULT_UDP_PORT + 1
PROBE_MAGIC = b"MSPROBE!"
PROBE_HEADER = struct.Struct("<8sII")  # magic(8) + seq(u32) + timestamp_ns(u32)
PROBE_SIZE = PROBE_HEADER.size  # 16 bytes

DEFAULT_PROBE_COUNT = 5
DEFAULT_PROBE_TIMEOUT = 0.5  # seconds per probe round
DEFAULT_PROBE_INTERVAL = 0.02  # 20ms between probes


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Result of probing a single IP pair."""

    local_ip: str
    remote_ip: str
    local_nic: str | None
    rtts_us: list[float]  # round-trip times in microseconds

    @property
    def median_rtt_us(self) -> float:
        """Median RTT in microseconds. Returns inf if no successful probes."""
        if not self.rtts_us:
            return float("inf")
        return statistics.median(self.rtts_us)

    @property
    def min_rtt_us(self) -> float:
        if not self.rtts_us:
            return float("inf")
        return min(self.rtts_us)

    @property
    def loss_pct(self) -> float:
        """Packet loss as a percentage (0-100)."""
        # Total probes sent is not tracked here; caller knows probe_count
        return 0.0  # Filled in by the caller


@dataclass(frozen=True, slots=True)
class LinkSelection:
    """The winning link after probing all candidate pairs."""

    local_ip: str
    remote_ip: str
    local_nic: str | None
    median_rtt_us: float
    all_results: list[ProbeResult]


async def select_best_link(
    remote_nics: list[NICInfo],
    probe_count: int = DEFAULT_PROBE_COUNT,
    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
) -> LinkSelection | None:
    """Probe all reachable IP pairs and return the fastest link.

    Args:
        remote_nics: List of the peer's non-loopback NICs (from hello handshake).
        probe_count: Number of probe packets per IP pair.
        probe_timeout: Max time to wait for all probes on one pair.

    Returns:
        LinkSelection with the best pair, or None if no pair is reachable.
    """
    local = list_nics()
    if not local or not remote_nics:
        return None

    # Probe all pairs concurrently
    tasks = []
    for local_nic in local:
        for remote_nic in remote_nics:
            tasks.append(
                _probe_pair(local_nic, remote_nic.ipv4, probe_count, probe_timeout)
            )

    results: list[ProbeResult] = await asyncio.gather(*tasks)

    # Filter to reachable pairs and pick lowest median RTT
    reachable = [r for r in results if r.rtts_us]
    if not reachable:
        return None

    best = min(reachable, key=lambda r: r.median_rtt_us)
    return LinkSelection(
        local_ip=best.local_ip,
        remote_ip=best.remote_ip,
        local_nic=best.local_nic,
        median_rtt_us=best.median_rtt_us,
        all_results=results,
    )


def link_selection_to_socket_options(selection: LinkSelection) -> SocketOptions:
    """Convert a LinkSelection into SocketOptions with the winning NIC bound."""
    return SocketOptions(bind_device=selection.local_nic)


async def run_probe_responder(
    bind_host: str = "0.0.0.0",
    port: int = PROBE_PORT,
) -> tuple[asyncio.DatagramTransport, _ProbeResponder]:
    """Start a UDP probe responder that echoes probe packets back.

    Run this on both peers before calling select_best_link().
    Returns (transport, protocol) — call transport.close() to stop.
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _ProbeResponder,
        local_addr=(bind_host, port),
    )
    return transport, protocol  # type: ignore[return-value]


class _ProbeResponder(asyncio.DatagramProtocol):
    """Echoes valid probe packets back to sender."""

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) == PROBE_SIZE and data[:8] == PROBE_MAGIC:
            self.transport.sendto(data, addr)  # type: ignore[union-attr]

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport


async def _probe_pair(
    local_nic: NICInfo,
    remote_ip: str,
    probe_count: int,
    timeout: float,
) -> ProbeResult:
    """Send probe packets from a local NIC to a remote IP and measure RTTs."""
    rtts: list[float] = []
    loop = asyncio.get_running_loop()

    try:
        # Bind to the specific local IP so traffic goes through the right NIC
        transport, protocol = await loop.create_datagram_endpoint(
            _ProbeClient,
            local_addr=(local_nic.ipv4, 0),
            remote_addr=(remote_ip, PROBE_PORT),
        )
    except OSError:
        # Can't bind or route — this pair is unreachable
        return ProbeResult(
            local_ip=local_nic.ipv4,
            remote_ip=remote_ip,
            local_nic=local_nic.name,
            rtts_us=[],
        )

    try:
        client: _ProbeClient = protocol  # type: ignore[assignment]
        for seq in range(probe_count):
            rtt = await asyncio.wait_for(
                client.send_probe(seq),
                timeout=timeout / probe_count,
            )
            if rtt is not None:
                rtts.append(rtt)
            if seq < probe_count - 1:
                await asyncio.sleep(DEFAULT_PROBE_INTERVAL)
    except (TimeoutError, OSError):
        pass
    finally:
        transport.close()

    return ProbeResult(
        local_ip=local_nic.ipv4,
        remote_ip=remote_ip,
        local_nic=local_nic.name,
        rtts_us=rtts,
    )


class _ProbeClient(asyncio.DatagramProtocol):
    """Sends probe packets and measures round-trip times.

    Timestamps are kept locally (not recovered from the packet) to avoid
    u32 truncation issues. The packet carries the seq number for correlation;
    the responder echoes it back unchanged.
    """

    def __init__(self) -> None:
        self._transport: asyncio.DatagramTransport | None = None
        self._pending: dict[int, asyncio.Future[float]] = {}
        self._send_times: dict[int, int] = {}  # seq → monotonic_ns at send

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) != PROBE_SIZE or data[:8] != PROBE_MAGIC:
            return
        _, seq, _ = PROBE_HEADER.unpack(data)
        recv_ns = time.monotonic_ns()
        send_ns = self._send_times.pop(seq, None)
        if send_ns is None:
            return
        rtt_us = (recv_ns - send_ns) / 1000.0
        fut = self._pending.pop(seq, None)
        if fut and not fut.done():
            fut.set_result(rtt_us)

    async def send_probe(self, seq: int) -> float | None:
        """Send one probe and wait for the echo. Returns RTT in microseconds."""
        if self._transport is None:
            return None

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[float] = loop.create_future()
        self._pending[seq] = fut

        self._send_times[seq] = time.monotonic_ns()
        packet = PROBE_HEADER.pack(PROBE_MAGIC, seq, 0)
        self._transport.sendto(packet)

        try:
            return await fut
        except asyncio.CancelledError:
            self._pending.pop(seq, None)
            self._send_times.pop(seq, None)
            return None
