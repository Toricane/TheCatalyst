"""Application entrypoint to run backend API and local frontend server."""

from __future__ import annotations

import contextlib
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

from backend.app import app

__all__ = ["app"]


BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000
FRONTEND_PORT = 3000
FRONTEND_PATH = "/frontend/"
PROJECT_ROOT = Path(__file__).resolve().parent


def _start_frontend_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    class CatalystRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

        def handle(self) -> None:  # pragma: no cover - integration behaviour
            try:
                super().handle()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass

        def send_head(self):  # TODO: Remove when adding real favicon
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return None
            return super().send_head()

    httpd = ThreadingHTTPServer(("127.0.0.1", FRONTEND_PORT), CatalystRequestHandler)
    httpd.daemon_threads = True

    server_thread = threading.Thread(
        target=httpd.serve_forever,
        name="frontend-http-server",
        daemon=True,
    )
    server_thread.start()
    return httpd, server_thread


def _open_frontend_when_backend_ready(stop_event: threading.Event) -> None:
    backend_probe_url = f"http://127.0.0.1:{BACKEND_PORT}/"
    while not stop_event.is_set():
        try:
            with urllib.request.urlopen(backend_probe_url, timeout=1):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    else:
        return

    if stop_event.is_set():
        return

    frontend_url = f"http://localhost:{FRONTEND_PORT}{FRONTEND_PATH}"
    print(f"🌐 Opening browser to {frontend_url}")
    webbrowser.open(frontend_url)


def main() -> None:
    frontend_server: ThreadingHTTPServer | None = None
    frontend_thread: threading.Thread | None = None
    backend_ready_thread: threading.Thread | None = None
    stop_event = threading.Event()
    try:
        print(
            f"🚀 Starting frontend server at http://localhost:{FRONTEND_PORT}{FRONTEND_PATH}"
        )
        frontend_server, frontend_thread = _start_frontend_server()

        # Give the frontend server a moment to begin accepting connections
        time.sleep(1)

        print(f"⚙️  Starting backend API at http://localhost:{BACKEND_PORT}")
        backend_ready_thread = threading.Thread(
            target=_open_frontend_when_backend_ready,
            args=(stop_event,),
            name="backend-ready-watcher",
            daemon=True,
        )
        backend_ready_thread.start()
        uvicorn.run(
            "backend.app:app",
            host=BACKEND_HOST,
            port=BACKEND_PORT,
            reload=True,
        )
    except KeyboardInterrupt:
        print("\n🛑 Shutdown requested by user.")
    finally:
        stop_event.set()
        if backend_ready_thread is not None:
            backend_ready_thread.join(timeout=2)
        if frontend_server is not None:
            print("🧹 Stopping frontend server...")
            with contextlib.suppress(Exception):
                frontend_server.shutdown()
                frontend_server.server_close()
        if frontend_thread is not None:
            frontend_thread.join(timeout=2)
        print("✨ All services stopped.")


if __name__ == "__main__":
    main()
