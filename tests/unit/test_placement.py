"""Tests for peer placement: default offsets, snapping, and mirroring."""

from __future__ import annotations

from mouse_share.edge.layout import Edge, ScreenLayout, default_offset, snap_offset
from mouse_share.screen import MonitorInfo

LOCAL = [
    MonitorInfo("A", 0, 0, 1920, 1080, True),
    MonitorInfo("B", 1920, 0, 2560, 1440, False),
]
# Peer with a negative-x secondary monitor, as Windows reports it
PEER = [
    MonitorInfo("P0", 0, 0, 1920, 1080, True),
    MonitorInfo("P1", -1280, 0, 1280, 1024, False),
]


def test_default_offset_right_matches_legacy_placement() -> None:
    # Legacy: peer's leftmost edge on our rightmost edge, tops aligned
    assert default_offset(LOCAL, PEER, Edge.RIGHT) == (4480 + 1280, 0)


def test_default_offset_left() -> None:
    assert default_offset(LOCAL, PEER, Edge.LEFT) == (-1920, 0)


def test_default_offset_above() -> None:
    assert default_offset(LOCAL, PEER, Edge.TOP) == (1280, -1080)


def test_snap_pulls_peer_flush_above() -> None:
    # Dropped slightly above and overlapping A: snaps flush to A's top
    ox, oy = snap_offset(LOCAL, PEER, 1300, -1000)
    assert oy == -1080
    assert ox == 1300


def test_snap_never_overlaps_local() -> None:
    ox, oy = snap_offset(LOCAL, PEER, 500, 300)
    layout = ScreenLayout()
    layout.add_peer_monitors("me", LOCAL)
    layout.add_peer_monitors("peer", PEER, offset_x=ox, offset_y=oy)
    for p in (s for k, s in layout.screens.items() if k.startswith("peer:")):
        for m in LOCAL:
            overlap_x = p.x < m.x + m.width and m.x < p.x + p.width
            overlap_y = p.y < m.y + m.height and m.y < p.y + p.height
            assert not (overlap_x and overlap_y)


def test_snap_keeps_overlap_along_edge() -> None:
    # Dragged far off to the side: slid back until it still shares an edge
    ox, oy = snap_offset(LOCAL, [PEER[0]], 9000, -1100)
    layout = ScreenLayout()
    layout.add_peer_monitors("me", LOCAL)
    layout.add_peer_monitors("peer", [PEER[0]], offset_x=ox, offset_y=oy)
    assert any(
        layout.get_adjacent(f"me:{i}", edge) is not None
        for i in range(len(LOCAL)) for edge in Edge
    )


def test_mirrored_placement_crosses_both_ways() -> None:
    # We put the peer above monitor A; the peer mirrors with the negated offset
    ox, oy = snap_offset(LOCAL, PEER, 0, -1080)
    ours = ScreenLayout()
    ours.add_peer_monitors("me", LOCAL)
    ours.add_peer_monitors("peer", PEER, offset_x=ox, offset_y=oy)
    theirs = ScreenLayout()
    theirs.add_peer_monitors("peer", PEER)
    theirs.add_peer_monitors("me", LOCAL, offset_x=-ox, offset_y=-oy)

    up = ours.map_edge_crossing("me:0", Edge.TOP, 100)
    assert up is not None
    assert up.target_peer_id.startswith("peer:")

    down = theirs.map_edge_crossing(up.target_peer_id, Edge.BOTTOM, up.entry_x)
    assert down is not None
    assert down.target_peer_id == "me:0"
