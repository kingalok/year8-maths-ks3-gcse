from app.models import Question
from app.services.quiz_service import (
    determine_ladder_difficulty,
    rolling_accuracy,
    select_deterministic_question,
)


def _q(question_id: int) -> Question:
    return Question(
        id=question_id,
        topic_id=1,
        prompt_text="P",
        answer_text="A",
        answer_type="text",
        difficulty="easy",
        marks=1,
        source="test",
        tags_json="[]",
    )


def test_rolling_accuracy_last_window_only() -> None:
    assert rolling_accuracy([True, True, False, True, False, True], window=5) == 60.0


def test_select_deterministic_question_is_stable() -> None:
    candidates = [_q(3), _q(1), _q(2)]
    first = select_deterministic_question(candidates, "session-a", "mixed:all:0")
    second = select_deterministic_question(candidates, "session-a", "mixed:all:0")
    assert first is not None
    assert second is not None
    assert first.id == second.id


def test_select_deterministic_question_changes_with_salt() -> None:
    candidates = [_q(1), _q(2), _q(3), _q(4)]
    first = select_deterministic_question(candidates, "session-a", "mixed:all:0")
    second = select_deterministic_question(candidates, "session-a", "mixed:all:1")
    assert first is not None
    assert second is not None
    assert first.id != second.id


def test_ladder_starts_easy() -> None:
    attempts: list[tuple[str, bool]] = []
    assert determine_ladder_difficulty(attempts) == "easy"


def test_ladder_moves_to_medium_when_easy_over_70_pct() -> None:
    attempts = [
        ("easy", True),
        ("easy", True),
        ("easy", True),
        ("easy", True),
        ("easy", False),
    ]
    assert determine_ladder_difficulty(attempts) == "medium"


def test_ladder_reaches_hard_after_medium_over_70_pct() -> None:
    attempts = [
        ("easy", True),
        ("easy", True),
        ("easy", True),
        ("easy", True),
        ("easy", False),
        ("medium", True),
        ("medium", True),
        ("medium", True),
        ("medium", True),
        ("medium", False),
    ]
    assert determine_ladder_difficulty(attempts) == "hard"


def test_ladder_stays_medium_if_medium_accuracy_not_over_70_pct() -> None:
    attempts = [
        ("easy", True),
        ("easy", True),
        ("easy", True),
        ("easy", True),
        ("easy", False),
        ("medium", True),
        ("medium", False),
        ("medium", True),
        ("medium", False),
        ("medium", False),
    ]
    assert determine_ladder_difficulty(attempts) == "medium"
