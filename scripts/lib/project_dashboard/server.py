"""Local HTTP server for the installed harness dashboard."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from lib.project_dashboard.core import (
    DASHBOARD_ACTIONS,
    dashboard_data_to_json,
    load_dashboard_data,
)


ASSET_DIR = Path(__file__).resolve().parent / "assets"
MAX_OUTPUT_CHARS = 24000
COMMAND_TIMEOUT_SECONDS = 60
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MUTATION_LOCK = threading.Lock()


def serve_dashboard(*, root: Path, host: str, port: int) -> None:
    if host not in LOCAL_HOSTS:
        raise SystemExit("Dashboard server refuses non-local bind addresses. Use 127.0.0.1 or localhost.")
    root = root.resolve()
    token = secrets.token_urlsafe(32)

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not self._request_is_local():
                self.send_error(403, "Forbidden")
                return
            route = urlparse(self.path).path
            if route in {"/", "/overview", "/progress", "/actions"}:
                self._send_dashboard_html()
                return
            if route == "/api/dashboard":
                if not self._session_is_valid():
                    self._send_json({"ok": False, "error": "Missing or invalid dashboard session."}, status=403)
                    return
                self._send_json(dashboard_data_to_json(load_dashboard_data(root)))
                return
            if route == "/favicon.ico":
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if route.startswith("/assets/"):
                self._send_asset(route.removeprefix("/assets/"))
                return
            self.send_error(404, "Not found")

        def do_POST(self) -> None:
            if not self._request_is_local():
                self.send_error(403, "Forbidden")
                return
            route = urlparse(self.path).path
            if route != "/api/run":
                self.send_error(404, "Not found")
                return
            try:
                payload = self._read_json_body()
                if not self._session_is_valid():
                    raise ValueError("Missing or invalid dashboard session.")
                action_id = str(payload.get("action", ""))
                confirmed = payload.get("confirmed") is True
                result = run_dashboard_action(root=root, action_id=action_id, confirmed=confirmed)
                self._send_json(result)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} - {format % args}")

        def _read_json_body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > 4096:
                raise ValueError("Request body is too large.")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            loaded = json.loads(raw.decode("utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Request body must be a JSON object.")
            return loaded

        def _send_json(self, payload: dict[str, object], *, status: int = 200) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_dashboard_html(self) -> None:
            path = ASSET_DIR / "dashboard.html"
            text = path.read_text(encoding="utf-8")
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", f"dashboard_session={token}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_asset(self, name: str, content_type: str | None = None) -> None:
            if "/" in name or "\\" in name or name.startswith("."):
                self.send_error(404, "Not found")
                return
            path = ASSET_DIR / name
            if not path.exists() or not path.is_file():
                self.send_error(404, "Not found")
                return
            data = path.read_bytes()
            guessed_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type or guessed_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _request_is_local(self) -> bool:
            host_header = host_without_port(self.headers.get("Host", ""))
            origin = self.headers.get("Origin")
            if host_header and host_header not in LOCAL_HOSTS:
                return False
            if origin:
                origin_host = urlparse(origin).hostname
                if origin_host not in LOCAL_HOSTS:
                    return False
            return self.client_address[0] in LOCAL_HOSTS

        def _session_is_valid(self) -> bool:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookie.get("dashboard_session")
            return morsel is not None and secrets.compare_digest(morsel.value, token)

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard server: http://{host}:{port}/overview")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
    finally:
        server.server_close()


def run_dashboard_action(*, root: Path, action_id: str, confirmed: bool = False) -> dict[str, object]:
    action = next((item for item in DASHBOARD_ACTIONS if item.action_id == action_id), None)
    if action is None:
        raise ValueError(f"Unknown dashboard action: {action_id}")
    if action.confirmation and not confirmed:
        raise ValueError("Action requires explicit confirmation.")
    try:
        with MUTATION_LOCK:
            completed = subprocess.run(
                action.command,
                cwd=root,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=dashboard_env(),
            )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {
            "ok": False,
            "action": action.action_id,
            "label": action.label,
            "command": " ".join(action.command),
            "returncode": None,
            "output": truncate_output(output + "\n[dashboard action timed out]"),
        }
    output = completed.stdout or ""
    return {
        "ok": completed.returncode == 0,
        "action": action.action_id,
        "label": action.label,
        "command": " ".join(action.command),
        "returncode": completed.returncode,
        "output": truncate_output(output),
    }


def dashboard_env() -> dict[str, str]:
    return dict(os.environ)


def truncate_output(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return output[:MAX_OUTPUT_CHARS] + "\n\n[output truncated by dashboard]"


def host_without_port(value: str) -> str:
    if value.startswith("["):
        end = value.find("]")
        if end != -1:
            return value[1:end]
    return value.split(":", 1)[0]
