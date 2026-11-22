import difflib
import hashlib
import os
import re
import stat


class FileToolsError(Exception):
    """Base exception for FileTools operations."""


class FileTooLargeError(FileToolsError):
    """Raised when a read or write exceeds its configured size limit."""


class TooManyEntriesError(FileToolsError):
    """Raised when a directory exceeds the configured entry limit."""


class PatchValidationError(FileToolsError):
    """Raised when a patch has an invalid structure or value."""


class PatchStaleError(FileToolsError):
    """Raised when the source file hash does not match the expected hash."""


class PatchMatchError(FileToolsError):
    """Raised when an old-text pattern has zero or multiple matches."""


class PatchOverlapError(FileToolsError):
    """Raised when patch changes target overlapping text ranges."""


class PatchNoOpError(FileToolsError):
    """Raised when a patch produces no content change."""


class FileTools:
    DEFAULT_MAX_READ_BYTES = 1_048_576
    DEFAULT_MAX_WRITE_BYTES = 1_048_576
    DEFAULT_MAX_LIST_ENTRIES = 1000
    READ_CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        workspace,
        *,
        max_read_bytes=DEFAULT_MAX_READ_BYTES,
        max_write_bytes=DEFAULT_MAX_WRITE_BYTES,
        max_list_entries=DEFAULT_MAX_LIST_ENTRIES,
    ):
        if type(max_read_bytes) is not int or max_read_bytes <= 0:
            raise ValueError("max_read_bytes must be a positive integer")

        if type(max_write_bytes) is not int or max_write_bytes <= 0:
            raise ValueError("max_write_bytes must be a positive integer")

        if type(max_list_entries) is not int or max_list_entries <= 0:
            raise ValueError("max_list_entries must be a positive integer")

        self._workspace = workspace
        self._max_read_bytes = max_read_bytes
        self._max_write_bytes = max_write_bytes
        self._max_list_entries = max_list_entries

    @property
    def max_read_bytes(self) -> int:
        return self._max_read_bytes

    @property
    def max_write_bytes(self) -> int:
        return self._max_write_bytes

    @property
    def max_list_entries(self) -> int:
        return self._max_list_entries

    def list_files(self, path=".") -> list[str]:
        fd = self._workspace.open_file(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NONBLOCK,
        )

        try:
            names = []

            with os.scandir(fd) as entries:
                for entry in entries:
                    names.append(entry.name)

                    if len(names) > self._max_list_entries:
                        raise TooManyEntriesError(
                            f"Directory exceeds the limit of "
                            f"{self._max_list_entries} entries"
                        )

            return sorted(names)

        except TooManyEntriesError:
            raise
        except OSError as exc:
            raise FileToolsError(
                f"Unable to list directory: {path}"
            ) from exc
        finally:
            os.close(fd)

    def write_file(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
    ) -> dict:
        if not isinstance(content, str):
            raise TypeError("content must be a string")

        if type(overwrite) is not bool:
            raise TypeError("overwrite must be a bool")

        try:
            encoded = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise FileToolsError(
                "Content cannot be encoded as UTF-8"
            ) from exc

        if len(encoded) > self._max_write_bytes:
            raise FileTooLargeError(
                f"Content exceeds the write limit of "
                f"{self._max_write_bytes} bytes"
            )

        created = self._workspace.write_atomic(
            path,
            encoded,
            overwrite=overwrite,
        )

        return {
            "path": path,
            "bytes_written": len(encoded),
            "created": created,
            "overwritten": not created,
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    def _read_file_bytes(self, path: str) -> bytes:
        fd = self._workspace.open_file(
            path,
            os.O_RDONLY | os.O_NONBLOCK,
        )

        try:
            file_info = os.fstat(fd)

            if not stat.S_ISREG(file_info.st_mode):
                raise FileToolsError(
                    "Only regular files can be read"
                )

            if file_info.st_size > self._max_read_bytes:
                raise FileTooLargeError(
                    f"File exceeds the limit of "
                    f"{self._max_read_bytes} bytes"
                )

            chunks = []
            total_bytes = 0

            while True:
                remaining = self._max_read_bytes + 1 - total_bytes

                chunk = os.read(
                    fd,
                    min(self.READ_CHUNK_SIZE, remaining),
                )

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > self._max_read_bytes:
                    raise FileTooLargeError(
                        f"File exceeds the limit of "
                        f"{self._max_read_bytes} bytes"
                    )

                chunks.append(chunk)

            return b"".join(chunks)

        except FileToolsError:
            raise
        except OSError as exc:
            raise FileToolsError(
                f"Unable to read file: {path}"
            ) from exc
        finally:
            os.close(fd)

    def apply_patch(self, patch: dict, *, preview_only: bool = False) -> dict:
        if type(patch) is not dict:
            raise PatchValidationError("Patch must be a dictionary")

        if set(patch) != {"path", "expected_sha256", "changes"}:
            raise PatchValidationError(
                "Patch must contain exactly: path, expected_sha256, changes"
            )

        file_path = patch["path"]
        expected_sha256 = patch["expected_sha256"]
        changes = patch["changes"]

        if not isinstance(file_path, str) or not file_path or "\x00" in file_path:
            raise PatchValidationError("path must be a non-empty string")

        if (
            not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise PatchValidationError(
                "expected_sha256 must be 64 lowercase hexadecimal characters"
            )

        if type(changes) is not list or not changes:
            raise PatchValidationError("changes must be a non-empty list")

        validated_changes = []

        for index, change in enumerate(changes):
            if type(change) is not dict or set(change) != {"old_text", "new_text"}:
                raise PatchValidationError(
                    f"Change {index} must contain exactly old_text and new_text"
                )

            old_text = change["old_text"]
            new_text = change["new_text"]

            if not isinstance(old_text, str) or not old_text:
                raise PatchValidationError(
                    f"Change {index}: old_text must be a non-empty string"
                )

            if not isinstance(new_text, str):
                raise PatchValidationError(
                    f"Change {index}: new_text must be a string"
                )

            if "\x00" in old_text or "\x00" in new_text:
                raise PatchValidationError(
                    f"Change {index}: NUL characters are not allowed"
                )

            if old_text == new_text:
                raise PatchNoOpError(
                    f"Change {index} replaces text with identical text"
                )

            try:
                old_text.encode("utf-8", errors="strict")
                new_text.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise PatchValidationError(
                    f"Change {index} contains invalid Unicode"
                ) from exc

            validated_changes.append((old_text, new_text))

        original_bytes = self._read_file_bytes(file_path)

        before_sha256 = hashlib.sha256(original_bytes).hexdigest()

        if before_sha256 != expected_sha256:
            raise PatchStaleError(
                "Source file hash does not match expected_sha256"
            )

        if b"\x00" in original_bytes:
            raise FileToolsError(
                "Source file contains NUL bytes and cannot be patched as text"
            )

        try:
            original_text = original_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise FileToolsError(
                "Source file is not valid UTF-8 text"
            ) from exc

        replacements = []

        for index, (old_text, new_text) in enumerate(validated_changes):
            positions = []
            cursor = 0

            while True:
                position = original_text.find(old_text, cursor)

                if position == -1:
                    break

                positions.append(position)
                cursor = position + 1

            if not positions:
                raise PatchMatchError(
                    f"Change {index}: old_text was not found"
                )

            if len(positions) > 1:
                raise PatchMatchError(
                    f"Change {index}: old_text has multiple matches"
                )

            start = positions[0]
            end = start + len(old_text)
            replacements.append((start, end, new_text))

        ordered_ranges = sorted(replacements, key=lambda item: item[0])

        for previous, current in zip(ordered_ranges, ordered_ranges[1:]):
            if current[0] < previous[1]:
                raise PatchOverlapError(
                    "Patch changes contain overlapping text ranges"
                )

        patched_text = original_text

        for start, end, new_text in sorted(
            replacements,
            key=lambda item: item[0],
            reverse=True,
        ):
            patched_text = (
                patched_text[:start] + new_text + patched_text[end:]
            )

        if patched_text == original_text:
            raise PatchNoOpError("Patch produces no content change")

        try:
            patched_bytes = patched_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise PatchValidationError(
                "Patched content cannot be encoded as UTF-8"
            ) from exc

        if len(patched_bytes) > self._max_write_bytes:
            raise FileTooLargeError(
                f"Patched content exceeds the write limit of "
                f"{self._max_write_bytes} bytes"
            )

        diff_lines = difflib.unified_diff(
            original_text.splitlines(keepends=True),
            patched_text.splitlines(keepends=True),
            fromfile=file_path,
            tofile=file_path,
        )

        formatted_diff = []

        for line in diff_lines:
            formatted_diff.append(line)

            if (
                line.startswith((" ", "+", "-"))
                and not line.endswith(("\n", "\r"))
            ):
                formatted_diff.append(
                    "\n\\ No newline at end of file\n"
                )

        diff = "".join(formatted_diff)

        if not preview_only:
            self._workspace.write_atomic(
                file_path,
                patched_bytes,
                overwrite=True,
            )

        return {
            "path": file_path,
            "before_sha256": before_sha256,
            "after_sha256": hashlib.sha256(patched_bytes).hexdigest(),
            "bytes_written": 0 if preview_only else len(patched_bytes),
            "bytes_to_write": len(patched_bytes),
            "changes_applied": len(replacements),
            "diff": diff,
        }

    def preview_patch(self, patch: dict) -> dict:
        return self.apply_patch(patch, preview_only=True)

    def read_file(self, path: str) -> str:
        content = self._read_file_bytes(path)

        try:
            return content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise FileToolsError(
                "File is not valid UTF-8 text"
            ) from exc
