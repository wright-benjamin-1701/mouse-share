"""Low-latency socket optimizations for direct LAN connections.

Applies platform-aware setsockopt calls to minimize latency on a dedicated
ethernet link. Linux-only options are guarded and silently skipped elsewhere.

Key optimizations:
- IP_TOS / DSCP EF (0xB8): marks packets as Expedited Forwarding so switches
  and NIC hardware prioritize them over bulk traffic.
- SO_PRIORITY (Linux): kernel-level packet priority, complements DSCP.
- SO_BUSY_POLL (Linux): kernel spins on the NIC receive queue instead of
  sleeping, cutting receive latency from ~50μs to ~5μs.
- TCP_NODELAY: disables Nagle's algorithm — never buffer small writes.
- SO_RCVBUF / SO_SNDBUF: modest buffer sizes to avoid bloat on a LAN where
  RTT is <1ms.
- SO_BINDTODEVICE (Linux, optional): pins the socket to a specific NIC,
  bypassing routing table lookups entirely.
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import sys
from dataclasses import dataclass

# DSCP Expedited Forwarding = 0x2E << 2 = 0xB8
DSCP_EF: int = 0xB8

# Linux-only socket option constants (not in the socket module on all platforms)
_SO_BUSY_POLL = 46  # linux/socket.h
_SO_PRIORITY = 12  # linux/socket.h SO_PRIORITY

_IS_LINUX = sys.platform == "linux"


@dataclass(frozen=True, slots=True)
class SocketOptions:
    """Tunable socket parameters for LAN-optimized transport.

    All options have sensible defaults for a dedicated ethernet link.
    Set bind_device to the NIC name (e.g. "eth0", "enp3s0") to pin traffic.
    """

    dscp_tos: int = DSCP_EF
    priority: int = 6  # Linux SO_PRIORITY (6 = interactive)
    busy_poll_us: int = 50  # microseconds to busy-poll on receive
    recv_buf: int = 256 * 1024  # 256 KiB
    send_buf: int = 256 * 1024  # 256 KiB
    tcp_nodelay: bool = True
    bind_device: str | None = None  # NIC name for SO_BINDTODEVICE


def apply_udp_opts(sock: socket.socket, opts: SocketOptions | None = None) -> None:
    """Apply low-latency socket options to a UDP socket."""
    if opts is None:
        opts = SocketOptions()

    # DSCP / TOS — works on all platforms
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, opts.dscp_tos)

    # Buffer sizes
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, opts.recv_buf)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, opts.send_buf)

    if _IS_LINUX:
        _apply_linux_opts(sock, opts)


def apply_tcp_opts(sock: socket.socket, opts: SocketOptions | None = None) -> None:
    """Apply low-latency socket options to a TCP socket."""
    if opts is None:
        opts = SocketOptions()

    # TCP_NODELAY — disable Nagle on all platforms
    if opts.tcp_nodelay:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # DSCP / TOS
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, opts.dscp_tos)

    # Buffer sizes
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, opts.recv_buf)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, opts.send_buf)

    if _IS_LINUX:
        _apply_linux_opts(sock, opts)


def _apply_linux_opts(sock: socket.socket, opts: SocketOptions) -> None:
    """Apply Linux-specific socket options. Only called on Linux."""
    # SO_PRIORITY — kernel packet priority (may require CAP_NET_ADMIN for priority > 6)
    with contextlib.suppress(OSError):
        sock.setsockopt(socket.SOL_SOCKET, _SO_PRIORITY, opts.priority)

    # SO_BUSY_POLL — spin on receive for lower latency (requires kernel support)
    if opts.busy_poll_us > 0:
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, _SO_BUSY_POLL, opts.busy_poll_us)

    # SO_BINDTODEVICE — pin to a specific NIC (requires CAP_NET_RAW or root)
    if opts.bind_device is not None:
        with contextlib.suppress(OSError):
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                opts.bind_device.encode("utf-8"),
            )


# ---------------------------------------------------------------------------
# NIC auto-detection
# ---------------------------------------------------------------------------


def detect_nic_for_peer(peer_host: str) -> str | None:
    """Detect which local NIC would route traffic to a given peer IP.

    Uses a non-blocking UDP connect (no actual traffic) to let the kernel's
    routing table pick the outbound interface, then maps the resulting local
    IP back to an interface name.

    Returns the NIC name (e.g. "enp3s0") or None if detection fails.
    """
    local_ip = _get_local_ip_for_peer(peer_host)
    if local_ip is None:
        return None
    return _ip_to_nic_name(local_ip)


def list_nics() -> list[NICInfo]:
    """List all non-loopback network interfaces with their IPv4 addresses.

    Returns a list of NICInfo sorted by name. Useful for GUI display
    or letting the user pick an interface.
    """
    result: list[NICInfo] = []
    for name, addrs in _get_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and not _is_loopback(addr.address):
                result.append(NICInfo(name=name, ipv4=addr.address))
    result.sort(key=lambda n: n.name)
    return result


@dataclass(frozen=True, slots=True)
class NICInfo:
    """Basic info about a network interface."""

    name: str
    ipv4: str


def auto_socket_options(peer_host: str) -> SocketOptions:
    """Create SocketOptions with auto-detected bind_device for a peer.

    On Linux, detects which NIC routes to the peer and pins traffic to it.
    On other platforms, returns default options (bind_device stays None).
    """
    bind_device = None
    if _IS_LINUX:
        bind_device = detect_nic_for_peer(peer_host)
    return SocketOptions(bind_device=bind_device)


def _get_local_ip_for_peer(peer_host: str) -> str | None:
    """Determine which local IP the kernel would use to reach a peer.

    Creates a UDP socket and connects it (no traffic sent) — the kernel
    fills in the source address from the routing table.
    """
    try:
        # Resolve hostname to IP if needed
        infos = socket.getaddrinfo(peer_host, 80, socket.AF_INET, socket.SOCK_DGRAM)
        if not infos:
            return None
        peer_ip = infos[0][4][0]

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((peer_ip, 1))  # Port doesn't matter, no traffic sent
            local_ip: str = sock.getsockname()[0]
            if _is_loopback(local_ip):
                return None
            return local_ip
        finally:
            sock.close()
    except OSError:
        return None


def _ip_to_nic_name(target_ip: str) -> str | None:
    """Map a local IP address to its network interface name."""
    for name, addrs in _get_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address == target_ip:
                return name
    return None


def _get_if_addrs() -> dict[str, list[_IfAddr]]:
    """Enumerate network interfaces and their IPv4 addresses.

    Uses `ip` command on Linux, falls back to hostname-based lookup elsewhere.
    """
    if _IS_LINUX:
        result = _enumerate_linux_interfaces()
        if result:
            return result
    return _enumerate_interfaces_fallback()


class _IfAddr:
    """Minimal stand-in for interface address info."""

    __slots__ = ("family", "address")

    def __init__(self, family: socket.AddressFamily, address: str) -> None:
        self.family = family
        self.address = address


def _enumerate_linux_interfaces() -> dict[str, list[_IfAddr]]:
    """Enumerate interfaces on Linux using /proc/net/fib_trie or ip command."""
    import subprocess  # noqa: PLC0415

    result: dict[str, list[_IfAddr]] = {}
    try:
        output = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show"],  # noqa: S603, S607
            text=True,
            timeout=5,
        )
        for line in output.strip().splitlines():
            # Format: "2: enp3s0    inet 192.168.1.100/24 brd 192.168.1.255 scope global enp3s0"
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "inet":
                name = parts[1].rstrip(":")
                ip_cidr = parts[3]
                ip_addr = ip_cidr.split("/")[0]
                result.setdefault(name, []).append(_IfAddr(socket.AF_INET, ip_addr))
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return result


def _enumerate_interfaces_fallback() -> dict[str, list[_IfAddr]]:
    """Cross-platform fallback: use socket.getaddrinfo on the hostname."""
    result: dict[str, list[_IfAddr]] = {}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not _is_loopback(ip):
                # We don't know the interface name in this fallback
                result.setdefault("unknown", []).append(_IfAddr(socket.AF_INET, ip))
    except OSError:
        pass
    return result


def _is_loopback(ip: str) -> bool:
    """Check if an IP is a loopback address."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False
