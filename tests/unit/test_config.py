"""Tests for config.py — round-trip save/load, defaults, missing file."""

from pathlib import Path

from mouse_share.config import (
    AppConfig,
    PeerConfig,
    PlacementConfig,
    ScreenConfig,
    load_config,
    save_config,
)


class TestDefaults:
    def test_default_config(self) -> None:
        cfg = AppConfig()
        assert cfg.screen_width == 1920
        assert cfg.screen_height == 1080
        assert cfg.tcp_port == 24800
        assert cfg.udp_port == 24801
        assert cfg.peers == []
        assert cfg.screens == []
        assert cfg.monitors == []

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "nonexistent.json")
        assert cfg == AppConfig()


class TestRoundTrip:
    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        original = AppConfig(
            local_peer_id="my-pc",
            screen_width=2560,
            screen_height=1440,
            tcp_port=25000,
            udp_port=25001,
            peers=[PeerConfig("remote", "192.168.1.50", 25000, 25001)],
            screens=[ScreenConfig("remote", 1920, 1080, 2560, 0)],
        )
        save_config(original, path)
        loaded = load_config(path)
        assert loaded == original

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "config.json"
        save_config(AppConfig(), path)
        assert path.exists()

    def test_partial_config_fills_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text('{"local_peer_id": "test", "screen_width": 3840}')
        cfg = load_config(path)
        assert cfg.local_peer_id == "test"
        assert cfg.screen_width == 3840
        assert cfg.screen_height == 1080  # default
        assert cfg.peers == []

    def test_monitors_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        original = AppConfig(
            local_peer_id="test",
            monitors=[
                ScreenConfig("local", 1920, 1080, 0, 0),
                ScreenConfig("local", 2560, 1440, 1920, 0),
            ],
        )
        save_config(original, path)
        loaded = load_config(path)
        assert loaded.monitors == original.monitors
        assert len(loaded.monitors) == 2

    def test_placements_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        original = AppConfig(
            local_peer_id="test",
            placements=[PlacementConfig("laptop", 0, -1080), PlacementConfig("htpc", -2560, 0)],
        )
        save_config(original, path)
        assert load_config(path).placements == original.placements

    def test_missing_placements_defaults_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text('{"local_peer_id": "test"}')
        assert load_config(path).placements == []
