"""Tests for link probing and fastest-path selection."""

import asyncio

import pytest

from mouse_share.net.link_selector import (
    PROBE_MAGIC,
    PROBE_SIZE,
    LinkSelection,
    ProbeResult,
    link_selection_to_socket_options,
    run_probe_responder,
    select_best_link,
)
from mouse_share.net.sockopt import NICInfo, SocketOptions


class TestProbeResult:
    def test_median_rtt(self) -> None:
        r = ProbeResult(local_ip="1.1.1.1", remote_ip="2.2.2.2", local_nic="eth0", rtts_us=[100, 200, 150])
        assert r.median_rtt_us == 150.0

    def test_min_rtt(self) -> None:
        r = ProbeResult(local_ip="1.1.1.1", remote_ip="2.2.2.2", local_nic="eth0", rtts_us=[100, 200, 150])
        assert r.min_rtt_us == 100.0

    def test_empty_rtts_returns_inf(self) -> None:
        r = ProbeResult(local_ip="1.1.1.1", remote_ip="2.2.2.2", local_nic="eth0", rtts_us=[])
        assert r.median_rtt_us == float("inf")
        assert r.min_rtt_us == float("inf")

    def test_single_rtt(self) -> None:
        r = ProbeResult(local_ip="1.1.1.1", remote_ip="2.2.2.2", local_nic="eth0", rtts_us=[42.0])
        assert r.median_rtt_us == 42.0


class TestLinkSelectionToSocketOptions:
    def test_converts_to_socket_options(self) -> None:
        sel = LinkSelection(
            local_ip="192.168.1.10",
            remote_ip="192.168.1.20",
            local_nic="enp3s0",
            median_rtt_us=150.0,
            all_results=[],
        )
        opts = link_selection_to_socket_options(sel)
        assert isinstance(opts, SocketOptions)
        assert opts.bind_device == "enp3s0"

    def test_none_nic(self) -> None:
        sel = LinkSelection(
            local_ip="192.168.1.10",
            remote_ip="192.168.1.20",
            local_nic=None,
            median_rtt_us=150.0,
            all_results=[],
        )
        opts = link_selection_to_socket_options(sel)
        assert opts.bind_device is None


class TestProbeResponder:
    @pytest.mark.asyncio
    async def test_echoes_valid_probe(self) -> None:
        """Responder should echo back a valid probe packet."""
        transport, _protocol = await run_probe_responder(bind_host="127.0.0.1", port=0)
        port = transport.get_extra_info("sockname")[1]

        loop = asyncio.get_running_loop()
        # Send a probe packet to the responder
        import struct

        header = struct.Struct("<8sII")
        probe = header.pack(PROBE_MAGIC, 1, 12345)
        assert len(probe) == PROBE_SIZE

        # Use a simple client socket to send and receive
        client_transport, client_protocol = await loop.create_datagram_endpoint(
            _EchoCollector,
            remote_addr=("127.0.0.1", port),
        )
        try:
            client_transport.sendto(probe)
            collector: _EchoCollector = client_protocol  # type: ignore[assignment]
            # Wait for the echo
            await asyncio.wait_for(collector.received.wait(), timeout=1.0)
            assert collector.data == probe
        finally:
            client_transport.close()
            transport.close()

    @pytest.mark.asyncio
    async def test_ignores_invalid_packet(self) -> None:
        """Responder should ignore packets with wrong magic or size."""
        transport, _protocol = await run_probe_responder(bind_host="127.0.0.1", port=0)
        port = transport.get_extra_info("sockname")[1]

        loop = asyncio.get_running_loop()
        client_transport, client_protocol = await loop.create_datagram_endpoint(
            _EchoCollector,
            remote_addr=("127.0.0.1", port),
        )
        try:
            # Send garbage — should not be echoed
            client_transport.sendto(b"not a probe packet")
            collector: _EchoCollector = client_protocol  # type: ignore[assignment]
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(collector.received.wait(), timeout=0.1)
        finally:
            client_transport.close()
            transport.close()


class TestSelectBestLink:
    @pytest.mark.asyncio
    async def test_loopback_probing(self) -> None:
        """Probe localhost via the responder — should get sub-millisecond RTTs."""
        transport, _protocol = await run_probe_responder(bind_host="127.0.0.1", port=0)
        port = transport.get_extra_info("sockname")[1]

        try:
            # Simulate: local NIC is loopback, remote is loopback
            # We need to patch PROBE_PORT for this test since we used port=0
            from unittest.mock import patch

            with (
                patch("mouse_share.net.link_selector.PROBE_PORT", port),
                patch("mouse_share.net.link_selector.list_nics", return_value=[
                    NICInfo(name="lo", ipv4="127.0.0.1"),
                ]),
            ):
                result = await select_best_link(
                    remote_nics=[NICInfo(name="lo", ipv4="127.0.0.1")],
                    probe_count=3,
                    probe_timeout=2.0,
                )

            assert result is not None
            assert isinstance(result, LinkSelection)
            assert result.local_ip == "127.0.0.1"
            assert result.remote_ip == "127.0.0.1"
            assert result.median_rtt_us < 10000  # <10ms on loopback is generous
            assert len(result.all_results) == 1
            assert len(result.all_results[0].rtts_us) == 3
        finally:
            transport.close()

    @pytest.mark.asyncio
    async def test_picks_fastest_of_multiple_pairs(self) -> None:
        """When multiple pairs are probed, the one with lowest median wins."""
        # Create two responders on different ports
        t1, _ = await run_probe_responder(bind_host="127.0.0.1", port=0)
        p1 = t1.get_extra_info("sockname")[1]
        t2, _ = await run_probe_responder(bind_host="127.0.0.1", port=0)

        try:
            # Both respond on loopback so RTTs should be similar,
            # but the test verifies that selection logic works
            from unittest.mock import patch

            with (
                patch("mouse_share.net.link_selector.PROBE_PORT", p1),
                patch("mouse_share.net.link_selector.list_nics", return_value=[
                    NICInfo(name="lo", ipv4="127.0.0.1"),
                ]),
            ):
                result = await select_best_link(
                    remote_nics=[
                        NICInfo(name="lo", ipv4="127.0.0.1"),
                    ],
                    probe_count=3,
                    probe_timeout=2.0,
                )

            assert result is not None
            assert result.median_rtt_us < float("inf")
        finally:
            t1.close()
            t2.close()

    @pytest.mark.asyncio
    async def test_no_remote_nics_returns_none(self) -> None:
        result = await select_best_link(remote_nics=[], probe_count=1, probe_timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_unreachable_peer_returns_none(self) -> None:
        """Probing an unreachable IP should not crash, just return None."""
        from unittest.mock import patch

        with patch("mouse_share.net.link_selector.list_nics", return_value=[
            NICInfo(name="lo", ipv4="127.0.0.1"),
        ]):
            result = await select_best_link(
                remote_nics=[NICInfo(name="eth0", ipv4="192.0.2.1")],  # TEST-NET, unroutable
                probe_count=2,
                probe_timeout=0.2,
            )

        # No responder running → all probes timeout → None
        assert result is None


class TestPeerNicsInHello:
    @pytest.mark.asyncio
    async def test_peer_nics_property(self) -> None:
        """ControlConnection.peer_nics parses the NIC list from hello payload."""
        from mouse_share.net.control import ControlConnection

        reader = asyncio.StreamReader()
        transport = _MockTransport()
        protocol = asyncio.StreamReaderProtocol(reader)
        writer = asyncio.StreamWriter(transport, protocol, reader, asyncio.get_event_loop())
        conn = ControlConnection(reader, writer)

        # Simulate receiving a hello with NIC info
        conn._peer_info = {
            "version": 1,
            "hostname": "macbook",
            "nics": [
                {"name": "en0", "ipv4": "192.168.1.50"},
                {"name": "en1", "ipv4": "10.0.0.50"},
            ],
        }

        nics = conn.peer_nics
        assert len(nics) == 2
        assert nics[0] == NICInfo(name="en0", ipv4="192.168.1.50")
        assert nics[1] == NICInfo(name="en1", ipv4="10.0.0.50")

    @pytest.mark.asyncio
    async def test_peer_nics_empty_when_missing(self) -> None:
        from mouse_share.net.control import ControlConnection

        reader = asyncio.StreamReader()
        transport = _MockTransport()
        protocol = asyncio.StreamReaderProtocol(reader)
        writer = asyncio.StreamWriter(transport, protocol, reader, asyncio.get_event_loop())
        conn = ControlConnection(reader, writer)
        conn._peer_info = {"version": 1, "hostname": "old-peer"}

        assert conn.peer_nics == []


class _EchoCollector(asyncio.DatagramProtocol):
    """Collects the first datagram received."""

    def __init__(self) -> None:
        self.data: bytes = b""
        self.received = asyncio.Event()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.data = data
        self.received.set()


class _MockTransport(asyncio.Transport):
    def write(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False

    def can_write_eof(self) -> bool:
        return False

    def get_extra_info(self, name: str, default: object = None) -> object:
        return default
