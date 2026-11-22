import subprocess

import pytest

from core.authorization import AuthorizationError, AuthorizationManager


def test_authorize_runs_sudo_after_approval(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    manager = AuthorizationManager(
        approval_callback=lambda operation: True
    )

    assert manager.authorize("Run approved tests") is True
    assert calls[0][0] == ["sudo", "-v"]


def test_denied_approval_does_not_run_sudo(monkeypatch):
    def unexpected_run(*args, **kwargs):
        pytest.fail("sudo must not run after denied approval")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    manager = AuthorizationManager(
        approval_callback=lambda operation: False
    )

    with pytest.raises(AuthorizationError) as exc:
        manager.authorize("Run approved tests")

    assert exc.value.code == "AUTHORIZATION_DENIED"


def test_sudo_authentication_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    manager = AuthorizationManager(
        approval_callback=lambda operation: True
    )

    with pytest.raises(AuthorizationError) as exc:
        manager.authorize("Run approved tests")

    assert exc.value.code == "SUDO_AUTHENTICATION_FAILED"


def test_sudo_unavailable(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("sudo not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    manager = AuthorizationManager(
        approval_callback=lambda operation: True
    )

    with pytest.raises(AuthorizationError) as exc:
        manager.authorize("Run approved tests")

    assert exc.value.code == "SUDO_UNAVAILABLE"
