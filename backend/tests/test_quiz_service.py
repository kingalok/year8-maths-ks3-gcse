import pytest

from app.models import Question
from app.services.quiz_service import (
    answers_match,
    generate_explanation_hint,
    normalize_answer,
    parse_numeric_value,
)


def test_normalize_answer_trims_lowercases_and_removes_spaces() -> None:
    assert normalize_answer("  1 / 2  ") == "1/2"
    assert normalize_answer(" X Y z ") == "xyz"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7", "7"),
        ("0.5", "1/2"),
        ("3/4", "3/4"),
        (" 10 / 20 ", "1/2"),
        ("-1.25", "-5/4"),
    ],
)
def test_parse_numeric_value_handles_integers_decimals_and_fractions(raw: str, expected: str) -> None:
    parsed = parse_numeric_value(raw)
    assert parsed is not None
    assert str(parsed) == expected


@pytest.mark.parametrize("raw", ["", "abc", "1/0", "2/3/4", "3/"])
def test_parse_numeric_value_rejects_invalid_inputs(raw: str) -> None:
    assert parse_numeric_value(raw) is None


def test_answers_match_for_numeric_equivalence() -> None:
    assert answers_match("0.5", "1/2", "numeric")
    assert answers_match("10/20", "0.5", "numeric")
    assert not answers_match("0.51", "1/2", "numeric")


def test_answers_match_for_text_exact_normalized_only() -> None:
    assert answers_match("  FIVE A ", "fivea", "text")
    assert not answers_match("0.5", "1/2", "text")


@pytest.mark.parametrize(
    ("answer_type", "tags_json", "expected"),
    [
        ("fraction", "[]", "Try converting to the same form first (fraction or decimal), then simplify."),
        ("percentage", "[]", "Turn percent into decimal by dividing by 100, then calculate step by step."),
        ("algebra", "[]", "Collect like terms carefully and simplify each side before your final answer."),
        ("angles", "[]", "Remember: straight line = 180, triangle = 180, full turn = 360."),
        ("ratio", "[]", "Add ratio parts, divide by total parts, then scale each share."),
    ],
)
def test_generate_explanation_hint_from_answer_type(answer_type: str, tags_json: str, expected: str) -> None:
    question = Question(
        topic_id=1,
        prompt_text="p",
        answer_text="a",
        answer_type=answer_type,
        difficulty="easy",
        marks=1,
        source="test",
        tags_json=tags_json,
    )
    assert generate_explanation_hint(question) == expected


def test_generate_explanation_hint_from_tags_when_answer_type_generic() -> None:
    question = Question(
        topic_id=1,
        prompt_text="p",
        answer_text="a",
        answer_type="text",
        difficulty="easy",
        marks=1,
        source="test",
        tags_json='["geometry"]',
    )
    assert generate_explanation_hint(question) == "Remember: straight line = 180, triangle = 180, full turn = 360."
