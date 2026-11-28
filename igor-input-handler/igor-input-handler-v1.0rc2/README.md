# Igor Input Handler

**Version:** `1.0.0rc2` (review candidate)  
**Python:** 3.10+  
**Runtime dependencies:** Python standard library only

Igor Input Handler is an independent Python module for collecting user input in two modes and converting it into one canonical string format with no raw CR or LF. It does not send messages to an AI model, manage conversations, or perform terminal I/O itself.

## Installation

From the project directory:

```bash
python -m pip install .
```

For development and tests:

```bash
python -m pip install -e ".[test]"
python -m pytest -q --cov=igor_input_handler --cov-branch --cov-fail-under=90
```

The import name is `igor_input_handler`.

## Quick start

```python
from igor_input_handler import InputHandler

handler = InputHandler()

encoded = handler.from_text("Hello\nHow are you?")
print(encoded)
# Hello\nCTRLHow are you?\end

logical_message = handler.decode(encoded)
print(logical_message)
# Hello
# How are you?
```

The marker strings shown above contain literal backslashes. They are not raw newline characters.

## The two input modes

### Mode 1: a complete string

Use `from_text(text)` when the entire input is already available:

```python
encoded = handler.from_text("first line\nsecond line")
```

`CRLF`, `LF`, and lone `CR` are normalized to logical newlines. When the normalized input ends in a newline, only its final newline represents message submission; earlier newlines remain inside the message. If there is no final newline, message submission is appended automatically.

Examples:

| Input | Logical message | Encoded output |
|---|---|---|
| `"hello"` | `"hello"` | `hello\end` |
| `"hello\n"` | `"hello"` | `hello\end` |
| `"hello\nworld"` | `"hello\nworld"` | `hello\nCTRLworld\end` |
| `"hello\n\n"` | `"hello\n"` | `hello\nCTRL\end` |
| `""` | empty | `\end` |

To include a logical trailing newline in the message, provide two trailing newlines: one for the message content and one for submission.

In Mode 1, text that happens to look like a marker is always ordinary text. You do not manually Escape marker-looking text in this mode.

### Mode 2: line-by-line collection

Use `from_lines(first_line, lines)` when the first line is already available and subsequent lines should be read lazily until the exact end-marker line appears:

```python
from igor_input_handler import InputHandler

handler = InputHandler()


def later_lines():
    while True:
        yield input("> ")

first = input("> ")
encoded = handler.from_lines(first, later_lines())
```

The handler itself does not call `input()`. The terminal adapter above owns terminal interaction and supplies line strings to the handler.

`first_line` and every item from `lines` must:

- be a Python `str`;
- contain exactly one line, with no `CR` or `LF` characters;
- retain any leading or trailing spaces exactly as entered.

A line ends the message only when the entire line exactly equals the configured end marker. Matching is case-sensitive. No whitespace is trimmed.

An empty line is valid message content. To add a newline at the end of the logical body, submit an empty content line before the terminator.

The iterable is consumed only as far as needed. Once the end marker is encountered, no later item is requested. The handler does not close the iterable or any underlying resource.

If the iterable ends before the end marker, `IncompleteInputError` is raised. A partial message is never returned.

#### Entering the end marker as literal content

With the default end marker `\end` and Escape character `~`, prefix a literal end-marker line with one additional Escape character:

| Desired literal line | Type this line |
|---|---|
| `\end` | `~\end` |
| `~\end` | `~~\end` |
| `~~\end` | `~~~\end` |

More generally, a line consisting of one or more consecutive Escape characters followed by the end marker is treated as literal content, with exactly one leading Escape removed. The exact end-marker line, with no leading Escape, terminates input.

Other lines are preserved unchanged. For example, `~\end!` is ordinary text and is not modified.

## Markers and Escape configuration

Defaults:

```python
from igor_input_handler import InputConfig, InputHandler

config = InputConfig(
    internal_enter_marker=r"\nCTRL",
    end_marker=r"\end",
    escape_char="~",
)
handler = InputHandler(config)
```

The control markers are literal strings. The default internal marker is the six-character string backslash + `nCTRL`; the default end marker is backslash + `end`.

Configuration is immutable and validated at construction. The two markers must be non-empty, distinct, contain no actual `CR` or `LF`, and neither may be a prefix of the other. The Escape character must be exactly one Python character, must not be `CR` or `LF`, and must not occur in either marker. The two markers may share their first character.

### Encoded-output Escape rules

Let `I` be the internal-enter marker, `E` the end marker, and `X` the Escape character. The first character of each marker is reserved in ordinary text.

When encoding ordinary text:

- `X` becomes `XX`;
- either reserved marker-prefix character becomes `X` followed by that character;
- a logical newline becomes `I`;
- all other characters remain unchanged;
- exactly one `E` is appended at the end.

This protects both complete marker strings and accidental marker formation across the boundary between message text and the final end marker.

## Decoding

`decode(encoded_message)` validates the complete canonical format and returns the logical message body:

```python
body = handler.decode(encoded)
```

It rejects malformed output rather than guessing how to repair it. In particular, it rejects raw `CR` or `LF`, missing or non-final end markers, invalid Escape sequences, and unescaped reserved prefixes that do not begin a valid control marker. Other Unicode characters, including Unicode line-separator characters, are preserved as ordinary content; only `CR` and `LF` have structural meaning in this version.

The implementation is designed around the round-trip invariant that decoding an encoded logical body recovers that same body. For normal application use, create encoded messages with `from_text` or `from_lines`; `_encode_body` is private and is not part of the public API.

## Exceptions

All module-specific exceptions derive from `InputHandlerError`:

| Exception | Meaning |
|---|---|
| `ConfigurationError` | Invalid marker or Escape configuration |
| `InvalidInputError` | A line or logical input violates its mode contract |
| `IncompleteInputError` | Line source ended before the end marker |
| `OutputFormatError` | Encoded output is malformed |

`TypeError` is used for values of the wrong Python type. `KeyboardInterrupt` is allowed to propagate. Errors raised by a line source, other than `EOFError`, propagate unchanged.

## API summary

```python
InputConfig(
    internal_enter_marker=r"\nCTRL",
    end_marker=r"\end",
    escape_char="~",
)

InputHandler(config: InputConfig | None = None)

InputHandler.from_text(text: str) -> str
InputHandler.from_lines(first_line: str, lines: Iterable[str]) -> str
InputHandler.decode(encoded_message: str) -> str
```

The public exceptions are `InputHandlerError`, `ConfigurationError`, `InvalidInputError`, `IncompleteInputError`, and `OutputFormatError`.

## Scope and non-goals

The module does not implement a CLI, Telegram adapter, GUI, asynchronous input API, file storage, AI-model communication, response handling, or conversation history. These responsibilities belong to the application or adapter using the module.

## Development checks

Run the tests with:

```bash
python -m pip install -e ".[test]"
python -m pytest -q --cov=igor_input_handler --cov-branch --cov-fail-under=90
```

The test suite covers marker collisions, custom markers, escaping, line-ending normalization, lazy iteration, incomplete input, malformed encoded data, deterministic randomized round trips, an independent encoding oracle, and an exhaustive configuration oracle over 1,521 candidate marker pairs (1,356 valid). The test configuration enforces a 90% branch-aware coverage minimum.

## Release status

`1.0.0rc2` is a review candidate. It is intentionally not labelled as a final stable release until independent code and contract reviews have been considered.
