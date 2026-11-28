"""Independent input collection and message encoding for Igor Input Handler.

The module exposes two input modes:

* ``InputHandler.from_text`` accepts a complete string.
* ``InputHandler.from_lines`` accepts an initial line and a lazy iterable of
  subsequent lines, ending at an exact end-marker line.

Both methods return the same canonical encoded string format, which contains no raw CR or LF. Use
``InputHandler.decode`` to validate that format and recover the logical body.

The implementation has no runtime dependencies outside the Python standard
library and does not perform terminal I/O, logging, network access, or model
communication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

__all__ = [
    "InputConfig",
    "InputHandler",
    "InputHandlerError",
    "ConfigurationError",
    "InvalidInputError",
    "IncompleteInputError",
    "OutputFormatError",
]


class InputHandlerError(Exception):
    """Base class for errors raised by Igor Input Handler."""


class ConfigurationError(InputHandlerError, ValueError):
    """Raised when marker or escape configuration is invalid."""


class InvalidInputError(InputHandlerError, ValueError):
    """Raised when supplied input violates the selected input-mode contract."""


class IncompleteInputError(InputHandlerError, EOFError):
    """Raised when line input ends before the end marker is received."""


class OutputFormatError(InputHandlerError, ValueError):
    """Raised when an encoded message is malformed or incomplete."""


@dataclass(frozen=True, slots=True)
class InputConfig:
    """Immutable marker configuration for an ``InputHandler`` instance.

    The markers are literal strings. For example, the default internal marker
    is the six-character sequence ``\\nCTRL``; it does not contain a newline.
    """

    internal_enter_marker: str = r"\nCTRL"
    end_marker: str = r"\end"
    escape_char: str = "~"

    def __post_init__(self) -> None:
        internal = self.internal_enter_marker
        end = self.end_marker
        escape = self.escape_char

        if not isinstance(internal, str):
            raise ConfigurationError("internal_enter_marker must be a str")
        if not isinstance(end, str):
            raise ConfigurationError("end_marker must be a str")
        if not isinstance(escape, str):
            raise ConfigurationError("escape_char must be a str")

        if not internal:
            raise ConfigurationError("internal_enter_marker must not be empty")
        if not end:
            raise ConfigurationError("end_marker must not be empty")
        if internal == end:
            raise ConfigurationError("internal_enter_marker and end_marker must differ")
        if internal.startswith(end) or end.startswith(internal):
            raise ConfigurationError("control markers must not be prefixes of one another")

        if "\r" in internal or "\n" in internal:
            raise ConfigurationError("internal_enter_marker must not contain CR or LF")
        if "\r" in end or "\n" in end:
            raise ConfigurationError("end_marker must not contain CR or LF")

        if len(escape) != 1:
            raise ConfigurationError("escape_char must be exactly one Python character")
        if escape in "\r\n":
            raise ConfigurationError("escape_char must not be CR or LF")
        if escape in internal or escape in end:
            raise ConfigurationError("escape_char must not occur in either control marker")


class InputHandler:
    """Collect input and encode it using a validated marker configuration.

    Args:
        config: Immutable marker configuration. If omitted, the documented
            default markers are used.

    Public methods return or accept ordinary Python strings. No method writes
    to a terminal or consumes input beyond the exact point required by the
    selected mode.
    """

    def __init__(self, config: InputConfig | None = None) -> None:
        if config is None:
            config = InputConfig()
        elif not isinstance(config, InputConfig):
            raise TypeError("config must be an InputConfig instance or None")

        self._config = config
        self._reserved_prefixes = frozenset(
            (config.internal_enter_marker[0], config.end_marker[0])
        )

    @property
    def config(self) -> InputConfig:
        """Return this handler's immutable configuration."""

        return self._config

    def from_text(self, text: str) -> str:
        """Encode one complete input string.

        CRLF, LF, and lone CR are normalized to logical newlines. If the
        normalized input ends in a newline, its final newline is the send/end
        event and is not part of the logical body. Earlier newlines are kept
        as internal Enter events. If there is no final newline, the end event
        is appended implicitly.
        """

        if not isinstance(text, str):
            raise TypeError("text must be a str")

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if normalized.endswith("\n"):
            body = normalized[:-1]
        else:
            body = normalized
        return self._encode_body(body)

    def from_lines(self, first_line: str, lines: Iterable[str]) -> str:
        """Collect and encode lines until an exact end-marker line is found.

        ``first_line`` is the already-read first line. ``lines`` supplies any
        subsequent lines lazily and must yield strings without CR/LF line
        endings. The iterable is not consumed after the end marker is found.

        A line equal to the end marker terminates input. To enter a literal
        line consisting of one or more escape characters followed by the end
        marker, prefix that line with one additional escape character.
        """

        self._validate_input_line(first_line, "first_line")

        if isinstance(lines, (str, bytes, bytearray)):
            raise TypeError("lines must be an iterable of line strings, not a string or bytes")
        try:
            iterator: Iterator[str] = iter(lines)
        except TypeError as exc:
            raise TypeError("lines must be an iterable of line strings") from exc

        accepted_lines: list[str] = []
        first_is_end, first_content = self._interpret_input_line(first_line)
        if first_is_end:
            return self._encode_body("")
        accepted_lines.append(first_content)

        while True:
            try:
                line = next(iterator)
            except StopIteration as exc:
                raise IncompleteInputError(
                    "line source ended before the end marker was received"
                ) from exc
            except EOFError as exc:
                if isinstance(exc, IncompleteInputError):
                    raise
                raise IncompleteInputError(
                    "line source raised EOF before the end marker was received"
                ) from exc

            self._validate_input_line(line, "line source item")
            is_end, content = self._interpret_input_line(line)
            if is_end:
                body = "\n".join(accepted_lines)
                return self._encode_body(body)
            accepted_lines.append(content)

    def decode(self, encoded_message: str) -> str:
        """Validate a canonical encoded message and return its logical body.

        Raw CR and LF are forbidden in encoded output. Internal newlines must
        be represented by the configured internal-enter marker. Exactly one
        end marker must occur, and it must be the final token.
        """

        if not isinstance(encoded_message, str):
            raise TypeError("encoded_message must be a str")
        if "\r" in encoded_message or "\n" in encoded_message:
            raise OutputFormatError("encoded output must not contain raw CR or LF")

        internal = self._config.internal_enter_marker
        end = self._config.end_marker
        escape = self._config.escape_char
        reserved = self._reserved_prefixes

        decoded: list[str] = []
        index = 0
        length = len(encoded_message)
        end_seen = False

        while index < length:
            char = encoded_message[index]

            if char == escape:
                if index + 1 >= length:
                    raise OutputFormatError("incomplete escape sequence at end of output")

                following = encoded_message[index + 1]
                if following == escape:
                    decoded.append(escape)
                    index += 2
                    continue
                if following in reserved:
                    decoded.append(following)
                    index += 2
                    continue
                raise OutputFormatError(
                    "escape must be followed by itself or a reserved marker prefix"
                )

            if char in reserved:
                if encoded_message.startswith(internal, index):
                    decoded.append("\n")
                    index += len(internal)
                    continue
                if encoded_message.startswith(end, index):
                    if index + len(end) != length:
                        raise OutputFormatError("end marker must be the final token")
                    end_seen = True
                    index += len(end)
                    break
                raise OutputFormatError(
                    "unescaped reserved prefix does not begin a valid control marker"
                )

            decoded.append(char)
            index += 1

        if not end_seen:
            raise OutputFormatError("encoded message is missing its final end marker")
        if index != length:
            # Defensive: the end-marker branch already checks this condition.
            raise OutputFormatError("data found after the end marker")

        return "".join(decoded)

    def _validate_input_line(self, line: str, parameter_name: str) -> None:
        if not isinstance(line, str):
            raise TypeError(f"{parameter_name} must be a str")
        if "\r" in line or "\n" in line:
            raise InvalidInputError(f"{parameter_name} must contain exactly one line without CR or LF")

    def _interpret_input_line(self, line: str) -> tuple[bool, str]:
        """Return (is_terminator, content) for one already-validated line."""

        end = self._config.end_marker
        escape = self._config.escape_char

        if line == end:
            return True, ""

        if line.endswith(end):
            prefix = line[: -len(end)]
            if prefix and all(char == escape for char in prefix):
                # One leading escape quotes the otherwise-special end line.
                return False, prefix[1:] + end

        return False, line

    def _encode_body(self, body: str) -> str:
        """Encode a logical body, whose only newline representation is LF."""

        if "\r" in body:
            raise InvalidInputError("logical message body must not contain raw CR")

        internal = self._config.internal_enter_marker
        end = self._config.end_marker
        escape = self._config.escape_char
        reserved = self._reserved_prefixes

        encoded: list[str] = []
        for char in body:
            if char == "\n":
                encoded.append(internal)
            elif char == escape:
                encoded.append(escape + escape)
            elif char in reserved:
                encoded.append(escape + char)
            else:
                encoded.append(char)

        encoded.append(end)
        return "".join(encoded)
