import hashlib

import pytest

from core.file_tools import FileTools, PatchStaleError
from core.workspace import WorkspaceBoundary
from tools.apply_patch import register_apply_patch
from tools.registry import ToolRegistry


@pytest.fixture
def setup_tool(tmp_path):
    with WorkspaceBoundary(tmp_path) as workspace:
        file_tools = FileTools(workspace)
        registry = ToolRegistry()
        approvals = []

        def approval_callback(preview):
            approvals.append(preview)
            return True

        register_apply_patch(
            registry,
            file_tools,
            approval_callback,
        )

        yield registry.get("apply_patch"), file_tools, approvals, tmp_path


def make_patch(original):
    return {
        "path": "sample.py",
        "expected_sha256": hashlib.sha256(
            original.encode("utf-8")
        ).hexdigest(),
        "changes": [
            {
                "old_text": "value = 1",
                "new_text": "value = 2",
            }
        ],
    }


def test_rejected_patch_does_not_modify_file(setup_tool):
    tool, file_tools, approvals, tmp_path = setup_tool
    original = "value = 1\n"
    file_tools.write_file("sample.py", original)

    def reject(preview):
        approvals.append(preview)
        return False

    tool, _, _, _ = setup_tool
    registry = ToolRegistry()
    register_apply_patch(registry, file_tools, reject)

    result = registry.get("apply_patch")["execute"](
        make_patch(original)
    )

    assert result["status"] == "rejected"
    assert (tmp_path / "sample.py").read_text() == original
    assert len(approvals) == 1
    assert "+value = 2" in approvals[0]["diff"]


def test_approved_patch_is_applied(setup_tool):
    tool, file_tools, approvals, tmp_path = setup_tool
    original = "value = 1\n"
    file_tools.write_file("sample.py", original)

    result = tool["execute"](make_patch(original))

    assert result["status"] == "applied"
    assert (tmp_path / "sample.py").read_text() == "value = 2\n"
    assert len(approvals) == 1


def test_stale_patch_is_not_applied_after_preview(setup_tool):
    tool, file_tools, approvals, tmp_path = setup_tool
    original = "value = 1\n"
    file_tools.write_file("sample.py", original)

    def modify_during_approval(preview):
        approvals.append(preview)
        file_tools.write_file(
            "sample.py",
            "value = 3\n",
            overwrite=True,
        )
        return True

    registry = ToolRegistry()
    register_apply_patch(
        registry,
        file_tools,
        modify_during_approval,
    )

    with pytest.raises(PatchStaleError):
        registry.get("apply_patch")["execute"](
            make_patch(original)
        )

    assert (tmp_path / "sample.py").read_text() == "value = 3\n"
    assert len(approvals) == 1
