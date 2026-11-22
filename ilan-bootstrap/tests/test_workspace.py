import os

import pytest

from core.workspace import WorkspaceBoundary, WorkspaceViolation


@pytest.fixture
def workspace(tmp_path):
    with WorkspaceBoundary(tmp_path) as boundary:
        yield boundary


@pytest.mark.parametrize("path", ["", None])
def test_open_file_rejects_invalid_path(workspace, path):
    with pytest.raises(
        WorkspaceViolation,
        match="Path must be a non-empty string",
    ):
        workspace.open_file(
            path,
            os.O_RDONLY | os.O_DIRECTORY,
        )


@pytest.mark.parametrize(
    "path, message",
    [
        ("/tmp/outside", "Absolute paths are not allowed"),
        ("../outside", "Parent-directory traversal is not allowed"),
    ],
)
def test_open_file_rejects_unsafe_paths(workspace, path, message):
    with pytest.raises(WorkspaceViolation, match=message):
        workspace.open_file(
            path,
            os.O_RDONLY | os.O_DIRECTORY,
        )


def test_open_file_accepts_workspace_root(workspace):
    fd = workspace.open_file(
        ".",
        os.O_RDONLY | os.O_DIRECTORY,
    )

    try:
        assert os.fstat(fd).st_mode & 0o170000 == 0o040000
    finally:
        os.close(fd)
