from core.test_profiles import create_default_test_profile_registry
from tools.registry import ToolRegistry
from tools.run_tests import register_run_tests


def test_run_tests_schema_uses_registered_profile_ids():
    profiles = create_default_test_profile_registry()
    registry = ToolRegistry()

    register_run_tests(registry, object(), object(), profiles)

    tool = registry.get("run_tests")

    assert tool["parameters"]["properties"]["profile_id"]["enum"] == ["pytest"]
    assert tool["parameters"]["required"] == ["profile_id"]
    assert tool["parameters"]["additionalProperties"] is False
    assert "pytest" in tool["description"]


def test_run_tests_passes_profile_and_workspace_to_service():
    profiles = create_default_test_profile_registry()
    registry = ToolRegistry()
    workspace = object()

    class FakeTestService:
        def execute(self, profile_id, received_workspace):
            return profile_id, received_workspace

    register_run_tests(registry, FakeTestService(), workspace, profiles)

    result = registry.get("run_tests")["execute"]({"profile_id": "pytest"})

    assert result == ("pytest", workspace)
