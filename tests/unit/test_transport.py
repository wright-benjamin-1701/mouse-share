"""Tests for UDP event batching order."""

from unittest.mock import MagicMock

from mouse_share.event.codec import decode_batch
from mouse_share.event.types import MouseButton, MouseButtonCode, MouseMove
from mouse_share.net.transport import UDPTransport

PRESS = MouseButton(MouseButtonCode.LEFT, pressed=True)
RELEASE = MouseButton(MouseButtonCode.LEFT, pressed=False)


def _sent(events):
    transport = UDPTransport(on_events=lambda _: None)
    sock = MagicMock()
    transport.connection_made(sock)
    transport.set_target("127.0.0.1", 9)
    for event in events:
        transport.queue_event(event)
    transport.flush_now()
    out = []
    for call in sock.sendto.call_args_list:
        out += decode_batch(call.args[0])[2]
    return out


def test_press_drag_release_keeps_order() -> None:
    sent = _sent([
        PRESS, MouseMove(3, 0), MouseMove(4, 1), RELEASE,
    ])
    assert sent == [PRESS, MouseMove(7, 1), RELEASE]


def test_move_then_click_keeps_move_first() -> None:
    sent = _sent([MouseMove(2, 2), PRESS, RELEASE, MouseMove(1, 0)])
    assert sent == [MouseMove(2, 2), PRESS, RELEASE, MouseMove(1, 0)]


def test_consecutive_moves_coalesce() -> None:
    assert _sent([MouseMove(1, 1), MouseMove(2, -1)]) == [MouseMove(3, 0)]
