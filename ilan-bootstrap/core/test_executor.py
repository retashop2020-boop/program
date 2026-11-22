from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Protocol

from .test_profiles import TestProfile


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: int
    memory_bytes: int
    cpu_cores: float

    def __post_init__(self):
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive integer")

        if (
            not isinstance(self.memory_bytes, int)
            or isinstance(self.memory_bytes, bool)
            or self.memory_bytes <= 0
        ):
            raise ValueError("memory_bytes must be a positive integer")

        if (
            isinstance(self.cpu_cores, bool)
            or not isinstance(self.cpu_cores, (int, float))
            or not isfinite(self.cpu_cores)
            or self.cpu_cores <= 0
        ):
            raise ValueError("cpu_cores must be a positive finite number")


@dataclass(frozen=True)
class ExecutionRequest:
    profile: TestProfile
    workspace_path: Path
    limits: ExecutionLimits

    def __post_init__(self):
        if not isinstance(self.profile, TestProfile):
            raise ValueError("profile must be a TestProfile instance")

        if not isinstance(self.workspace_path, Path):
            raise ValueError("workspace_path must be a pathlib.Path")

        if not self.workspace_path.is_absolute():
            raise ValueError("workspace_path must be absolute")

        if not isinstance(self.limits, ExecutionLimits):
            raise ValueError("limits must be an ExecutionLimits instance")

    @property
    def effective_timeout_seconds(self) -> int:
        return min(
            self.profile.timeout_seconds,
            self.limits.timeout_seconds,
        )


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    cancelled: bool = False
    oom_killed: bool = False

    def __post_init__(self):
        if (
            self.exit_code is not None
            and (
                not isinstance(self.exit_code, int)
                or isinstance(self.exit_code, bool)
            )
        ):
            raise ValueError("exit_code must be an integer or None")

        if not isinstance(self.stdout, str):
            raise ValueError("stdout must be a string")

        if not isinstance(self.stderr, str):
            raise ValueError("stderr must be a string")

        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, (int, float))
            or not isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise ValueError("duration_seconds must be a non-negative finite number")

        for field_name in ("timed_out", "cancelled", "oom_killed"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")

        if self.timed_out and self.cancelled:
            raise ValueError("Execution cannot be timed out and cancelled simultaneously")


class TestExecutionError(Exception):
    __test__ = False
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")

        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")

        if details is not None and not isinstance(details, dict):
            raise ValueError("details must be a dictionary or None")

        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details) if details is not None else {}


class TestExecutor(Protocol):
    __test__ = False
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        ...
