"""Tests for LAN socket optimizations."""

import socket

import pytest

from mouse_share.net.sockopt import (
    _IS_LINUX,
    DSCP_EF,
    NICInfo,
    SocketOptions,
    apply_tcp_opts,
    apply_udp_opts,
    auto_socket_options,
    detect_nic_for_peer,
    list_nics,
)


class TestSocketOptionsDefaults:
    def test_defaults(self) -> None:
        opts = SocketOptions()
        assert opts.dscp_tos == DSCP_EF
        assert opts.tcp_nodelay is True
        assert opts.busy_poll_us == 50
        assert opts.bind_device is None
        assert opts.recv_buf == 256 * 1024
        assert opts.send_buf == 256 * 1024

    def test_frozen(self) -> None:
        opts = SocketOptions()
        with pytest.raises(AttributeError):
            opts.dscp_tos = 0  # type: ignore[misc]

    def test_custom_values(self) -> None:
        opts = SocketOptions(dscp_tos=0x00, priority=3, bind_device="eth0")
        assert opts.dscp_tos == 0x00
        assert opts.priority == 3
        assert opts.bind_device == "eth0"


class TestApplyUDPOpts:
    def test_applies_tos(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            apply_udp_opts(sock)
            tos = sock.getsockopt(socket.IPPROTO_IP, socket.IP_TOS)
            assert tos == DSCP_EF
        finally:
            sock.close()

    def test_applies_buffer_sizes(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            opts = SocketOptions(recv_buf=128 * 1024, send_buf=128 * 1024)
            apply_udp_opts(sock, opts)
            # Kernel may double the value, so check it's at least what we asked
            rcv = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            snd = sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
            assert rcv >= 128 * 1024
            assert snd >= 128 * 1024
        finally:
            sock.close()

    def test_custom_tos(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            opts = SocketOptions(dscp_tos=0x00)
            apply_udp_opts(sock, opts)
            tos = sock.getsockopt(socket.IPPROTO_IP, socket.IP_TOS)
            assert tos == 0x00
        finally:
            sock.close()

    def test_default_opts_when_none(self) -> None:
        """Passing None uses default SocketOptions."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            apply_udp_opts(sock, None)
            tos = sock.getsockopt(socket.IPPROTO_IP, socket.IP_TOS)
            assert tos == DSCP_EF
        finally:
            sock.close()


class TestApplyTCPOpts:
    def test_applies_nodelay(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            apply_tcp_opts(sock)
            nodelay = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            assert nodelay == 1
        finally:
            sock.close()

    def test_nodelay_disabled(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            opts = SocketOptions(tcp_nodelay=False)
            apply_tcp_opts(sock, opts)
            nodelay = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            assert nodelay == 0
        finally:
            sock.close()

    def test_applies_tos(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            apply_tcp_opts(sock)
            tos = sock.getsockopt(socket.IPPROTO_IP, socket.IP_TOS)
            assert tos == DSCP_EF
        finally:
            sock.close()


@pytest.mark.skipif(not _IS_LINUX, reason="Linux-only socket options")
class TestLinuxOpts:
    def test_so_priority_applied(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            apply_udp_opts(sock, SocketOptions(priority=6))
            # SO_PRIORITY = 12 on Linux
            prio = sock.getsockopt(socket.SOL_SOCKET, 12)
            assert prio == 6
        finally:
            sock.close()

    def test_bind_device_skipped_without_perms(self) -> None:
        """SO_BINDTODEVICE typically needs CAP_NET_RAW — should not crash."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Use a nonsense device name; should silently fail
            apply_udp_opts(sock, SocketOptions(bind_device="nonexistent99"))
        finally:
            sock.close()


@pytest.mark.skipif(_IS_LINUX, reason="Tests non-Linux platform guard")
class TestNonLinuxGuard:
    def test_linux_opts_skipped(self) -> None:
        """On non-Linux, Linux-specific opts should be silently skipped."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Should not raise even with Linux-specific options set
            apply_udp_opts(sock, SocketOptions(priority=6, busy_poll_us=50, bind_device="eth0"))
        finally:
            sock.close()


class TestNICDetection:
    def test_detect_nic_for_loopback_returns_none(self) -> None:
        """Loopback peer should not return a NIC (it's not a real interface)."""
        result = detect_nic_for_peer("127.0.0.1")
        assert result is None

    def test_detect_nic_for_invalid_host_returns_none(self) -> None:
        result = detect_nic_for_peer("999.999.999.999")
        assert result is None

    def test_detect_nic_for_lan_peer(self) -> None:
        """Detecting NIC for a LAN-like IP should return a string or None (no crash)."""
        result = detect_nic_for_peer("192.168.1.1")
        # On a machine with a LAN interface this returns a string; on CI it may be None
        assert result is None or isinstance(result, str)

    def test_detect_nic_for_hostname(self) -> None:
        """Should handle hostnames, not just IPs."""
        result = detect_nic_for_peer("localhost")
        # localhost resolves to 127.0.0.1 → loopback → None
        assert result is None

    def test_list_nics_returns_list(self) -> None:
        nics = list_nics()
        assert isinstance(nics, list)
        for nic in nics:
            assert isinstance(nic, NICInfo)
            assert isinstance(nic.name, str)
            assert isinstance(nic.ipv4, str)

    def test_list_nics_excludes_loopback(self) -> None:
        nics = list_nics()
        for nic in nics:
            assert not nic.ipv4.startswith("127."), f"Loopback should be excluded: {nic}"

    @pytest.mark.skipif(not _IS_LINUX, reason="Linux-only NIC detection")
    def test_list_nics_has_entries_on_linux(self) -> None:
        """On a Linux machine with network, we should find at least one NIC."""
        nics = list_nics()
        assert len(nics) > 0, "Expected at least one non-loopback NIC on Linux"

    def test_auto_socket_options_for_peer(self) -> None:
        """auto_socket_options should return valid SocketOptions without crashing."""
        opts = auto_socket_options("192.168.1.1")
        assert isinstance(opts, SocketOptions)
        # bind_device is either a string (if NIC detected) or None
        assert opts.bind_device is None or isinstance(opts.bind_device, str)
        # All other fields should be defaults
        assert opts.dscp_tos == DSCP_EF
        assert opts.tcp_nodelay is True

    def test_auto_socket_options_for_unreachable(self) -> None:
        """Unreachable peer should still return valid options with bind_device=None."""
        opts = auto_socket_options("999.999.999.999")
        assert opts.bind_device is None

    def test_nic_info_frozen(self) -> None:
        nic = NICInfo(name="eth0", ipv4="192.168.1.100")
        assert nic.name == "eth0"
        assert nic.ipv4 == "192.168.1.100"
        with pytest.raises(AttributeError):
            nic.name = "eth1"  # type: ignore[misc]
