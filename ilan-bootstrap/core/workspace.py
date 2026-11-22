import ctypes
import errno
import os
import platform
import secrets
import stat
from pathlib import Path


class WorkspaceViolation(Exception):
    pass


class WorkspaceWriteError(OSError):
    """A write failed; committed indicates whether the destination was changed."""

    def __init__(self, message, *, committed):
        super().__init__(message)
        self.committed = committed



class OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


class WorkspaceBoundary:
    # Linux openat2 constants
    SYS_OPENAT2 = 437
    RESOLVE_NO_MAGICLINKS = 0x02
    RESOLVE_BENEATH = 0x08

    def __init__(self, workspace: str | Path):
        if platform.system() != "Linux":
            raise RuntimeError("Secure workspace access currently requires Linux")

        if platform.machine() not in ("x86_64", "aarch64"):
            raise RuntimeError("Unsupported architecture for openat2 syscall")

        self.root = Path(workspace).expanduser().resolve()

        if not self.root.exists() or not self.root.is_dir():
            raise ValueError("Workspace must be an existing directory")

        self._libc = ctypes.CDLL(None, use_errno=True)

        self._root_fd = os.open(
            self.root,
            os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC,
        )

        self._closed = False

        # Verify openat2 support during initialization.
        try:
            fd = self.open_file(".", os.O_PATH | os.O_DIRECTORY)
            os.close(fd)
        except OSError as exc:
            self.close()
            if exc.errno == errno.ENOSYS:
                raise RuntimeError("Kernel does not support openat2") from exc
            raise

    def _validate_path(self, relative_path: str) -> str:
        if not isinstance(relative_path, str) or not relative_path:
            raise WorkspaceViolation("Path must be a non-empty string")

        if "\x00" in relative_path:
            raise WorkspaceViolation("Null bytes are not allowed")

        candidate = Path(relative_path)

        if candidate.is_absolute():
            raise WorkspaceViolation("Absolute paths are not allowed")

        if ".." in candidate.parts:
            raise WorkspaceViolation("Parent-directory traversal is not allowed")

        return relative_path

    def resolve(self, relative_path: str) -> Path:
        relative_path = self._validate_path(relative_path)

        resolved = (self.root / relative_path).resolve()

        if not resolved.is_relative_to(self.root):
            raise WorkspaceViolation("Path escapes the workspace")

        return resolved

    def open_file(
        self,
        relative_path: str,
        flags: int,
        mode: int = 0,
    ) -> int:
        """
        Securely open a workspace-relative path.

        Returns an OS file descriptor. The caller must close it.

        Internal symlinks are allowed.
        Symlinks escaping the workspace are rejected by openat2.
        """
        if self._closed:
            raise RuntimeError("WorkspaceBoundary is closed")

        relative_path = self._validate_path(relative_path)

        how = OpenHow(
            flags=flags | os.O_CLOEXEC,
            mode=mode,
            resolve=(
                self.RESOLVE_BENEATH
                | self.RESOLVE_NO_MAGICLINKS
            ),
        )

        fd = self._libc.syscall(
            self.SYS_OPENAT2,
            self._root_fd,
            ctypes.c_char_p(os.fsencode(relative_path)),
            ctypes.byref(how),
            ctypes.sizeof(how),
        )

        if fd < 0:
            error = ctypes.get_errno()

            if error in (errno.EXDEV, errno.ELOOP):
                raise WorkspaceViolation(
                    "Path escapes the workspace or uses a forbidden link"
                )

            raise OSError(error, os.strerror(error), relative_path)

        return fd

    def open_parent(self, relative_path: str) -> tuple[int, str]:
        """
        Securely open the parent directory of a workspace-relative file path.

        Returns (parent_directory_fd, basename).
        The caller must close the returned file descriptor.
        """
        relative_path = self._validate_path(relative_path)

        raw_basename = relative_path.rsplit("/", 1)[-1]
        if raw_basename in ("", ".", ".."):
            raise WorkspaceViolation(
                "A file path must include a valid filename"
            )

        path = Path(relative_path)
        basename = path.name
        parent_path = path.parent.as_posix()

        if not basename or basename in (".", ".."):
            raise WorkspaceViolation(
                "A file path must include a valid filename"
            )

        parent_fd = self.open_file(
            parent_path,
            os.O_RDONLY | os.O_DIRECTORY,
        )

        return parent_fd, basename

    def write_atomic(
        self,
        relative_path: str,
        content: bytes,
        *,
        overwrite: bool = False,
    ) -> bool:
        """Atomically write bytes and return True if a new file was created."""
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")

        if type(overwrite) is not bool:
            raise TypeError("overwrite must be a bool")

        parent_fd, basename = self.open_parent(relative_path)
        temp_fd = None
        temp_name = None
        committed = False
        primary_error = None

        try:
            try:
                existing = os.stat(
                    basename,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None

            created = existing is None

            if existing is not None:
                if stat.S_ISLNK(existing.st_mode):
                    raise WorkspaceViolation(
                        "Symbolic-link destinations are not allowed"
                    )

                if not stat.S_ISREG(existing.st_mode):
                    raise WorkspaceViolation(
                        "Only regular files can be replaced"
                    )

                if not overwrite:
                    raise FileExistsError(
                        errno.EEXIST,
                        os.strerror(errno.EEXIST),
                        relative_path,
                    )

                file_mode = stat.S_IMODE(existing.st_mode) & 0o777
            else:
                file_mode = 0o600

            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | os.O_NOFOLLOW
            )

            for _ in range(10):
                candidate = f".ilan-tmp-{secrets.token_hex(16)}"
                try:
                    temp_fd = os.open(
                        candidate,
                        flags,
                        0o600,
                        dir_fd=parent_fd,
                    )
                    temp_name = candidate
                    break
                except FileExistsError:
                    continue
            else:
                raise WorkspaceWriteError(
                    "Unable to allocate a unique temporary filename",
                    committed=False,
                )

            view = memoryview(content)
            offset = 0

            while offset < len(view):
                written = os.write(temp_fd, view[offset:])
                if written <= 0:
                    raise OSError(errno.EIO, "Incomplete file write")
                offset += written

            # Persist the content while the temporary file is still mode 0600.
            os.fsync(temp_fd)

            if overwrite:
                os.replace(
                    temp_name,
                    basename,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                committed = True
                temp_name = None

                # Apply the previous destination mode only after replacement.
                os.fchmod(temp_fd, file_mode)
                os.fsync(temp_fd)
            else:
                os.link(
                    temp_name,
                    basename,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                committed = True

                os.unlink(temp_name, dir_fd=parent_fd)
                temp_name = None

            fd_to_close = temp_fd
            temp_fd = None
            os.close(fd_to_close)
            os.fsync(parent_fd)
            return created

        except Exception as exc:
            primary_error = exc

            if isinstance(
                exc,
                (WorkspaceViolation, FileExistsError, TypeError, WorkspaceWriteError),
            ):
                raise

            if isinstance(exc, OSError):
                if committed:
                    raise WorkspaceWriteError(
                        "Destination was changed, but a later operation failed",
                        committed=True,
                    ) from exc

                raise WorkspaceWriteError(
                    "File operation failed before the destination was changed",
                    committed=False,
                ) from exc

            raise

        finally:
            cleanup_error = None

            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError as exc:
                    cleanup_error = exc

            if temp_name is not None:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    if cleanup_error is None:
                        cleanup_error = exc

            try:
                os.close(parent_fd)
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc

            if cleanup_error is not None and primary_error is None:
                raise WorkspaceWriteError(
                    "File operation cleanup failed",
                    committed=committed,
                ) from cleanup_error

    def close(self):
        if not self._closed:
            os.close(self._root_fd)
            self._closed = True

    def __enter__(self):
        if self._closed:
            raise RuntimeError("WorkspaceBoundary is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
