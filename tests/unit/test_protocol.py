"""Tests for TCP control protocol framing and serialization."""

import asyncio
import json
import struct

import pytest

from mouse_share.net.protocol import (
    MAX_CONTROL_MESSAGE_SIZE,
    PROTOCOL_VERSION,
    ControlMessageType,
    decode_control_message,
    encode_control_message,
    read_length_prefixed,
    write_length_prefixed,
)


class TestControlMessageEncoding:
    def test_hello_round_trip(self) -> None:
        payload = {
            "version": PROTOCOL_VERSION,
            "hostname": "test-host",
            "screen": {"width": 1920, "height": 1080},
        }
        encoded = encode_control_message(ControlMessageType.HELLO, payload)

        # Verify length prefix
        length = struct.unpack("<I", encoded[:4])[0]
        assert length == len(encoded) - 4

        # Decode the JSON part
        msg_type, decoded_payload = decode_control_message(encoded[4:])
        assert msg_type == ControlMessageType.HELLO
        assert decoded_payload["version"] == PROTOCOL_VERSION
        assert decoded_payload["hostname"] == "test-host"
        assert decoded_payload["screen"]["width"] == 1920

    def test_ping_pong(self) -> None:
        encoded = encode_control_message(ControlMessageType.PING, {"timestamp": 12345.678})
        msg_type, payload = decode_control_message(encoded[4:])
        assert msg_type == ControlMessageType.PING
        assert payload["timestamp"] == 12345.678

    def test_switch_focus(self) -> None:
        payload = {"target": "macbook", "entry_x": 0, "entry_y": 540}
        encoded = encode_control_message(ControlMessageType.SWITCH_FOCUS, payload)
        msg_type, decoded = decode_control_message(encoded[4:])
        assert msg_type == ControlMessageType.SWITCH_FOCUS
        assert decoded["target"] == "macbook"
        assert decoded["entry_x"] == 0

    def test_clipboard_update(self) -> None:
        payload = {"content": "Hello, world!", "content_type": "text/plain"}
        encoded = encode_control_message(ControlMessageType.CLIPBOARD_UPDATE, payload)
        msg_type, decoded = decode_control_message(encoded[4:])
        assert msg_type == ControlMessageType.CLIPBOARD_UPDATE
        assert decoded["content"] == "Hello, world!"

    def test_all_message_types(self) -> None:
        for msg_type in ControlMessageType:
            encoded = encode_control_message(msg_type, {"test": True})
            decoded_type, _ = decode_control_message(encoded[4:])
            assert decoded_type == msg_type

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            decode_control_message(b"not json")

    def test_missing_type_field_raises(self) -> None:
        with pytest.raises(ValueError, match="missing 'type'"):
            decode_control_message(json.dumps({"foo": "bar"}).encode())

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown control message type"):
            decode_control_message(json.dumps({"type": "nonexistent"}).encode())

    def test_compact_json(self) -> None:
        """Verify JSON uses compact separators (no whitespace)."""
        encoded = encode_control_message(ControlMessageType.PING, {"a": 1})
        json_part = encoded[4:]
        assert b" " not in json_part


class TestLengthPrefixedIO:
    @pytest.mark.asyncio
    async def test_read_write_round_trip(self) -> None:
        """Test read/write through an in-memory stream pair."""
        reader = asyncio.StreamReader()
        # Create a mock writer using a transport
        transport = _MockTransport()
        protocol = asyncio.StreamReaderProtocol(reader)
        writer = asyncio.StreamWriter(transport, protocol, reader, asyncio.get_event_loop())

        message = b'{"type":"ping","timestamp":1.0}'
        await write_length_prefixed(writer, message)

        # Feed the written data back to the reader
        reader.feed_data(transport.written)
        reader.feed_eof()

        result = await read_length_prefixed(reader)
        assert result == message

    @pytest.mark.asyncio
    async def test_oversized_message_raises(self) -> None:
        reader = asyncio.StreamReader()
        # Feed a length prefix claiming a huge message
        reader.feed_data(struct.pack("<I", MAX_CONTROL_MESSAGE_SIZE + 1))
        reader.feed_eof()

        with pytest.raises(ValueError, match="too large"):
            await read_length_prefixed(reader)


class _MockTransport(asyncio.Transport):
    """Minimal transport that captures written bytes."""

    def __init__(self) -> None:
        super().__init__()
        self.written = b""

    def write(self, data: bytes) -> None:
        self.written += data

    def close(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False

    def can_write_eof(self) -> bool:
        return False

    def get_extra_info(self, name: str, default: object = None) -> object:
        return default
