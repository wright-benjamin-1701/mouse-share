"""Message framing, versioning, and protocol constants.

TCP control channel uses length-prefixed JSON: u32 (LE) length | UTF-8 JSON.
UDP event channel uses the binary codec from event.codec.
"""

from __future__ import annotations

import json
import struct
from enum import StrEnum
from typing import Any

PROTOCOL_VERSION = 1
DEFAULT_UDP_PORT = 24801
DEFAULT_TCP_PORT = 24800

# TCP length prefix: 4-byte unsigned little-endian
_LENGTH_PREFIX = struct.Struct("<I")
MAX_CONTROL_MESSAGE_SIZE = 1024 * 1024  # 1 MiB (clipboard images can be large)


class ControlMessageType(StrEnum):
    """TCP control channel message types."""

    HELLO = "hello"
    SCREEN_CONFIG = "screen_config"
    SWITCH_FOCUS = "switch_focus"
    CLIPBOARD_UPDATE = "clipboard_update"
    PING = "ping"
    PONG = "pong"


def encode_control_message(msg_type: ControlMessageType, payload: dict[str, Any]) -> bytes:
    """Encode a control message as length-prefixed JSON.

    Format: u32_le(length) | UTF-8 JSON bytes
    The JSON always includes a "type" field.
    """
    message = {"type": msg_type.value, **payload}
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return _LENGTH_PREFIX.pack(len(data)) + data


def decode_control_message(data: bytes) -> tuple[ControlMessageType, dict[str, Any]]:
    """Decode a control message from JSON bytes (without the length prefix).

    Returns (message_type, payload_dict).
    Raises ValueError on malformed data.
    """
    try:
        message = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Invalid JSON in control message: {e}") from e

    if not isinstance(message, dict) or "type" not in message:
        raise ValueError("Control message missing 'type' field")

    try:
        msg_type = ControlMessageType(message["type"])
    except ValueError as e:
        raise ValueError(f"Unknown control message type: {message['type']}") from e

    payload = {k: v for k, v in message.items() if k != "type"}
    return msg_type, payload


async def read_length_prefixed(reader: Any) -> bytes:
    """Read a length-prefixed message from an asyncio StreamReader.

    Returns the message bytes (without the length prefix).
    Raises ConnectionError if the connection is closed.
    Raises ValueError if the message exceeds MAX_CONTROL_MESSAGE_SIZE.
    """
    length_data = await reader.readexactly(_LENGTH_PREFIX.size)
    (length,) = _LENGTH_PREFIX.unpack(length_data)

    if length > MAX_CONTROL_MESSAGE_SIZE:
        raise ValueError(f"Control message too large: {length} bytes")

    return await reader.readexactly(length)


async def write_length_prefixed(writer: Any, data: bytes) -> None:
    """Write a length-prefixed message to an asyncio StreamWriter."""
    writer.write(_LENGTH_PREFIX.pack(len(data)) + data)
    await writer.drain()
