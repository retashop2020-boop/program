import subprocess

import pytest

from core.authorization import AuthorizationError
from core.docker_executor import DockerTestExecutor
from core.test_executor import (
    ExecutionLimits,
    ExecutionRequest,
    TestExecutionError,
)
from core.test_profiles import TestProfile


class FakeAuthorizationManager:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def authorize(self, operation):
        self.calls.append(operation)

        if self.error is not None:
            raise self.error

        return True


def make_request(workspace):
    profile = TestProfile(
        profile_id="pytest",
        name="Python Pytest",
        command=("python", "-m", "pytest", "-q"),
    )

    return ExecutionRequest(
        profile=profile,
        workspace_path=workspace,
        limits=ExecutionLimits(
            timeout_seconds=120,
            memory_bytes=512 * 1024 * 1024,
            cpu_cores=1.0,
        ),
    )


def test_denied_authorization_prevents_docker_execution(
    tmp_path,
    monkeypatch,
):
    authorization = FakeAuthorizationManager(
        error=AuthorizationError(
            "AUTHORIZATION_DENIED",
            "Permission denied",
        )
    )

    executor = DockerTestExecutor(
        authorization_manager=authorization,
    )

    def unexpected_popen(*args, **kwargs):
        pytest.fail("Docker must not start after denied authorization")

    monkeypatch.setattr(subprocess, "Popen", unexpected_popen)

    with pytest.raises(TestExecutionError) as exc:
        executor.execute(make_request(tmp_path))

    assert exc.value.code == "AUTHORIZATION_DENIED"
    assert len(authorization.calls) == 1


def test_authorization_happens_before_docker_start(
    tmp_path,
    monkeypatch,
):
    authorization = FakeAuthorizationManager()
    events = []

    executor = DockerTestExecutor(
        authorization_manager=authorization,
    )

    def fake_popen(*args, **kwargs):
        events.append("docker")
        raise OSError("Docker unavailable")

    original_authorize = authorization.authorize

    def tracked_authorize(operation):
        events.append("authorization")
        return original_authorize(operation)

    authorization.authorize = tracked_authorize

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with pytest.raises(TestExecutionError) as exc:
        executor.execute(make_request(tmp_path))

    assert exc.value.code == "DOCKER_START_FAILED"
    assert events == ["authorization", "docker"]
    assert len(authorization.calls) == 1
