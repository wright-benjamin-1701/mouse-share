"""Entry point for mouse-share."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import logging
import platform
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from mouse_share.app import App
from mouse_share.config import load_config
from mouse_share.net.protocol import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT
from mouse_share.platform import create_capture_backend, create_emulate_backend

if TYPE_CHECKING:
    from collections.abc import Callable

    from mouse_share.clipboard.base import ClipboardBackend


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mouse-share",
        description="Share keyboard and mouse across machines on a LAN.",
    )
    parser.add_argument(
        "--connect",
        metavar="HOST",
        help="Connect to a peer at HOST on startup",
    )
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=None,
        help=f"TCP control port (default: {DEFAULT_TCP_PORT})",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=None,
        help=f"UDP event port (default: {DEFAULT_UDP_PORT})",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to config file (default: platform-appropriate location)",
    )
    parser.add_argument(
        "--no-detect",
        action="store_true",
        help="Skip auto-detection and use config defaults for screen size",
    )
    parser.add_argument(
        "--peer-id",
        default=None,
        help="Local peer identifier (default: hostname)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the screen arrangement window alongside the app",
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Don't share copied text with peers",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Load config, then override with CLI args
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    config = dataclasses.replace(
        config,
        local_peer_id=args.peer_id or config.local_peer_id or platform.node(),
        tcp_port=args.tcp_port or config.tcp_port,
        udp_port=args.udp_port or config.udp_port,
    )

    try:
        capture = create_capture_backend()
        emulate = create_emulate_backend()
    except RuntimeError as e:
        logging.error("%s", e)
        return 1

    def make_app(clipboard: ClipboardBackend | None = None) -> App:
        return App(
            config=config,
            capture=capture,
            emulate=emulate,
            no_detect=args.no_detect,
            config_path=config_path,
            clipboard=clipboard,
        )

    # The clipboard and the window both need Qt, which must own the main thread
    if args.gui or not args.no_clipboard:
        return _run_under_qt(make_app, args.connect, gui=args.gui, clipboard=not args.no_clipboard)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(make_app().run(connect_host=args.connect))

    return 0


def _run_under_qt(
    make_app: Callable[[ClipboardBackend | None], App],
    connect_host: str | None,
    *,
    gui: bool,
    clipboard: bool,
) -> int:
    """Run Qt on the main thread and the app's event loop on a worker thread."""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    qt_app = QApplication(sys.argv) if gui else QGuiApplication(sys.argv)

    backend = None
    if clipboard:
        from mouse_share.clipboard.qt import QtClipboard

        backend = QtClipboard()
    app = make_app(backend)

    window = None
    if gui:
        from mouse_share.gui.arrange import ArrangeWindow

        window = ArrangeWindow(app, on_close=app.request_stop)
        window.show()

    def run_app() -> None:
        try:
            asyncio.run(app.run(connect_host=connect_host))
        except asyncio.CancelledError:
            pass  # stopped while still connecting
        except Exception:
            logging.exception("App stopped with an error")
        finally:
            qt_app.quit()  # quit() is thread-safe: it posts to the Qt loop

    # Daemon, so a stop requested before the loop is up can't hang the exit
    worker = threading.Thread(target=run_app, name="mouse-share-app", daemon=True)
    worker.start()

    # Let Ctrl+C reach Python: Qt's loop otherwise never returns to it
    signal.signal(signal.SIGINT, lambda *_: qt_app.quit())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)

    qt_app.exec()
    app.request_stop()
    worker.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
