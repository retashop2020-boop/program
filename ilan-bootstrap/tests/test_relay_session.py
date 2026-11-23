import threading

import pytest

from core.relay_session import (
    RelaySessionError,
    RelaySessionManager,
    RelaySessionState,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_manager(clock=None):
    clock = clock or FakeClock()
    manager = RelaySessionManager(
        suspect_after_seconds=5,
        recoverable_after_seconds=12,
        lease_timeout_seconds=30,
        clock=clock,
    )
    return manager, clock


def test_initial_state_and_credentials_are_created():
    manager, _ = make_manager()
    credentials = manager.initial_credentials()

    assert credentials.session_id
    assert credentials.owner_token
    assert credentials.recovery_token
    assert credentials.owner_token != credentials.recovery_token
    assert manager.snapshot().state is RelaySessionState.ALIVE
    assert "owner_token" not in repr(credentials)


def test_invalid_timing_configuration_is_rejected():
    with pytest.raises(ValueError):
        RelaySessionManager(
            suspect_after_seconds=12,
            recoverable_after_seconds=5,
            lease_timeout_seconds=30,
        )

    with pytest.raises(ValueError):
        RelaySessionManager(
            suspect_after_seconds=float("nan"),
            recoverable_after_seconds=12,
            lease_timeout_seconds=30,
        )


def test_state_progresses_through_suspect_recoverable_and_expired():
    manager, clock = make_manager()
    clock.advance(5)
    assert manager.snapshot().state is RelaySessionState.SUSPECT

    clock.advance(7)
    assert manager.snapshot().state is RelaySessionState.RECOVERABLE

    clock.advance(18)
    assert manager.snapshot().state is RelaySessionState.EXPIRED


def test_authenticate_validates_owner_without_refreshing_lease():
    manager, clock = make_manager()
    credentials = manager.initial_credentials()
    clock.advance(4)

    assert manager.authenticate(credentials.session_id, credentials.owner_token) is None
    assert manager.snapshot().seconds_since_heartbeat == 4

    with pytest.raises(RelaySessionError) as exc:
        manager.authenticate(credentials.session_id, "wrong-token")
    assert exc.value.code == "INVALID_OWNER_TOKEN"

    clock.advance(26)
    with pytest.raises(RelaySessionError) as exc:
        manager.authenticate(credentials.session_id, credentials.owner_token)
    assert exc.value.code == "LEASE_NOT_ACTIVE"


def test_valid_heartbeat_restores_alive_and_resets_lease():
    manager, clock = make_manager()
    credentials = manager.initial_credentials()
    clock.advance(8)
    assert manager.snapshot().state is RelaySessionState.SUSPECT

    result = manager.heartbeat(credentials.session_id, credentials.owner_token)

    assert result.state is RelaySessionState.ALIVE
    assert result.seconds_since_heartbeat == 0


def test_invalid_session_and_owner_credentials_are_rejected():
    manager, _ = make_manager()
    credentials = manager.initial_credentials()

    with pytest.raises(RelaySessionError) as exc:
        manager.heartbeat("wrong-session", credentials.owner_token)
    assert exc.value.code == "INVALID_SESSION"

    with pytest.raises(RelaySessionError) as exc:
        manager.heartbeat(credentials.session_id, "wrong-token")
    assert exc.value.code == "INVALID_OWNER_TOKEN"

    with pytest.raises(RelaySessionError) as exc:
        manager.heartbeat("شناسه-نامعتبر", credentials.owner_token)
    assert exc.value.code == "INVALID_SESSION"

    with pytest.raises(RelaySessionError) as exc:
        manager.heartbeat(credentials.session_id, "توکن-نامعتبر")
    assert exc.value.code == "INVALID_OWNER_TOKEN"


def test_reconnect_is_rejected_before_recoverable_state():
    manager, clock = make_manager()
    credentials = manager.initial_credentials()
    clock.advance(11)

    with pytest.raises(RelaySessionError) as exc:
        manager.reconnect(credentials.session_id, credentials.recovery_token)
    assert exc.value.code == "OWNER_NOT_RECOVERABLE"


def test_reconnect_rotates_owner_and_recovery_tokens():
    manager, clock = make_manager()
    old = manager.initial_credentials()
    clock.advance(12)

    new = manager.reconnect(old.session_id, old.recovery_token)

    assert new.session_id == old.session_id
    assert new.owner_token != old.owner_token
    assert new.recovery_token != old.recovery_token
    assert manager.snapshot().state is RelaySessionState.ALIVE

    with pytest.raises(RelaySessionError) as exc:
        manager.heartbeat(old.session_id, old.owner_token)
    assert exc.value.code == "INVALID_OWNER_TOKEN"

    assert manager.heartbeat(new.session_id, new.owner_token).state is RelaySessionState.ALIVE


def test_recovery_token_is_one_time_and_invalid_token_does_not_transfer_owner():
    manager, clock = make_manager()
    old = manager.initial_credentials()
    clock.advance(12)

    with pytest.raises(RelaySessionError) as exc:
        manager.reconnect(old.session_id, "bad-recovery-token")
    assert exc.value.code == "INVALID_RECOVERY_TOKEN"

    new = manager.reconnect(old.session_id, old.recovery_token)
    clock.advance(12)

    with pytest.raises(RelaySessionError) as exc:
        manager.reconnect(old.session_id, old.recovery_token)
    assert exc.value.code == "INVALID_RECOVERY_TOKEN"

    assert manager.heartbeat(new.session_id, new.owner_token).state is RelaySessionState.ALIVE


def test_reconnect_is_rejected_after_lease_expiry():
    manager, clock = make_manager()
    credentials = manager.initial_credentials()
    clock.advance(30)

    with pytest.raises(RelaySessionError) as exc:
        manager.reconnect(credentials.session_id, credentials.recovery_token)
    assert exc.value.code == "LEASE_EXPIRED"


def test_normal_shutdown_forbids_heartbeat_and_reconnect():
    manager, _ = make_manager()
    credentials = manager.initial_credentials()
    manager.shutdown(credentials.session_id, credentials.owner_token)

    assert manager.snapshot().state is RelaySessionState.SHUTDOWN
    with pytest.raises(RelaySessionError) as exc:
        manager.heartbeat(credentials.session_id, credentials.owner_token)
    assert exc.value.code == "LEASE_NOT_ACTIVE"

    with pytest.raises(RelaySessionError) as exc:
        manager.reconnect(credentials.session_id, credentials.recovery_token)
    assert exc.value.code == "SESSION_SHUTDOWN"


def test_only_one_concurrent_reconnect_can_consume_recovery_token():
    manager, clock = make_manager()
    credentials = manager.initial_credentials()
    clock.advance(12)
    barrier = threading.Barrier(3)
    outcomes = []
    outcome_lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            result = manager.reconnect(credentials.session_id, credentials.recovery_token)
            value = ("ok", result.owner_token)
        except RelaySessionError as exc:
            value = ("error", exc.code)
        with outcome_lock:
            outcomes.append(value)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert sum(kind == "ok" for kind, _ in outcomes) == 1
    assert sum(kind == "error" for kind, _ in outcomes) == 1
    # The losing caller may observe the rotated token or the restored ALIVE
    # state; either way it must not acquire ownership.
    assert any(
        value in ("INVALID_RECOVERY_TOKEN", "OWNER_NOT_RECOVERABLE")
        for kind, value in outcomes
        if kind == "error"
    )
