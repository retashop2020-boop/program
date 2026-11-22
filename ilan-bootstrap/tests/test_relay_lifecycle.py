
import threading
import time

import pytest
import json
from urllib.request import Request, urlopen

from core.relay_server import RelayHTTPServer

from core.relay_lifecycle import (
    RelayLifecycle,
    RelayLifecycleConfig,
)


class FakeManager:
    def initial_credentials(self):
        return object()


class FakeServer:
    def __init__(
        self,
        *,
        on_shutdown_requested=None,
        fail_start=False,
    ):
        self.ready = threading.Event()
        self.exited = threading.Event()
        self.closed = False
        self.shutdown_calls = 0

        self.on_shutdown_requested = on_shutdown_requested
        self.fail_start = fail_start
        self.server_address = ("127.0.0.1", 12345)

    def serve_forever(self, poll_interval=0.1):
        if self.fail_start:
            raise OSError("Simulated bind failure")

        self.ready.set()
        self.exited.wait(5)

    def wait_until_ready(self, timeout):
        return self.ready.wait(timeout)

    def shutdown(self):
        self.shutdown_calls += 1
        self.exited.set()

    def server_close(self):
        self.closed = True

    def http_shutdown(self):
        self.on_shutdown_requested()


def build_lifecycle(server_refs, *, fail_start=False):
    config = RelayLifecycleConfig(
        bind_host="127.0.0.1",
        port=0,
        startup_timeout_seconds=1,
        shutdown_timeout_seconds=1,
        heartbeat_interval_seconds=1,
        suspect_after_seconds=2,
        recoverable_after_seconds=3,
        lease_timeout_seconds=4,
    )

    def server_factory(**kwargs):
        server = FakeServer(
            on_shutdown_requested=kwargs["on_shutdown_requested"],
            fail_start=fail_start,
        )
        server_refs.append(server)
        return server

    return RelayLifecycle(
        config,
        server_factory=server_factory,
        session_manager_factory=lambda config: FakeManager(),
    )


def test_start_and_manual_stop():
    refs = []
    lifecycle = build_lifecycle(refs)

    lifecycle.start()

    assert lifecycle.state == "RUNNING"

    lifecycle.stop()

    assert refs[0].closed
    assert refs[0].shutdown_calls == 1
    assert lifecycle.state == "STOPPED"


def test_http_shutdown_signals_lifecycle():
    refs = []
    lifecycle = build_lifecycle(refs)

    lifecycle.start()
    refs[0].http_shutdown()

    deadline = time.monotonic() + 2

    while not refs[0].closed and time.monotonic() < deadline:
        time.sleep(0.01)

    assert refs[0].closed
    assert refs[0].shutdown_calls == 1
    assert lifecycle.state == "STOPPED"


def test_server_start_failure():
    refs = []
    lifecycle = build_lifecycle(refs, fail_start=True)

    with pytest.raises(OSError):
        lifecycle.start()

    assert refs[0].closed
    assert lifecycle.state == "FAILED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("heartbeat_interval_seconds", float("nan")),
        ("suspect_after_seconds", float("inf")),
        ("lease_timeout_seconds", 0),
        ("port", 65536),
        ("bind_host", "0.0.0.0"),
        ("bind_host", "::1"),
    ],
)
def test_invalid_config(field, value):
    values = dict(
        bind_host="127.0.0.1",
        port=1234,
        heartbeat_interval_seconds=1,
        suspect_after_seconds=2,
        recoverable_after_seconds=3,
        lease_timeout_seconds=4,
    )
    values[field] = value

    with pytest.raises(ValueError):
        RelayLifecycleConfig(**values).validate()

class IntegrationManager:
    def initial_credentials(self):
        return object()

    def shutdown(self, session_id, owner_token):
        if session_id != "session-test":
            raise RuntimeError("Invalid session")
        if owner_token != "owner-test":
            raise RuntimeError("Invalid owner")


def test_real_relay_server_authenticated_shutdown():
    config = RelayLifecycleConfig(
        bind_host="127.0.0.1",
        port=0,
        startup_timeout_seconds=2,
        shutdown_timeout_seconds=2,
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=1,
        suspect_after_seconds=2,
        recoverable_after_seconds=3,
        lease_timeout_seconds=4,
    )

    server_refs = []
    manager = IntegrationManager()

    def server_factory(**kwargs):
        server = RelayHTTPServer(
            (config.bind_host, config.port),
            kwargs["session_manager"],
            on_shutdown_requested=kwargs["on_shutdown_requested"],
        )
        server_refs.append(server)
        return server

    lifecycle = RelayLifecycle(
        config,
        server_factory=server_factory,
        session_manager_factory=lambda _: manager,
    )

    lifecycle.start()
    server = server_refs[0]

    host, port = lifecycle.server_address
    url = f"http://{host}:{port}/__relay/shutdown"

    payload = json.dumps({
        "session_id": "session-test",
        "owner_token": "owner-test",
    }).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request, timeout=3) as response:
        assert response.status == 200
        body = json.loads(response.read())

    assert body["state"] == "SHUTDOWN"

    deadline = time.monotonic() + 3

    while lifecycle.state != "STOPPED":
        if time.monotonic() >= deadline:
            pytest.fail("Lifecycle did not stop after HTTP shutdown")
        time.sleep(0.01)

    assert server.fileno() == -1
    assert lifecycle.server_address is None
    assert lifecycle.credentials is None

class EnteredButNotReadyServer(FakeServer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.loop_entered = threading.Event()
        self.release_loop = threading.Event()

    def serve_forever(self, poll_interval=0.1):
        self.loop_entered.set()
        self.release_loop.wait(5)
        self.exited.set()

    def wait_until_ready(self, timeout):
        return False

    def shutdown(self):
        self.shutdown_calls += 1
        self.release_loop.set()
        self.exited.set()

def test_startup_timeout_stops_entered_but_not_ready_server():
    config = RelayLifecycleConfig(
        bind_host="127.0.0.1",
        port=0,
        startup_timeout_seconds=0.1,
        shutdown_timeout_seconds=0.1,
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=1,
        suspect_after_seconds=2,
        recoverable_after_seconds=3,
        lease_timeout_seconds=4,
    )

    refs = []

    def server_factory(**kwargs):
        server = EnteredButNotReadyServer(
            on_shutdown_requested=kwargs["on_shutdown_requested"],
        )
        refs.append(server)
        return server

    lifecycle = RelayLifecycle(
        config,
        server_factory=server_factory,
        session_manager_factory=lambda _: FakeManager(),
    )

    with pytest.raises(TimeoutError):
        lifecycle.start()

    server = refs[0]

    try:
        assert server.loop_entered.is_set()

        # These assertions expose the current lifecycle limitation.
        assert server.shutdown_calls == 1
        assert server.closed
        assert not lifecycle._serve_thread.is_alive()

    finally:
        # Prevent a failed diagnostic test from leaving a daemon thread.
        server.release_loop.set()
        lifecycle._serve_thread.join(timeout=1)

        if not server.closed:
            server.server_close()