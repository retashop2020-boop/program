"""In-memory session and lease state for the Windows Ollama relay.

This module deliberately contains no HTTP server, filesystem persistence, or
process management. It is compatible with Python 3.10+.
"""

from dataclasses import dataclass
from enum import Enum
import hmac
import math
import secrets
import threading
import time
from typing import Callable, Optional


class RelaySessionError(RuntimeError):
    """A rejected session operation with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class RelaySessionState(str, Enum):
    ALIVE = "ALIVE"
    SUSPECT = "SUSPECT"
    RECOVERABLE = "RECOVERABLE"
    EXPIRED = "EXPIRED"
    SHUTDOWN = "SHUTDOWN"


@dataclass(frozen=True, repr=False)
class RelayCredentials:
    """Secrets returned once to the owner; repr intentionally hides them."""

    session_id: str
    owner_token: str
    recovery_token: str


@dataclass(frozen=True)
class RelaySessionSnapshot:
    session_id: str
    state: RelaySessionState
    seconds_since_heartbeat: float


class RelaySessionManager:
    """Thread-safe in-memory Lease state and atomic owner reattachment.

    Timing values are deliberately required from the caller. The project has
    not yet selected production heartbeat/deadline values.
    """

    def __init__(
        self,
        *,
        suspect_after_seconds: float,
        recoverable_after_seconds: float,
        lease_timeout_seconds: float,
        clock: Optional[Callable[[], float]] = None,
        token_bytes: int = 32,
    ):
        timings = (
            suspect_after_seconds,
            recoverable_after_seconds,
            lease_timeout_seconds,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in timings
        ):
            raise ValueError("Lease timing values must be finite positive numbers")
        if not (
            suspect_after_seconds
            < recoverable_after_seconds
            < lease_timeout_seconds
        ):
            raise ValueError(
                "timings must satisfy suspect_after < recoverable_after < lease_timeout"
            )
        if isinstance(token_bytes, bool) or not isinstance(token_bytes, int) or token_bytes < 16:
            raise ValueError("token_bytes must be an integer of at least 16")

        self._suspect_after = float(suspect_after_seconds)
        self._recoverable_after = float(recoverable_after_seconds)
        self._lease_timeout = float(lease_timeout_seconds)
        self._clock = clock or time.monotonic
        self._token_bytes = token_bytes
        self._lock = threading.RLock()

        self._session_id = secrets.token_urlsafe(18)
        self._owner_token = self._new_token()
        self._recovery_token = self._new_token()
        self._last_heartbeat = self._clock()
        self._closed = False

    def initial_credentials(self) -> RelayCredentials:
        """Return the initial credentials for the process that created this manager."""
        with self._lock:
            if self._closed:
                raise RelaySessionError("SESSION_SHUTDOWN", "Session is shut down")
            return RelayCredentials(
                self._session_id, self._owner_token, self._recovery_token
            )

    def snapshot(self) -> RelaySessionSnapshot:
        with self._lock:
            state, elapsed = self._current_state()
            return RelaySessionSnapshot(self._session_id, state, elapsed)

    def authenticate(self, session_id: str, owner_token: str) -> None:
        """Validate the current owner without refreshing the heartbeat lease."""
        with self._lock:
            state, _ = self._current_state()
            self._check_session(session_id)
            self._check_owner(owner_token)
            if state in (RelaySessionState.EXPIRED, RelaySessionState.SHUTDOWN):
                raise RelaySessionError("LEASE_NOT_ACTIVE", "Lease is no longer active")

    def heartbeat(self, session_id: str, owner_token: str) -> RelaySessionSnapshot:
        """Accept a valid one-way heartbeat and refresh the Lease."""
        with self._lock:
            state, _ = self._current_state()
            self._check_session(session_id)
            self._check_owner(owner_token)
            if state in (RelaySessionState.EXPIRED, RelaySessionState.SHUTDOWN):
                raise RelaySessionError("LEASE_NOT_ACTIVE", "Lease is no longer active")
            self._last_heartbeat = self._clock()
            return self.snapshot()

    def reconnect(self, session_id: str, recovery_token: str) -> RelayCredentials:
        """Atomically transfer ownership after abnormal loss, rotating both secrets."""
        with self._lock:
            state, _ = self._current_state()
            self._check_session(session_id)
            if state == RelaySessionState.SHUTDOWN:
                raise RelaySessionError("SESSION_SHUTDOWN", "Normal shutdown forbids reconnect")
            if state == RelaySessionState.EXPIRED:
                raise RelaySessionError("LEASE_EXPIRED", "Lease has expired")
            if state != RelaySessionState.RECOVERABLE:
                raise RelaySessionError(
                    "OWNER_NOT_RECOVERABLE",
                    "Reconnect is allowed only after the owner becomes recoverable",
                )
            if not self._secret_matches(recovery_token, self._recovery_token):
                raise RelaySessionError("INVALID_RECOVERY_TOKEN", "Recovery credential is invalid")

            # All checks and rotation happen under one lock. An old heartbeat
            # racing this operation either wins first (and blocks reconnect),
            # or loses after rotation because its owner token is now stale.
            self._owner_token = self._new_token()
            self._recovery_token = self._new_token()
            self._last_heartbeat = self._clock()
            return RelayCredentials(
                self._session_id, self._owner_token, self._recovery_token
            )

    def shutdown(self, session_id: str, owner_token: str) -> None:
        """Close the session after an authenticated normal shutdown."""
        with self._lock:
            self._check_session(session_id)
            self._check_owner(owner_token)
            if self._closed:
                raise RelaySessionError("SESSION_SHUTDOWN", "Session is already shut down")
            self._closed = True

    def _current_state(self):
        if self._closed:
            return RelaySessionState.SHUTDOWN, max(0.0, self._clock() - self._last_heartbeat)
        elapsed = max(0.0, self._clock() - self._last_heartbeat)
        if elapsed >= self._lease_timeout:
            state = RelaySessionState.EXPIRED
        elif elapsed >= self._recoverable_after:
            state = RelaySessionState.RECOVERABLE
        elif elapsed >= self._suspect_after:
            state = RelaySessionState.SUSPECT
        else:
            state = RelaySessionState.ALIVE
        return state, elapsed

    def _check_session(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not hmac.compare_digest(
            session_id.encode("utf-8"), self._session_id.encode("utf-8")
        ):
            raise RelaySessionError("INVALID_SESSION", "Session identifier is invalid")

    def _check_owner(self, owner_token: str) -> None:
        if not self._secret_matches(owner_token, self._owner_token):
            raise RelaySessionError("INVALID_OWNER_TOKEN", "Owner credential is invalid")

    @staticmethod
    def _secret_matches(candidate: str, expected: str) -> bool:
        return (
            isinstance(candidate, str)
            and bool(candidate)
            and hmac.compare_digest(
                candidate.encode("utf-8"), expected.encode("utf-8")
            )
        )

    def _new_token(self) -> str:
        return secrets.token_urlsafe(self._token_bytes)
