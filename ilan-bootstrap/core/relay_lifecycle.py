
"""Lifecycle coordinator for the Windows Relay server."""

from __future__ import annotations

from dataclasses import dataclass
import time
import ipaddress
import math
import threading
from typing import Callable, Optional


@dataclass(frozen=True)
class RelayLifecycleConfig:
    bind_host: str
    port: int
    startup_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    poll_interval_seconds: float = 0.1
    heartbeat_interval_seconds: float = 5.0
    suspect_after_seconds: float = 15.0
    recoverable_after_seconds: float = 30.0
    lease_timeout_seconds: float = 60.0

    def validate(self) -> None:
        try:
            address = ipaddress.ip_address(self.bind_host)
        except ValueError as exc:
            raise ValueError(
                "bind_host must be a literal IPv4 address"
            ) from exc

        if not isinstance(address, ipaddress.IPv4Address):
            raise ValueError("bind_host must be IPv4")

        if address.is_unspecified or address.is_multicast:
            raise ValueError("bind_host must be a specific unicast IPv4")

        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port must be an integer")

        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")

        positive_fields = (
            "startup_timeout_seconds",
            "shutdown_timeout_seconds",
            "poll_interval_seconds",
            "heartbeat_interval_seconds",
            "suspect_after_seconds",
            "recoverable_after_seconds",
            "lease_timeout_seconds",
        )

        for name in positive_fields:
            value = getattr(self, name)

            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite positive number")

            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")

        if not (
            self.heartbeat_interval_seconds
            < self.suspect_after_seconds
            < self.recoverable_after_seconds
            < self.lease_timeout_seconds
        ):
            raise ValueError(
                "Required timing order: heartbeat < suspect "
                "< recoverable < lease"
            )


class RelayLifecycle:
    """
    Owns server startup, shutdown coordination, and socket cleanup.

    Server adapter contract:
      - serve_forever(poll_interval=...)
      - wait_until_ready(timeout) -> bool
      - shutdown()
      - server_close()
      - server_address

    Only the lifecycle coordinator may call server.shutdown().
    """

    def __init__(
        self,
        config: RelayLifecycleConfig,
        *,
        server_factory: Callable,
        session_manager_factory: Callable,
        credentials_factory: Optional[Callable] = None,
    ):
        config.validate()

        self.config = config
        self._server_factory = server_factory
        self._session_manager_factory = session_manager_factory
        self._credentials_factory = credentials_factory

        self._state_lock = threading.RLock()
        self._operation_lock = threading.Lock()

        self._state = "STOPPED"
        self._server = None
        self._serve_thread = None
        self._coordinator_thread = None

        self._shutdown_requested = threading.Event()
        self._serve_exited = threading.Event()
        self._closed = threading.Event()

        self._credentials = None
        self._startup_error = None
        self._serve_started = False

    @property
    def state(self):
        with self._state_lock:
            return self._state

    @property
    def credentials(self):
        with self._state_lock:
            return self._credentials

    @property
    def startup_error(self):
        with self._state_lock:
            return self._startup_error

    @property
    def server_address(self):
        with self._state_lock:
            if self._server is None:
                return None
            return self._server.server_address

    def start(self):
        with self._operation_lock:
            with self._state_lock:
                if self._state != "STOPPED":
                    raise RuntimeError(
                        f"Cannot start in state {self._state}"
                    )

                self._state = "STARTING"
                self._shutdown_requested.clear()
                self._serve_exited.clear()
                self._closed.clear()
                self._credentials = None
                self._startup_error = None
                self._serve_started = False
                self._serve_thread = None
                self._coordinator_thread = None
                self._server = None

            server = None

            try:
                manager = self._session_manager_factory(self.config)

                server = self._server_factory(
                    config=self.config,
                    session_manager=manager,
                    on_shutdown_requested=self.request_stop,
                )

                # Keep ownership immediately, so later failures can clean up.
                with self._state_lock:
                    self._server = server

                # Coordinator must exist before the serving thread starts.
                self._coordinator_thread = threading.Thread(
                    target=self._coordinate_shutdown,
                    name="ilan-relay-shutdown-coordinator",
                    daemon=True,
                )
                self._coordinator_thread.start()

                if self._credentials_factory is not None:
                    credentials = self._credentials_factory(manager)
                else:
                    credentials = manager.initial_credentials()

                with self._state_lock:
                    self._credentials = credentials

                self._serve_thread = threading.Thread(
                    target=self._serve,
                    name="ilan-relay-serve",
                    daemon=True,
                )

                self._serve_thread.start()
                self._serve_started = True

                deadline = time.monotonic() + (
                    self.config.startup_timeout_seconds
                )

                while True:
                    if self._serve_exited.is_set():
                        error = self.startup_error
                        if error is not None:
                            raise error
                        raise RuntimeError(
                            "Relay server exited during startup"
                        )

                    if self._shutdown_requested.is_set():
                        raise RuntimeError(
                            "Relay shutdown requested during startup"
                        )

                    remaining = deadline - time.monotonic()

                    if remaining <= 0:
                        raise TimeoutError(
                            "Relay server startup timed out"
                        )


                    if server.wait_until_ready(
                        min(
                            self.config.poll_interval_seconds,
                            remaining,
                        )
                    ):
                        break

                with self._state_lock:
                    if self._state != "STARTING":
                        raise RuntimeError(
                            "Relay stopped while startup was in progress"
                        )

                    self._state = "RUNNING"

                return credentials

            except BaseException as exc:
                with self._state_lock:
                    if self._startup_error is None:
                        self._startup_error = exc
                    self._state = "FAILED"

                self._shutdown_requested.set()

                coordinator = self._coordinator_thread

                if coordinator is not None:
                    coordinator.join(
                        self.config.startup_timeout_seconds
                        + self.config.shutdown_timeout_seconds
                        + 1
                    )

                    if coordinator.is_alive():
                        raise RuntimeError(
                            "Startup failed, but shutdown coordinator "
                            "did not finish"
                        ) from exc

                elif server is not None:
                    # Coordinator could not be started.
                    # No serving thread should have been started yet.
                    if self._serve_thread is None or not self._serve_thread.is_alive():
                        self._close_server()

                raise

    def request_stop(self):
        """Non-blocking stop request. Safe to call from an HTTP handler."""
        with self._state_lock:
            if self._state in ("STOPPED", "FAILED"):
                return

            if self._state != "STOPPING":
                self._state = "STOPPING"

            self._shutdown_requested.set()

    def stop(self):
        with self._operation_lock:
            self.request_stop()

            coordinator = self._coordinator_thread

            if coordinator is not None:
                if coordinator is not threading.current_thread():
                    coordinator.join(
                        self.config.startup_timeout_seconds
                        + self.config.shutdown_timeout_seconds
                        + 1
                    )

                    if coordinator.is_alive():
                        raise TimeoutError(
                            "Relay shutdown coordinator did not finish"
                        )

            elif self._serve_thread is not None:
                if self._serve_thread.is_alive():
                    raise RuntimeError(
                        "Serving thread exists without a shutdown coordinator"
                    )

                self._close_server()

            with self._state_lock:
                if self._state != "FAILED":
                    self._state = "STOPPED"

    def _serve(self):
        try:
            self._server.serve_forever(
                poll_interval=self.config.poll_interval_seconds
            )

        except BaseException as exc:
            with self._state_lock:
                if self._startup_error is None:
                    self._startup_error = exc

                if self._state not in (
                    "STOPPING",
                    "STOPPED",
                    "FAILED",
                ):
                    self._state = "FAILED"

            self._shutdown_requested.set()

        finally:
            self._serve_exited.set()

    def _coordinate_shutdown(self):
        self._shutdown_requested.wait()

        with self._state_lock:
            server = self._server
            thread = self._serve_thread

        if server is None:
            return

        if thread is not None:
            if thread.is_alive():
                # shutdown() must be safe even if serve_forever
                # has not reached its readiness signal yet.
                try:
                    server.shutdown()
                except BaseException as exc:
                    with self._state_lock:
                        if self._startup_error is None:
                            self._startup_error = exc
                        self._state = "FAILED"

            thread.join(
                self.config.shutdown_timeout_seconds
            )

            if thread.is_alive():
                with self._state_lock:
                    self._state = "FAILED"
                return

        self._close_server()

        with self._state_lock:
            if self._state != "FAILED":
                self._state = "STOPPED"

    def _close_server(self):
        with self._state_lock:
            server = self._server

            if server is None or self._closed.is_set():
                return

            self._closed.set()

        try:
            server.server_close()

        finally:
            with self._state_lock:
                self._server = None
                self._credentials = None
