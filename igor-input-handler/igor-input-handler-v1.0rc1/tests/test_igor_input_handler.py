from __future__ import annotations

import random
from dataclasses import FrozenInstanceError

import pytest

from igor_input_handler import (
    ConfigurationError,
    IncompleteInputError,
    InputConfig,
    InputHandler,
    InvalidInputError,
    OutputFormatError,
)


DEFAULT_I = r"\nCTRL"
DEFAULT_E = r"\end"
DEFAULT_X = "~"


@pytest.fixture()
def handler() -> InputHandler:
    return InputHandler()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("سلام", r"سلام\end"),
        ("سلام\n", r"سلام\end"),
        ("سلام\nخوبی", r"سلام\nCTRLخوبی\end"),
        ("سلام\n\n", r"سلام\nCTRL\end"),
        ("\n", r"\end"),
        ("\n\n", r"\nCTRL\end"),
        ("", r"\end"),
    ],
)
def test_from_text_examples(handler: InputHandler, raw: str, expected: str) -> None:
    assert handler.from_text(raw) == expected


def test_from_text_normalizes_all_supported_line_endings(handler: InputHandler) -> None:
    assert handler.from_text("a\r\nb") == handler.from_text("a\nb")
    assert handler.from_text("a\rb") == handler.from_text("a\nb")
    assert handler.from_text("a\r\n\r\nb") == handler.from_text("a\n\nb")


def test_mode1_marker_looking_text_is_literal(handler: InputHandler) -> None:
    body = r"literal \end and \nCTRL"
    encoded = handler.from_text(body)
    assert handler.decode(encoded) == body


def test_escape_character_and_reserved_prefixes_round_trip(handler: InputHandler) -> None:
    body = "~\\nCTRL\\end\\~~"
    assert handler.decode(handler.from_text(body)) == body


def test_config_is_immutable() -> None:
    config = InputConfig()
    with pytest.raises(FrozenInstanceError):
        config.escape_char = "!"  # type: ignore[misc]


def test_handler_exposes_its_configuration() -> None:
    config = InputConfig()
    assert InputHandler(config).config is config


@pytest.mark.parametrize(
    "kwargs",
    [
        {"internal_enter_marker": ""},
        {"end_marker": ""},
        {"internal_enter_marker": "same", "end_marker": "same"},
        {"internal_enter_marker": "abc", "end_marker": "ab"},
        {"internal_enter_marker": "ab", "end_marker": "abc"},
        {"internal_enter_marker": "a\nb"},
        {"end_marker": "a\rb"},
        {"internal_enter_marker": "a~b"},
        {"end_marker": "a~b"},
        {"escape_char": ""},
        {"escape_char": "!!"},
        {"escape_char": "\n"},
        {"escape_char": "\r"},
        {"escape_char": "\\"},
    ],
)
def test_invalid_configuration_is_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError):
        base = InputConfig()
        values = {
            "internal_enter_marker": base.internal_enter_marker,
            "end_marker": base.end_marker,
            "escape_char": base.escape_char,
        }
        values.update(kwargs)
        InputConfig(**values)


def test_config_non_string_values_are_rejected() -> None:
    with pytest.raises(ConfigurationError):
        InputConfig(internal_enter_marker=None)  # type: ignore[arg-type]


def test_handler_rejects_non_config() -> None:
    with pytest.raises(TypeError):
        InputHandler(config={})  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, 1, b"text", [], object()])
def test_from_text_rejects_non_strings(handler: InputHandler, value: object) -> None:
    with pytest.raises(TypeError):
        handler.from_text(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, 1, b"text", [], object()])
def test_decode_rejects_non_strings(handler: InputHandler, value: object) -> None:
    with pytest.raises(TypeError):
        handler.decode(value)  # type: ignore[arg-type]


def test_mode2_simple_input(handler: InputHandler) -> None:
    assert handler.from_lines("سلام", [DEFAULT_E]) == handler.from_text("سلام\n")


def test_mode2_blank_lines(handler: InputHandler) -> None:
    assert handler.decode(handler.from_lines("سلام", ["", DEFAULT_E])) == "سلام\n"
    assert handler.decode(handler.from_lines("", ["", DEFAULT_E])) == "\n"
    assert handler.decode(handler.from_lines("", [DEFAULT_E])) == ""


def test_mode2_initial_terminator_returns_empty_body_without_consuming_items(
    handler: InputHandler,
) -> None:
    class ExplodingIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise AssertionError("the iterator must not be consumed")

    assert handler.from_lines(DEFAULT_E, ExplodingIterator()) == handler.from_text("")


def test_mode2_does_not_consume_after_terminator(handler: InputHandler) -> None:
    consumed: list[str] = []

    def source():
        consumed.append("first")
        yield "second"
        consumed.append("terminator")
        yield DEFAULT_E
        consumed.append("must-not-be-read")
        yield "unexpected"

    assert handler.decode(handler.from_lines("first", source())) == "first\nsecond"
    assert consumed == ["first", "terminator"]


@pytest.mark.parametrize(
    ("desired", "typed"),
    [
        (DEFAULT_E, "~" + DEFAULT_E),
        ("~" + DEFAULT_E, "~~" + DEFAULT_E),
        ("~~" + DEFAULT_E, "~~~" + DEFAULT_E),
        ("~~~" + DEFAULT_E, "~~~~" + DEFAULT_E),
        ("~~~~~~~" + DEFAULT_E, "~~~~~~~~" + DEFAULT_E),
    ],
)
def test_mode2_escaped_terminator_line(
    handler: InputHandler, desired: str, typed: str
) -> None:
    result = handler.from_lines(typed, [DEFAULT_E])
    assert handler.decode(result) == desired


def test_mode2_escaped_terminator_works_after_first_line(handler: InputHandler) -> None:
    result = handler.from_lines("prefix", ["~" + DEFAULT_E, DEFAULT_E])
    assert handler.decode(result) == "prefix\n" + DEFAULT_E


def test_mode2_only_exact_terminator_line_ends_input(handler: InputHandler) -> None:
    encoded = handler.from_lines(" ", [DEFAULT_E + " ", "hello " + DEFAULT_E, DEFAULT_E])
    assert handler.decode(encoded) == " \n" + DEFAULT_E + " \nhello " + DEFAULT_E


@pytest.mark.parametrize("line", ["a\nb", "a\rb", "\n", "\r"])
def test_mode2_rejects_multiline_lines(handler: InputHandler, line: str) -> None:
    with pytest.raises(InvalidInputError):
        handler.from_lines(line, [DEFAULT_E])
    with pytest.raises(InvalidInputError):
        handler.from_lines("ok", [line, DEFAULT_E])


def test_mode2_rejects_non_string_lines(handler: InputHandler) -> None:
    with pytest.raises(TypeError):
        handler.from_lines("first", [123, DEFAULT_E])  # type: ignore[list-item]


def test_mode2_rejects_string_as_lines_argument(handler: InputHandler) -> None:
    with pytest.raises(TypeError):
        handler.from_lines("first", DEFAULT_E)


def test_mode2_rejects_non_iterable_lines_argument(handler: InputHandler) -> None:
    with pytest.raises(TypeError):
        handler.from_lines("first", 123)  # type: ignore[arg-type]


def test_mode2_maps_stop_iteration_to_incomplete_input(handler: InputHandler) -> None:
    with pytest.raises(IncompleteInputError):
        handler.from_lines("first", [])


def test_mode2_maps_eoferror_to_incomplete_input(handler: InputHandler) -> None:
    class EOFIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise EOFError("underlying reader EOF")

    with pytest.raises(IncompleteInputError):
        handler.from_lines("first", EOFIterator())


def test_mode2_propagates_other_source_errors(handler: InputHandler) -> None:
    class BrokenIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise RuntimeError("source failure")

    with pytest.raises(RuntimeError, match="source failure"):
        handler.from_lines("first", BrokenIterator())


def test_mode2_preserves_original_incomplete_input_error(handler: InputHandler) -> None:
    class IncompleteIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise IncompleteInputError("already classified")

    with pytest.raises(IncompleteInputError, match="already classified"):
        handler.from_lines("first", IncompleteIterator())


def test_custom_marker_prefix_collision_is_avoided() -> None:
    custom = InputHandler(InputConfig("ab", "bc", "~"))
    encoded = custom.from_text("a")
    assert encoded == "~abc"
    assert custom.decode(encoded) == "a"


def test_custom_markers_with_shared_initial_character_are_unambiguous() -> None:
    custom = InputHandler(InputConfig("abc", "abd", "~"))
    for body in ["", "a", "abc", "abd", "xabcabd", "~a\nb"]:
        assert custom.decode(custom.from_text(body)) == body


def test_custom_markers_with_overlapping_internal_characters_round_trip() -> None:
    custom = InputHandler(InputConfig("abxy", "bcab", "~"))
    bodies = ["a", "b", "ab", "bc", "xy", "abxybcab", "~ab\nbc"]
    for body in bodies:
        assert custom.decode(custom.from_text(body)) == body


def test_decoder_rejects_missing_end_marker(handler: InputHandler) -> None:
    with pytest.raises(OutputFormatError):
        handler.decode("plain")


@pytest.mark.parametrize(
    "encoded",
    [
        "plain\n" + DEFAULT_E,
        "plain\r" + DEFAULT_E,
        DEFAULT_E + "trailing",
        DEFAULT_E + DEFAULT_E,
        "~",
        "~x" + DEFAULT_E,
        "\\unknown" + DEFAULT_E,
        "\\nCT" + DEFAULT_E,
    ],
)
def test_decoder_rejects_malformed_output(handler: InputHandler, encoded: str) -> None:
    with pytest.raises(OutputFormatError):
        handler.decode(encoded)


def test_decoder_rejects_end_marker_in_middle(handler: InputHandler) -> None:
    with pytest.raises(OutputFormatError):
        handler.decode("before" + DEFAULT_E + "after")


def test_decoder_rejects_unescaped_reserved_prefix(handler: InputHandler) -> None:
    with pytest.raises(OutputFormatError):
        handler.decode("\\not-a-token" + DEFAULT_E)


def test_decoder_accepts_internal_marker_then_end_marker(handler: InputHandler) -> None:
    encoded = DEFAULT_I + DEFAULT_E
    assert handler.decode(encoded) == "\n"


def test_encode_decode_round_trip_randomized_default_config() -> None:
    rng = random.Random(917_2026)
    handler = InputHandler()
    alphabet = [
        "a", "b", "z", "~", "\\", "n", "C", "T", "R", "L",
        "0", " ", "ا", "ب", "🙂", "é", "\u0301", "\n", "\t",
    ]
    for _ in range(2_000):
        body = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 50)))
        assert handler.decode(handler._encode_body(body)) == body


def test_encode_decode_round_trip_randomized_custom_configs() -> None:
    rng = random.Random(44_011)
    configurations = [
        InputConfig("ab", "bc", "~"),
        InputConfig("abc", "abd", "!"),
        InputConfig("<I>", "<E>", "^"),
        InputConfig("xy1", "yx2", "#"),
    ]
    for config in configurations:
        handler = InputHandler(config)
        alphabet = list("abcxyz123<>!^#~ ") + ["🙂", "ا", "\n", "\t"]
        for _ in range(500):
            body = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
            assert handler.decode(handler._encode_body(body)) == body


def test_mode1_decode_property_for_newline_inputs(handler: InputHandler) -> None:
    cases = ["", "\n", "\n\n", "a", "a\n", "a\n\n", "a\rb", "a\r\nb\n"]
    for raw in cases:
        normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
        expected = normalized[:-1] if normalized.endswith("\n") else normalized
        assert handler.decode(handler.from_text(raw)) == expected


def test_mode1_mode2_equivalence(handler: InputHandler) -> None:
    examples = [
        ["one"],
        ["one", "two"],
        ["one", ""],
        ["", ""],
        ["", "middle", ""],
        ["~", r"literal \end", "🙂"],
    ]
    for accepted_lines in examples:
        # The chosen lines do not equal the terminator or its quoting syntax.
        mode2 = handler.from_lines(accepted_lines[0], [*accepted_lines[1:], DEFAULT_E])
        mode1_raw = "\n".join(accepted_lines) + "\n"
        assert mode2 == handler.from_text(mode1_raw)


def test_mode2_quoted_terminator_matches_mode1_logical_body(handler: InputHandler) -> None:
    desired_lines = ["before", DEFAULT_E, "after"]
    mode2_lines = ["before", "~" + DEFAULT_E, "after", DEFAULT_E]
    mode2 = handler.from_lines(mode2_lines[0], mode2_lines[1:])
    expected_body = "\n".join(desired_lines)
    assert handler.decode(mode2) == expected_body
    assert mode2 == handler._encode_body(expected_body)


def test_escape_is_one_python_character_not_one_grapheme_cluster() -> None:
    # A combining sequence has two Python characters and is rejected.
    with pytest.raises(ConfigurationError):
        InputConfig(escape_char="e\u0301")


def test_unicode_line_separator_characters_are_preserved_as_content(
    handler: InputHandler,
) -> None:
    body = "before\u2028middle\u2029after"
    assert handler.decode(handler.from_text(body)) == body


def test_keyboard_interrupt_from_line_source_propagates(handler: InputHandler) -> None:
    class InterruptIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        handler.from_lines("first", InterruptIterator())
