"""Start the local workbench and open it only after the web page is ready."""

import argparse
import json
import socket
import threading
import time
import webbrowser
from contextlib import closing
from http.client import HTTPConnection, HTTPException
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
TITLE = "桥安智析 · 桥梁监测 AI 分析工作台".encode()


def platform_ready(port):
    try:
        with closing(HTTPConnection(HOST, port, timeout=1)) as connection:
            connection.request("GET", "/")
            response = connection.getresponse()
            if response.status != 200 or TITLE not in response.read(16_384):
                return False
        with closing(HTTPConnection(HOST, port, timeout=1)) as connection:
            connection.request("GET", "/api/v2/health")
            response = connection.getresponse()
            if response.status != 200:
                return False
            data = json.loads(response.read(4096))
            return (
                isinstance(data, dict)
                and data.get("service") == "bridge-insight"
                and data.get("api_version") == 2
                and data.get("workspace_drafts") is True
                and data.get("record_deletion") is True
                and data.get("observation_intervals") is True
                and data.get("chat_observation_intervals") is True
            )
    except (OSError, HTTPException, ValueError):
        return False


def port_in_use(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex((HOST, port)) == 0


def wait_for_platform(port, timeout, stopped=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stopped is not None and stopped.is_set():
            return False
        if platform_ready(port):
            return True
        if stopped is None:
            time.sleep(0.2)
        elif stopped.wait(0.2):
            return False
    return False


def open_platform(url, no_browser):
    print(f"Platform ready: {url}", flush=True)
    if no_browser:
        return
    try:
        if webbrowser.open(url, new=2):
            print("Opened in your default browser.", flush=True)
            return
    except (OSError, webbrowser.Error):
        pass
    print(
        f"Browser did not open. Paste this address into your browser: {url}", flush=True
    )


def launch(port, no_browser):
    url = f"http://{HOST}:{port}/"
    if platform_ready(port) or (port_in_use(port) and wait_for_platform(port, 3)):
        print("Bridge Insight is already running.")
        open_platform(url, no_browser)
        return 0

    if port_in_use(port):
        print(
            f"Port {port} is occupied and does not serve the current Bridge Insight API."
        )
        print("Close the previous platform window, then relaunch.")
        print("If the port belongs to another app, run scripts\\start.ps1 -Port 8001.")
        return 1

    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("The web interface is not built. Run the dependency installer first.")
        return 1

    try:
        import uvicorn
    except ImportError:
        print("Python dependencies are missing. Run the dependency installer first.")
        return 1

    stopped = threading.Event()

    def announce_ready():
        if wait_for_platform(port, 45, stopped):
            open_platform(url, no_browser)
        elif not stopped.is_set():
            print(
                f"The page has not responded yet. Check the messages above and try {url}",
                flush=True,
            )

    print(f"Starting Bridge Insight at {url}", flush=True)
    print(
        "Keep this window open while using the platform. Press Ctrl+C to stop it.",
        flush=True,
    )
    server = uvicorn.Server(uvicorn.Config("backend.main:app", host=HOST, port=port))
    watcher = threading.Thread(target=announce_ready, daemon=True)
    watcher.start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        watcher.join(timeout=2)
    return 0 if server.started else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    raise SystemExit(launch(args.port, args.no_browser))
