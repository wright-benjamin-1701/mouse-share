"""Tests for binary codec round-trips."""

import pytest

from mouse_share.event.codec import (
    MAX_EVENTS_PER_BATCH,
    PROTOCOL_VERSION,
    decode_batch,
    encode_batch,
)
from mouse_share.event.types import (
    KeyPress,
    KeyRelease,
    MouseButton,
    MouseButtonCode,
    MouseMove,
    MouseScroll,
)


class TestEncodeDecodeBatch:
    def test_single_mouse_move(self) -> None:
        events = [MouseMove(dx=100, dy=-50)]
        data = encode_batch(events)
        version, flags, decoded = decode_batch(data)
        assert version == PROTOCOL_VERSION
        assert flags == 0
        assert len(decoded) == 1
        assert decoded[0] == MouseMove(dx=100, dy=-50)

    def test_single_mouse_button(self) -> None:
        events = [MouseButton(button=MouseButtonCode.RIGHT, pressed=True)]
        data = encode_batch(events)
        _, _, decoded = decode_batch(data)
        assert decoded[0] == MouseButton(button=MouseButtonCode.RIGHT, pressed=True)

    def test_single_mouse_scroll(self) -> None:
        events = [MouseScroll(dx=0, dy=-120)]
        data = encode_batch(events)
        _, _, decoded = decode_batch(data)
        assert decoded[0] == MouseScroll(dx=0, dy=-120)

    def test_key_press_release_round_trip(self) -> None:
        events = [KeyPress(scancode=0x04), KeyRelease(scancode=0x04)]
        data = encode_batch(events)
        _, _, decoded = decode_batch(data)
        assert decoded == events

    def test_mixed_batch(self) -> None:
        events = [
            MouseMove(dx=10, dy=20),
            MouseButton(button=MouseButtonCode.LEFT, pressed=True),
            KeyPress(scancode=0x1A),
            MouseMove(dx=-5, dy=3),
            KeyRelease(scancode=0x1A),
            MouseButton(button=MouseButtonCode.LEFT, pressed=False),
            MouseScroll(dx=0, dy=3),
        ]
        data = encode_batch(events)
        _, _, decoded = decode_batch(data)
        assert decoded == events

    def test_max_batch_size(self) -> None:
        events = [MouseMove(dx=i, dy=i) for i in range(MAX_EVENTS_PER_BATCH)]
        data = encode_batch(events)
        _, _, decoded = decode_batch(data)
        assert len(decoded) == MAX_EVENTS_PER_BATCH

    def test_exceeds_max_batch_raises(self) -> None:
        events = [MouseMove(dx=0, dy=0)] * (MAX_EVENTS_PER_BATCH + 1)
        with pytest.raises(ValueError, match="exceeds max"):
            encode_batch(events)

    def test_empty_batch_raises(self) -> None:
        with pytest.raises(ValueError, match="empty batch"):
            encode_batch([])

    def test_negative_deltas(self) -> None:
        events = [MouseMove(dx=-32768, dy=32767)]
        data = encode_batch(events)
        _, _, decoded = decode_batch(data)
        assert decoded[0] == MouseMove(dx=-32768, dy=32767)

    def test_flags_preserved(self) -> None:
        events = [KeyPress(scancode=0x10)]
        data = encode_batch(events, flags=0xAB)
        version, flags, _ = decode_batch(data)
        assert flags == 0xAB

    def test_truncated_header_raises(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            decode_batch(b"\x01\x00")

    def test_truncated_event_raises(self) -> None:
        events = [MouseMove(dx=1, dy=2)]
        data = encode_batch(events)
        with pytest.raises(ValueError, match="truncated"):
            decode_batch(data[:-1])

    def test_unknown_event_tag_raises(self) -> None:
        events = [KeyPress(scancode=0x04)]
        data = bytearray(encode_batch(events))
        data[4] = 0xFF  # corrupt the event type tag
        with pytest.raises(ValueError, match="Unknown event type tag"):
            decode_batch(bytes(data))

    def test_wire_size_efficiency(self) -> None:
        """At 1000Hz mouse + 8ms flush: ~8 mouse moves per packet."""
        events = [MouseMove(dx=i, dy=-i) for i in range(8)]
        data = encode_batch(events)
        # Header(4) + 8 * MouseMove(5) = 44 bytes
        assert len(data) == 44
