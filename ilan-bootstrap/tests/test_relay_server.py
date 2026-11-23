import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, build_opener, urlopen

import pytest

import core.relay_server as relay_module
from core.relay_server import RelayHTTPServer


class FakeSnapshot:
    session_id = "session-test"
    state = "ALIVE"
    seconds_since_heartbeat = 0.0


class FakeSessionError(Exception):
    def __init__(self, code):
        super().__init__("private detail must not leak")
        self.code = code


class FakeSessionManager:
    def __init__(self):
        self.state = "ALIVE"
        self.expected_session = "session-test"
        self.expected_owner = "owner-test-secret"

    def _check(self, session_id, owner_token):
        if session_id != self.expected_session:
            raise FakeSessionError("INVALID_SESSION")
        if owner_token != self.expected_owner:
            raise FakeSessionError("INVALID_OWNER_TOKEN")
        if self.state == "SHUTDOWN":
            raise FakeSessionError("SESSION_SHUTDOWN")

    def authenticate(self, session_id, owner_token):
        self._check(session_id, owner_token)

    def heartbeat(self, session_id, owner_token):
        self._check(session_id, owner_token)
        return FakeSnapshot()

    def shutdown(self, session_id, owner_token):
        self._check(session_id, owner_token)
        self.state = "SHUTDOWN"


class FakeOllamaHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body = b'{"model":"test","message":{"role":"assistant","content":"hello"},"done":true}'
    received = None

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        type(self).received = (self.path, self.rfile.read(length))
        self.send_response(type(self).response_status)
        self.send_header("Content-Type", "application/json")
        if type(self).response_status == 302:
            self.send_header("Location", "http://127.0.0.1:9/redirect-target")
        self.send_header("Content-Length", str(len(type(self).response_body)))
        self.end_headers()
        self.wfile.write(type(self).response_body)


@pytest.fixture

def relay_stack(monkeypatch):
    FakeOllamaHandler.response_status = 200
    FakeOllamaHandler.response_body = b'{"model":"test","message":{"role":"assistant","content":"hello"},"done":true}'
    FakeOllamaHandler.received = None
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, args=(0.01,), daemon=True)
    upstream_thread.start()

    real_open = relay_module._open_upstream

    def local_open(request, timeout):
        # Rebuild the Request rather than mutating urllib's request object.
        local_url = request.full_url.replace(
            "http://127.0.0.1:11434",
            "http://127.0.0.1:%d" % upstream.server_address[1],
            1,
        )
        local_request = Request(
            local_url,
            data=request.data,
            headers=dict(request.header_items()),
            method=request.get_method(),
        )
        return build_opener(relay_module._NoRedirect()).open(local_request, timeout=timeout)

    monkeypatch.setattr(relay_module, "_open_upstream", local_open)
    manager = FakeSessionManager()
    shutdown_requested = threading.Event()

    relay = RelayHTTPServer(
        ("127.0.0.1", 0), 
        manager, 
        upstream_timeout=2,
        on_shutdown_requested=shutdown_requested.set,
    )

    # فقط برای دسترسی تست به Event، بدون تغییر قرارداد fixture
    relay._test_shutdown_requested = shutdown_requested
    
    relay_thread = threading.Thread(target=relay.serve_forever, args=(0.01,), daemon=True)
    relay_thread.start()
    try:
        yield relay, manager, upstream
    finally:
        relay.shutdown()
        relay_thread.join(timeout=2)
        relay.close()
        
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=2)


def relay_url(relay, path):
    host, port = relay.server_address
    return "http://%s:%d%s" % (host, port, path)


def send_raw(url, body, headers=None, method="POST"):
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def post_json(url, payload):
    return send_raw(
        url,
        json.dumps(payload).encode("utf-8"),
        {
            "Content-Type": "application/json",
            "X-Relay-Session-ID": "session-test",
            "Authorization": "Bearer owner-test-secret",
        },
    )


def test_chat_forwarded_and_response_preserved(relay_stack):
    relay, _, _ = relay_stack
    payload = {"model": "test", "messages": [{"role": "user", "content": "hello"}], "stream": False}
    status, body = post_json(relay_url(relay, "/api/chat"), payload)
    assert status == 200
    assert body == FakeOllamaHandler.response_body
    assert FakeOllamaHandler.received[0] == "/api/chat"
    assert json.loads(FakeOllamaHandler.received[1]) == payload


def test_chat_rejects_missing_authentication(relay_stack):
    relay, _, _ = relay_stack
    status, body = send_raw(
        relay_url(relay, "/api/chat"),
        json.dumps({"stream": False}).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    assert status == 401
    assert json.loads(body)["error"] == "RELAY_AUTHENTICATION_REQUIRED"
    assert FakeOllamaHandler.received is None


def test_chat_rejects_invalid_owner_token(relay_stack):
    relay, _, _ = relay_stack
    status, body = send_raw(
        relay_url(relay, "/api/chat"),
        json.dumps({"stream": False}).encode("utf-8"),
        {
            "Content-Type": "application/json",
            "X-Relay-Session-ID": "session-test",
            "Authorization": "Bearer wrong-token",
        },
    )
    assert status == 401
    assert json.loads(body)["error"] == "INVALID_OWNER_TOKEN"
    assert FakeOllamaHandler.received is None


def test_streaming_rejected(relay_stack):
    relay, _, _ = relay_stack
    status, body = post_json(relay_url(relay, "/api/chat"), {"stream": True})
    assert status == 400
    assert json.loads(body)["error"] == "STREAMING_NOT_SUPPORTED"


def test_media_type_must_be_exact_json(relay_stack):
    relay, _, _ = relay_stack
    status, body = send_raw(relay_url(relay, "/api/chat"), b'{"stream":false}', {"Content-Type": "text/application/jsonx", "X-Relay-Session-ID": "session-test", "Authorization": "Bearer owner-test-secret"})
    assert status == 415


def test_unknown_path_not_forwarded(relay_stack):
    relay, _, _ = relay_stack
    status, body = post_json(relay_url(relay, "/not-a-route"), {})
    assert status == 404
    assert FakeOllamaHandler.received is None


def test_heartbeat_rejects_wrong_owner(relay_stack):
    relay, _, _ = relay_stack
    status, body = post_json(relay_url(relay, "/__relay/heartbeat"), {"session_id": "session-test", "owner_token": "wrong"})
    assert status == 401
    assert json.loads(body)["error"] == "INVALID_OWNER_TOKEN"


def test_heartbeat_accepts_valid_owner(relay_stack):
    relay, _, _ = relay_stack
    status, body = post_json(relay_url(relay, "/__relay/heartbeat"), {"session_id": "session-test", "owner_token": "owner-test-secret"})
    assert status == 200
    assert json.loads(body)["state"] == "ALIVE"


def test_invalid_session_is_rejected(relay_stack):
    relay, _, _ = relay_stack
    status, body = post_json(relay_url(relay, "/__relay/heartbeat"), {"session_id": "wrong", "owner_token": "owner-test-secret"})
    assert status == 401
    assert json.loads(body)["error"] == "INVALID_SESSION"


def test_malformed_and_non_object_json_rejected(relay_stack):
    relay, _, _ = relay_stack
    status, _ = send_raw(relay_url(relay, "/__relay/heartbeat"), b'{bad', {"Content-Type": "application/json"})
    assert status == 400
    status, _ = send_raw(relay_url(relay, "/__relay/heartbeat"), b'[]', {"Content-Type": "application/json"})
    assert status == 400


def test_shutdown_authenticated_signals_lifecycle(relay_stack):
    relay, manager, _ = relay_stack

    status, body = post_json(
        relay_url(relay, "/__relay/shutdown"), 
        {
            "session_id": "session-test", 
            "owner_token": "owner-test-secret",
        },
    )

    assert status == 200
    assert json.loads(body)["state"] == "SHUTDOWN"
    assert manager.state == "SHUTDOWN"
    assert relay._test_shutdown_requested.wait(1)
    # The lifecycle owner must still call close() to release the listening socket.


def test_shutdown_rejects_wrong_owner(relay_stack):
    relay, manager, _ = relay_stack
    status, _ = post_json(relay_url(relay, "/__relay/shutdown"), {"session_id": "session-test", "owner_token": "wrong"})
    assert status == 401
    assert manager.state == "ALIVE"


def test_get_and_patch_rejected(relay_stack):
    relay, _, _ = relay_stack
    for method in ("GET", "PATCH"):
        status, _ = send_raw(relay_url(relay, "/api/chat"), None, method=method)
        assert status == 405


def test_body_size_limit(relay_stack):
    relay, _, _ = relay_stack
    relay.max_body_bytes = 8
    status, body = post_json(relay_url(relay, "/api/chat"), {"stream": False})
    assert status == 413
    assert json.loads(body)["error"] == "REQUEST_TOO_LARGE"


def test_upstream_http_error_preserved(relay_stack):
    relay, _, _ = relay_stack
    FakeOllamaHandler.response_status = 503
    FakeOllamaHandler.response_body = b'{"error":"model unavailable"}'
    status, body = post_json(relay_url(relay, "/api/chat"), {"stream": False})
    assert status == 503
    assert body == FakeOllamaHandler.response_body


def test_server_rejects_non_fixed_upstream():
    with pytest.raises(ValueError):
        RelayHTTPServer(("127.0.0.1", 0), FakeSessionManager(), upstream_url="http://example.com")


def test_unexpected_session_exception_is_sanitized(relay_stack):
    relay, manager, _ = relay_stack

    def explode(*args):
        raise RuntimeError("owner-test-secret must not leak")

    manager.heartbeat = explode
    status, body = post_json(relay_url(relay, "/__relay/heartbeat"), {"session_id": "session-test", "owner_token": "owner-test-secret"})
    assert status == 500
    assert b"owner-test-secret" not in body
    assert b"must not leak" not in body


def test_incomplete_content_length_rejected(relay_stack):
    # A raw socket is needed to declare more bytes than are sent.
    import socket
    relay, _, _ = relay_stack
    host, port = relay.server_address
    client = socket.create_connection((host, port), timeout=2)
    client.sendall(b"POST /api/chat HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nX-Relay-Session-ID: session-test\r\nAuthorization: Bearer owner-test-secret\r\nContent-Length: 20\r\nConnection: close\r\n\r\n{}")
    client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    response = b"".join(chunks)
    assert b"400" in response
    assert b"INCOMPLETE_REQUEST_BODY" in response


def test_invalid_content_length_rejected(relay_stack):
    import socket
    relay, _, _ = relay_stack
    host, port = relay.server_address
    client = socket.create_connection((host, port), timeout=2)
    client.sendall(b"POST /api/chat HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nX-Relay-Session-ID: session-test\r\nAuthorization: Bearer owner-test-secret\r\nContent-Length: +2\r\nConnection: close\r\n\r\n{}")
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    response = b"".join(chunks)
    assert b"400" in response
    assert b"INVALID_CONTENT_LENGTH" in response


def test_upstream_redirect_is_not_followed(relay_stack):
    relay, _, _ = relay_stack
    FakeOllamaHandler.response_status = 302
    FakeOllamaHandler.response_body = b"redirect"
    status, body = post_json(relay_url(relay, "/api/chat"), {"stream": False})
    assert status == 502
    assert json.loads(body)["error"] == "OLLAMA_REDIRECT_REJECTED"


def test_extremely_long_content_length_is_bounded(relay_stack):
    import socket
    relay, _, _ = relay_stack
    host, port = relay.server_address
    client = socket.create_connection((host, port), timeout=2)
    huge = b"9" * 5000
    client.sendall(
        b"POST /api/chat HTTP/1.1\r\nHost: localhost\r\n"
        b"Content-Type: application/json\r\nX-Relay-Session-ID: session-test\r\nAuthorization: Bearer owner-test-secret\r\nContent-Length: " + huge +
        b"\r\nConnection: close\r\n\r\n"
    )
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    response = b"".join(chunks)
    assert b"413" in response
    assert b"REQUEST_TOO_LARGE" in response


def test_close_releases_listener_socket():
    manager = FakeSessionManager()
    relay = RelayHTTPServer(("127.0.0.1", 0), manager)
    address = relay.server_address
    relay.close()
    # Rebinding the exact address proves server_close released the listener.
    replacement = ThreadingHTTPServer(address, BaseHTTPRequestHandler)
    replacement.server_close()
