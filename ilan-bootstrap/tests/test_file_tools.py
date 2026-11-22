import hashlib

import pytest

from core.file_tools import (
    FileTools,
    PatchMatchError,
    PatchStaleError,
)
from core.workspace import WorkspaceBoundary


@pytest.fixture
def file_tools(tmp_path):
    with WorkspaceBoundary(tmp_path) as workspace:
        yield FileTools(workspace)


def test_write_file_creates_new_file(file_tools, tmp_path):
    result = file_tools.write_file("sample.txt", "Hello Ilan")

    assert (tmp_path / "sample.txt").read_text() == "Hello Ilan"
    assert result["created"] is True
    assert result["overwritten"] is False
    assert result["bytes_written"] == len("Hello Ilan".encode("utf-8"))


def test_write_file_prevents_overwrite_without_permission(
    file_tools,
    tmp_path,
):
    file_tools.write_file("sample.txt", "Original")

    with pytest.raises(FileExistsError):
        file_tools.write_file("sample.txt", "Changed")

    assert (tmp_path / "sample.txt").read_text() == "Original"


def test_write_file_allows_explicit_overwrite(file_tools, tmp_path):
    file_tools.write_file("sample.txt", "Original")

    result = file_tools.write_file(
        "sample.txt",
        "Changed",
        overwrite=True,
    )

    assert (tmp_path / "sample.txt").read_text() == "Changed"
    assert result["created"] is False
    assert result["overwritten"] is True


def test_apply_patch_updates_file_and_returns_diff(file_tools, tmp_path):
    original = "def greet():\n    return 'hello'\n"
    file_tools.write_file("sample.py", original)

    result = file_tools.apply_patch({
        "path": "sample.py",
        "expected_sha256": hashlib.sha256(
            original.encode("utf-8")
        ).hexdigest(),
        "changes": [
            {
                "old_text": "return 'hello'",
                "new_text": "return 'hi'",
            }
        ],
    })

    updated = "def greet():\n    return 'hi'\n"

    assert (tmp_path / "sample.py").read_text() == updated
    assert result["changes_applied"] == 1
    assert "-    return 'hello'" in result["diff"]
    assert "+    return 'hi'" in result["diff"]


def test_apply_patch_rejects_stale_hash(file_tools):
    file_tools.write_file("sample.txt", "Current content")

    with pytest.raises(PatchStaleError):
        file_tools.apply_patch({
            "path": "sample.txt",
            "expected_sha256": "0" * 64,
            "changes": [
                {
                    "old_text": "Current",
                    "new_text": "Updated",
                }
            ],
        })


def test_apply_patch_rejects_ambiguous_text(file_tools):
    original = "value = 1\nvalue = 1\n"
    file_tools.write_file("sample.py", original)

    with pytest.raises(PatchMatchError):
        file_tools.apply_patch({
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
        })

def test_preview_patch_does_not_modify_file(file_tools, tmp_path):
    original = "value = 1\n"
    file_tools.write_file("sample.py", original)

    patch = {
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

    result = file_tools.preview_patch(patch)

    assert (tmp_path / "sample.py").read_text() == original
    assert result["bytes_written"] == 0
    assert result["bytes_to_write"] > 0
    assert "+value = 2" in result["diff"]


def test_patch_can_be_applied_after_preview(file_tools, tmp_path):
    original = "value = 1\n"
    file_tools.write_file("sample.py", original)

    patch = {
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

    preview = file_tools.preview_patch(patch)
    result = file_tools.apply_patch(patch)

    assert preview["diff"] == result["diff"]
    assert (tmp_path / "sample.py").read_text() == "value = 2\n"
    assert result["bytes_written"] == len("value = 2\n".encode("utf-8"))
