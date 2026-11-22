"""Bounded HTTP relay from the WSL AgentLoop to Windows Ollama.

The upstream is deliberately fixed to 127.0.0.1:11434. This module is a
server component only; it does not start or supervise a production Relay.
Compatible with Python 3.10+.
"""

import json
import math
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

UPSTREAM_URL = "http://127.0.0.1:11434"
MAX_UPSTREAM_RESPONSE_BYTES = 64 * 1024 * 1024
INBOUND_SOCKET_TIMEOUT_SECONDS = 30


class _NoRedirect(HTTPRedirectHandler):
    """Do not allow a fixed loopback upstream to redirect elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_upstream(request, timeout):
    opener = build_opener(_NoRedirect())
    return opener.open(request, timeout=timeout)


class RelayHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a fixed Ollama upstream and session manager."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        server_address,
        session_manager,
        *,
        on_shutdown_requested=None,
        upstream_url=UPSTREAM_URL,
        upstream_timeout=2000,
        max_body_bytes=16 * 1024 * 1024,
        max_response_bytes=MAX_UPSTREAM_RESPONSE_BYTES,
    ):
        if upstream_url != UPSTREAM_URL:
            raise ValueError("upstream_url must be exactly the fixed Ollama URL")
        if (
            isinstance(upstream_timeout, bool)
            or not isinstance(upstream_timeout, (int, float))
            or not math.isfinite(upstream_timeout)
            or upstream_timeout <= 0
        ):
            raise ValueError("upstream_timeout must be a finite positive number")
        for name, value in (("max_body_bytes", max_body_bytes), ("max_response_bytes", max_response_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(name + " must be a positive integer")

        self.session_manager = session_manager
        self.upstream_url = UPSTREAM_URL
        self.upstream_timeout = float(upstream_timeout)
        self.max_body_bytes = max_body_bytes
        self.max_response_bytes = max_response_bytes
        self._ready = threading.Event()
        self._on_shutdown_requested = on_shutdown_requested
        super().__init__(server_address, self._make_handler())

    def service_actions(self):
        self._ready.set()
        return super().service_actions()

    def wait_until_ready(self, timeout):
        return self._ready.wait(timeout)

    def close(self):
        """Release the listening socket after the serving thread has exited."""
        self.server_close()

    def _make_handler(self):
        server = self


        class RelayHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "IlanRelay"
            sys_version = ""

            def setup(self):
                super().setup()
                self.connection.settimeout(INBOUND_SOCKET_TIMEOUT_SECONDS)

            def log_message(self, format_string, *args):
                # Never log paths, headers, or session credentials.
                return

            def handle_expect_100(self):
                self._json(417, {"error": "EXPECT_CONTINUE_NOT_SUPPORTED"})
                return False

            def _send(self, status, body, content_type="application/json"):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if body:
                    try:
                        self.wfile.write(body)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                self.close_connection = True

            def _json(self, status, payload):
                self._send(status, json.dumps(payload, ensure_ascii=False))

            def _read_body(self):
                # Reject ambiguous framing and anything except strict decimal digits.
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1:
                    self._json(411 if not lengths else 400, {
                        "error": "CONTENT_LENGTH_REQUIRED" if not lengths else "AMBIGUOUS_CONTENT_LENGTH"
                    })
                    return None
                if self.headers.get_all("Transfer-Encoding"):
                    self._json(400, {"error": "TRANSFER_ENCODING_NOT_SUPPORTED"})
                    return None
                raw_length = lengths[0]
                if not raw_length or not raw_length.isascii() or not raw_length.isdecimal():
                    self._json(400, {"error": "INVALID_CONTENT_LENGTH"})
                    return None
                # Bound conversion cost and avoid Python's huge-integer digit limit.
                max_digits = len(str(server.max_body_bytes))
                if len(raw_length) > max_digits:
                    self._json(413, {"error": "REQUEST_TOO_LARGE"})
                    return None
                length = int(raw_length)
                if length > server.max_body_bytes:
                    self._json(413, {"error": "REQUEST_TOO_LARGE"})
                    return None
                try:
                    body = self.rfile.read(length)
                except (OSError, socket.timeout):
                    self._json(400, {"error": "REQUEST_BODY_READ_FAILED"})
                    return None
                if len(body) != length:
                    self._json(400, {"error": "INCOMPLETE_REQUEST_BODY"})
                    return None
                return body

            def _parse_json_object(self):
                raw = self._read_body()
                if raw is None:
                    return None
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"error": "INVALID_JSON"})
                    return None
                if not isinstance(payload, dict):
                    self._json(400, {"error": "JSON_OBJECT_REQUIRED"})
                    return None
                return payload

            def do_POST(self):
                if self.path == "/api/chat":
                    self._proxy_chat()
                elif self.path == "/__relay/heartbeat":
                    self._heartbeat()
                elif self.path == "/__relay/shutdown":
                    self._shutdown()
                else:
                    self._json(404, {"error": "NOT_FOUND"})

            def _method_not_allowed(self):
                self._json(405, {"error": "METHOD_NOT_ALLOWED"})

            do_GET = _method_not_allowed
            do_HEAD = _method_not_allowed
            do_PUT = _method_not_allowed
            do_DELETE = _method_not_allowed
            do_PATCH = _method_not_allowed
            do_OPTIONS = _method_not_allowed

            def _control_credentials(self):
                payload = self._parse_json_object()
                if payload is None:
                    return None
                session_id = payload.get("session_id")
                owner_token = payload.get("owner_token")
                if not isinstance(session_id, str) or not isinstance(owner_token, str):
                    self._json(400, {"error": "SESSION_CREDENTIALS_REQUIRED"})
                    return None
                if not session_id or not owner_token:
                    self._json(400, {"error": "SESSION_CREDENTIALS_REQUIRED"})
                    return None
                return session_id, owner_token

            def _session_error(self, exc):
                # Expected session errors carry a stable .code. Unexpected errors
                # are contained and sanitized; exception text/secrets are not sent.
                code = getattr(exc, "code", None)
                status = {
                    "INVALID_SESSION": 401,
                    "INVALID_OWNER_TOKEN": 401,
                    "LEASE_NOT_ACTIVE": 409,
                    "SESSION_SHUTDOWN": 409,
                }.get(code)
                if status is None:
                    self._json(500, {"error": "INTERNAL_SESSION_ERROR"})
                else:
                    self._json(status, {"error": code})

            def _heartbeat(self):
                credentials = self._control_credentials()
                if credentials is None:
                    return
                try:
                    snapshot = server.session_manager.heartbeat(*credentials)
                except Exception as exc:
                    self._session_error(exc)
                    return
                state = getattr(snapshot.state, "value", snapshot.state)
                self._json(200, {
                    "ok": True,
                    "session_id": snapshot.session_id,
                    "state": state,
                    "seconds_since_heartbeat": snapshot.seconds_since_heartbeat,
                })

            def _shutdown(self):
                credentials = self._control_credentials()
                if credentials is None:
                    return
                try:
                    server.session_manager.shutdown(*credentials)
                except Exception as exc:
                    self._session_error(exc)
                    return

                self._json(200, {"ok": True, "state": "SHUTDOWN"})

                callback = server._on_shutdown_requested
                if callback is not None:
                    callback()

            def _proxy_chat(self):
                content_types = self.headers.get_all("Content-Type", [])
                if len(content_types) != 1:
                    self._json(415, {"error": "APPLICATION_JSON_REQUIRED"})
                    return
                media_type = content_types[0].split(";", 1)[0].strip().lower()
                if media_type != "application/json":
                    self._json(415, {"error": "APPLICATION_JSON_REQUIRED"})
                    return

                payload = self._parse_json_object()
                if payload is None:
                    return
                if payload.get("stream") is not False:
                    self._json(400, {"error": "STREAMING_NOT_SUPPORTED"})
                    return

                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                request = Request(
                    server.upstream_url + "/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with _open_upstream(request, server.upstream_timeout) as response:
                        status = response.status
                        response_type = response.headers.get("Content-Type", "application/json")
                        response_body = response.read(server.max_response_bytes + 1)
                except HTTPError as exc:
                    # A redirect is intentionally not followed. Preserve its status.
                    if 300 <= exc.code < 400:
                        self._json(502, {"error": "OLLAMA_REDIRECT_REJECTED"})
                        return
                    response_type = exc.headers.get("Content-Type", "application/json")
                    response_body = exc.read(server.max_response_bytes + 1)
                    status = exc.code
                except (URLError, TimeoutError, OSError, socket.timeout):
                    self._json(502, {"error": "OLLAMA_UPSTREAM_UNAVAILABLE"})
                    return
                if len(response_body) > server.max_response_bytes:
                    self._json(502, {"error": "OLLAMA_RESPONSE_TOO_LARGE"})
                    return
                self._send(status, response_body, response_type)

        return RelayHandler
