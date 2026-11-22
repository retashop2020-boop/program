from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Iterable


class TestProfileError(Exception):
    __test__ = False
    pass


class DuplicateTestProfileError(TestProfileError):
    pass


class TestProfileNotFoundError(TestProfileError):
    pass


@dataclass(frozen=True)
class TestProfile:
    __test__ = False
    profile_id: str
    name: str
    command: tuple[str, ...]
    working_directory: str = "."
    timeout_seconds: int = 120

    def __post_init__(self):
        if not isinstance(self.profile_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]*", self.profile_id
        ):
            raise ValueError("Invalid profile_id")

        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")

        if not isinstance(self.command, tuple) or not self.command:
            raise ValueError("command must be a non-empty tuple")

        if any(
            not isinstance(part, str) or not part or "\x00" in part
            for part in self.command
        ):
            raise ValueError("command must contain non-empty strings without NUL")

        if (
            not isinstance(self.working_directory, str)
            or not self.working_directory
            or "\x00" in self.working_directory
            or "\\" in self.working_directory
        ):
            raise ValueError("Invalid working_directory")

        path = PurePosixPath(self.working_directory)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError("working_directory must stay inside the workspace")

        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive integer")


class TestProfileRegistry:
    __test__ = False
    def __init__(self, profiles: Iterable[TestProfile] = ()):
        self._profiles: dict[str, TestProfile] = {}

        for profile in profiles:
            self.register(profile)

    def register(self, profile: TestProfile) -> None:
        if not isinstance(profile, TestProfile):
            raise ValueError("Only TestProfile instances can be registered")

        if profile.profile_id in self._profiles:
            raise DuplicateTestProfileError(
                f"Test profile already exists: {profile.profile_id}"
            )

        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> TestProfile:
        if not isinstance(profile_id, str):
            raise ValueError("profile_id must be a string")

        try:
            return self._profiles[profile_id]
        except KeyError:
            raise TestProfileNotFoundError(
                f"Unknown test profile: {profile_id}"
            ) from None

    def list_profiles(self) -> tuple[TestProfile, ...]:
        return tuple(self._profiles.values())


def create_default_test_profile_registry() -> TestProfileRegistry:
    pytest_profile = TestProfile(
        profile_id="pytest",
        name="Python Pytest",
        command=("python", "-m", "pytest", "-q"),
        working_directory=".",
        timeout_seconds=120,
    )

    return TestProfileRegistry([pytest_profile])
