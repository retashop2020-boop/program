from .test_executor import (
    ExecutionLimits,
    ExecutionRequest,
    ExecutionResult,
    TestExecutor,
)
from .test_profiles import TestProfileRegistry
from .workspace import WorkspaceBoundary


class TestExecutionService:
    __test__ = False

    def __init__(
        self,
        registry: TestProfileRegistry,
        executor: TestExecutor,
        limits: ExecutionLimits,
    ):
        if not isinstance(registry, TestProfileRegistry):
            raise ValueError("registry must be a TestProfileRegistry")

        if not callable(getattr(executor, "execute", None)):
            raise ValueError("executor must provide a callable execute method")

        if not isinstance(limits, ExecutionLimits):
            raise ValueError("limits must be an ExecutionLimits instance")

        self._registry = registry
        self._executor = executor
        self._limits = limits

    def execute(
        self,
        profile_id: str,
        workspace: WorkspaceBoundary,
    ) -> ExecutionResult:
        if not isinstance(profile_id, str):
            raise ValueError("profile_id must be a string")

        if not isinstance(workspace, WorkspaceBoundary):
            raise ValueError("workspace must be a WorkspaceBoundary")

        profile = self._registry.get(profile_id)

        request = ExecutionRequest(
            profile=profile,
            workspace_path=workspace.root,
            limits=self._limits,
        )

        return self._executor.execute(request)
