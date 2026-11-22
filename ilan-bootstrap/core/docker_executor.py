import os
import selectors
import subprocess
import tempfile
import time
import uuid
from .authorization import AuthorizationError
from pathlib import Path, PurePosixPath

from .test_executor import (
    ExecutionRequest,
    ExecutionResult,
    TestExecutionError,
)


class DockerTestExecutor:
    def __init__(
        self,
        *,
        authorization_manager,
    image="ilan-test:0.1",
        docker_prefix=("sudo", "-n", "docker"),
        max_output_bytes=1_000_000,
    ):
        if not isinstance(image, str) or not image:
            raise ValueError("image must be a non-empty string")

        if not isinstance(docker_prefix, tuple) or not docker_prefix:
            raise ValueError("docker_prefix must be a non-empty tuple")

        if any(not isinstance(part, str) or not part for part in docker_prefix):
            raise ValueError("docker_prefix must contain non-empty strings")

        if (
            not isinstance(max_output_bytes, int)
            or isinstance(max_output_bytes, bool)
            or max_output_bytes <= 0
        ):
            raise ValueError("max_output_bytes must be a positive integer")

        if not callable(getattr(authorization_manager, "authorize", None)):
            raise ValueError("authorization_manager must provide authorize()")

        self._image = image
        self._docker_prefix = docker_prefix
        self._max_output_bytes = max_output_bytes
        self._authorization_manager = authorization_manager

    def _docker_control(self, action, container_name):
        try:
            return subprocess.run(
                [*self._docker_prefix, action, container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if not isinstance(request, ExecutionRequest):
            raise ValueError("request must be an ExecutionRequest")

        try:
            workspace = request.workspace_path.resolve(strict=True)
        except OSError as exc:
            raise TestExecutionError(
                "INVALID_WORKSPACE",
                "Workspace does not exist or cannot be resolved",
            ) from exc

        if not workspace.is_dir():
            raise TestExecutionError(
                "INVALID_WORKSPACE",
                "Workspace must be a directory",
            )

        # Docker's --mount syntax uses commas as separators.
        if "," in str(workspace):
            raise TestExecutionError(
                "INVALID_WORKSPACE_PATH",
                "Workspace paths containing commas are not supported",
            )

        relative_workdir = PurePosixPath(
            request.profile.working_directory
        )

        host_workdir = workspace.joinpath(*relative_workdir.parts)

        try:
            resolved_workdir = host_workdir.resolve(strict=True)
        except OSError as exc:
            raise TestExecutionError(
                "INVALID_WORKING_DIRECTORY",
                "Test working directory does not exist",
            ) from exc

        if (
            not resolved_workdir.is_dir()
            or not resolved_workdir.is_relative_to(workspace)
        ):
            raise TestExecutionError(
                "INVALID_WORKING_DIRECTORY",
                "Test working directory must be inside the workspace",
            )

        container_workdir = (
            "/workspace"
            if relative_workdir.as_posix() == "."
            else f"/workspace/{relative_workdir.as_posix()}"
        )

        try:
            self._authorization_manager.authorize(
                f"Run test profile '{request.profile.profile_id}' "
                f"in workspace '{workspace}' "
                f"using Docker image '{self._image}'"
            )
        except AuthorizationError as exc:
            raise TestExecutionError(
                exc.code,
                exc.message,
            ) from exc

        container_name = f"ilan-test-{uuid.uuid4().hex}"

        limits = request.limits
        timeout_seconds = request.effective_timeout_seconds

        with tempfile.TemporaryDirectory(prefix="ilan-docker-") as temp_dir:
            cidfile = Path(temp_dir) / "container.id"

            command = [
                *self._docker_prefix,
                "run",
                "--rm",
                "--name", container_name,
                "--log-driver", "local",
                "--log-opt", "max-size=1m",
                "--log-opt", "max-file=2",
                "--cidfile", str(cidfile),
                "--network", "none",
                "--read-only",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--pids-limit", "128",
                "--memory", str(limits.memory_bytes),
                "--memory-swap", str(limits.memory_bytes),
                "--cpus", str(limits.cpu_cores),
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,source={workspace},target=/workspace,readonly",
                "--workdir", container_workdir,
                "--env", "HOME=/tmp",
                "--env", "TMPDIR=/tmp",
                self._image,
                *request.profile.command,
            ]

            started_at = time.monotonic()

            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except OSError as exc:
                raise TestExecutionError(
                    "DOCKER_START_FAILED",
                    "Unable to start the Docker client",
                    {"reason": str(exc)},
                ) from exc

            stdout_data = bytearray()
            stderr_data = bytearray()
            total_output = 0
            timed_out = False
            output_limited = False
            kill_sent = False

            selector = selectors.DefaultSelector()

            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)

            selector.register(
                process.stdout,
                selectors.EVENT_READ,
                "stdout",
            )
            selector.register(
                process.stderr,
                selectors.EVENT_READ,
                "stderr",
            )

            deadline = started_at + timeout_seconds

            try:
                while selector.get_map():
                    if (
                        process.poll() is None
                        and time.monotonic() >= deadline
                        and not kill_sent
                    ):
                        timed_out = True
                        kill_sent = True
                        self._docker_control("kill", container_name)

                    events = selector.select(timeout=0.1)

                    for key, _ in events:
                        stream = key.fileobj
                        stream_name = key.data

                        try:
                            chunk = os.read(stream.fileno(), 65536)
                        except BlockingIOError:
                            continue

                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue

                        total_output += len(chunk)

                        if total_output > self._max_output_bytes:
                            output_limited = True
                            if not kill_sent:
                                kill_sent = True
                                self._docker_control("kill", container_name)
                            continue

                        if stream_name == "stdout":
                            stdout_data.extend(chunk)
                        else:
                            stderr_data.extend(chunk)

                return_code = process.wait()

            finally:
                selector.close()

                for stream in (process.stdout, process.stderr):
                    if not stream.closed:
                        stream.close()

                if process.poll() is None:
                    self._docker_control("kill", container_name)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                if timed_out or output_limited:
                    self._docker_control("rm", container_name)

            duration = time.monotonic() - started_at
            stdout_text = stdout_data.decode("utf-8", errors="replace")
            stderr_text = stderr_data.decode("utf-8", errors="replace")

            if output_limited:
                raise TestExecutionError(
                    "OUTPUT_LIMIT_EXCEEDED",
                    "Test output exceeded the configured limit",
                    {
                        "max_output_bytes": self._max_output_bytes,
                        "stdout": stdout_text,
                        "stderr": stderr_text,
                    },
                )

            if timed_out:
                return ExecutionResult(
                    exit_code=return_code,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    duration_seconds=duration,
                    timed_out=True,
                )

            if not cidfile.exists():
                raise TestExecutionError(
                    "DOCKER_START_FAILED",
                    "Docker did not create the test container",
                    {
                        "exit_code": return_code,
                        "stderr": stderr_text,
                    },
                )

            return ExecutionResult(
                exit_code=return_code,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_seconds=duration,
            )
