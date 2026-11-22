import subprocess


class AuthorizationError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class AuthorizationManager:
    def __init__(
        self,
        approval_callback,
        sudo_command=("sudo",),
        timeout_seconds=60,
    ):
        if not callable(approval_callback):
            raise ValueError("approval_callback must be callable")

        if not isinstance(sudo_command, tuple) or not sudo_command:
            raise ValueError("sudo_command must be a non-empty tuple")

        if any(not isinstance(part, str) or not part for part in sudo_command):
            raise ValueError("sudo_command must contain non-empty strings")

        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive integer")

        self._approval_callback = approval_callback
        self._sudo_command = sudo_command
        self._timeout_seconds = timeout_seconds

    def authorize(self, operation):
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")

        try:
            approved = self._approval_callback(operation)
        except Exception as exc:
            raise AuthorizationError(
                "APPROVAL_FAILED",
                "Unable to obtain user approval",
            ) from exc

        if approved is not True:
            raise AuthorizationError(
                "AUTHORIZATION_DENIED",
                "The user denied the requested operation",
            )

        try:
            result = subprocess.run(
                [*self._sudo_command, "-v"],
                check=False,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AuthorizationError(
                "SUDO_AUTHENTICATION_TIMEOUT",
                "Sudo authentication timed out",
            ) from exc
        except OSError as exc:
            raise AuthorizationError(
                "SUDO_UNAVAILABLE",
                "Unable to start sudo",
            ) from exc

        if result.returncode != 0:
            raise AuthorizationError(
                "SUDO_AUTHENTICATION_FAILED",
                "Sudo authentication was not successful",
            )

        return True
