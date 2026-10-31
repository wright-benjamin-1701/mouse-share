"""Configuration persistence — load/save app settings as JSON."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mouse_share.net.protocol import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT


@dataclass(frozen=True, slots=True)
class PeerConfig:
    """Connection details for a remote peer."""

    peer_id: str
    hostname: str
    tcp_port: int = DEFAULT_TCP_PORT
    udp_port: int = DEFAULT_UDP_PORT


@dataclass(frozen=True, slots=True)
class ScreenConfig:
    """A screen's position in the layout grid."""

    peer_id: str
    width: int
    height: int
    x: int = 0
    y: int = 0


@dataclass(frozen=True, slots=True)
class PlacementConfig:
    """Where a peer's monitors sit relative to ours.

    The offset is added to the peer's native monitor coordinates to place
    them in our layout space.
    """

    peer_id: str
    offset_x: int
    offset_y: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Top-level application configuration."""

    local_peer_id: str = ""
    screen_width: int = 1920
    screen_height: int = 1080
    tcp_port: int = DEFAULT_TCP_PORT
    udp_port: int = DEFAULT_UDP_PORT
    peers: list[PeerConfig] = field(default_factory=list)
    screens: list[ScreenConfig] = field(default_factory=list)
    monitors: list[ScreenConfig] = field(default_factory=list)
    placements: list[PlacementConfig] = field(default_factory=list)


def default_config_path() -> Path:
    """Platform-appropriate config file path."""
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Roaming" / "mouse-share"
    else:
        xdg = Path.home() / ".config"
        base = xdg / "mouse-share"
    return base / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from *path*, returning defaults if the file doesn't exist."""
    if path is None:
        path = default_config_path()

    if not path.exists():
        return AppConfig()

    data = json.loads(path.read_text("utf-8"))
    peers = [PeerConfig(**p) for p in data.get("peers", [])]
    screens = [ScreenConfig(**s) for s in data.get("screens", [])]
    monitors = [ScreenConfig(**m) for m in data.get("monitors", [])]
    placements = [PlacementConfig(**p) for p in data.get("placements", [])]
    return AppConfig(
        local_peer_id=data.get("local_peer_id", ""),
        screen_width=data.get("screen_width", 1920),
        screen_height=data.get("screen_height", 1080),
        tcp_port=data.get("tcp_port", DEFAULT_TCP_PORT),
        udp_port=data.get("udp_port", DEFAULT_UDP_PORT),
        peers=peers,
        screens=screens,
        monitors=monitors,
        placements=placements,
    )


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Persist *config* as JSON to *path*."""
    if path is None:
        path = default_config_path()

    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
