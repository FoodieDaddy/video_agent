"""Desktop launcher for the Windows one-click installation.

``start-studio.cmd`` runs ``python -m app.desktop``: it serves the API with
uvicorn, waits until ``/health`` answers and then opens the console in the
default browser.  Ctrl+C in the console window stops the studio.
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # On Windows SO_REUSEADDR also lets us bind a port that is already in use,
        # so ask for exclusive use there.  POSIX needs REUSEADDR to ignore TIME_WAIT.
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _open_browser_when_ready(url: str, health_url: str, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:  # noqa: S310
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    # Server slow or failed: still show the URL so the user can retry manually.
    print(f"Console not reachable yet - open {url} once the server is up.", flush=True)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="app.desktop",
        description="Run the AI Film Studio API and open the console.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8010, help="preferred port (default 8010)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--log-level", default="info", help="uvicorn log level (default info)")
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not _port_available(args.host, args.port):
        raise SystemExit(f"端口 {args.port} 已被占用，请使用现有实例或先停止该实例")
    port = args.port
    url = f"http://{args.host}:{port}/"
    health = f"{url}health"

    from studio_platform.configuration.settings import load_settings

    settings = load_settings()
    print("=" * 66, flush=True)
    print(f" {settings.app_name}", flush=True)
    print(f" console   : {url}", flush=True)
    print(f" env       : {settings.env}", flush=True)
    print(f" data      : {settings.data_dir}", flush=True)
    print(f" ffmpeg    : {settings.ffmpeg_bin}", flush=True)
    print(" close this window or press Ctrl+C to stop the studio", flush=True)
    print("=" * 66, flush=True)

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(url, health),
            daemon=True,
        ).start()

    import uvicorn

    try:
        uvicorn.run(
            "studio_api.main:app",
            host=args.host,
            port=port,
            log_level=args.log_level,
            workers=1,
            reload=False,
        )
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
