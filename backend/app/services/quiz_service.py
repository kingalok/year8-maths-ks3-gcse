import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from app.db import engine
from app.models import Attempt, Question, QuizSession, Topic
from app.repository import QuestionRepository

SUPPORTED_MODES = {"topic", "mixed", "ladder"}
SUPPORTED_DIFFICULTIES = {"any", "easy", "medium", "hard"}


@dataclass
class AttemptResult:
    is_correct: bool
    correct_answer: str
    normalized_user_answer: str
    explanation_hint: str | None = None


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def parse_numeric_value(value: str) -> Fraction | None:
    normalized = normalize_answer(value)
    if not normalized:
        return None

    if "/" in normalized:
        parts = normalized.split("/")
        if len(parts) != 2:
            return None
        numerator, denominator = parts
        if not numerator or not denominator:
            return None
        try:
            if float(denominator) == 0:
                return None
            return Fraction(numerator) / Fraction(denominator)
        except (ValueError, ZeroDivisionError):
            return None

    try:
        return Fraction(normalized)
    except ValueError:
        return None


def answers_match(submitted_answer: str, correct_answer: str, answer_type: str) -> bool:
    normalized_submitted = normalize_answer(submitted_answer)
    normalized_correct = normalize_answer(correct_answer)
    if normalized_submitted == normalized_correct:
        return True

    if answer_type == "numeric":
        submitted_num = parse_numeric_value(submitted_answer)
        correct_num = parse_numeric_value(correct_answer)
        if submitted_num is None or correct_num is None:
            return False
        return submitted_num == correct_num

    return False


def _parse_tags(tags_json: str) -> set[str]:
    try:
        tags = json.loads(tags_json)
    except json.JSONDecodeError:
        return set()
    if not isinstance(tags, list):
        return set()
    return {normalize_answer(str(tag)) for tag in tags if str(tag).strip()}


def generate_explanation_hint(question: Question) -> str | None:
    answer_type = normalize_answer(question.answer_type)
    tags = _parse_tags(question.tags_json)

    if answer_type in {"fraction", "decimal"} or {"fraction", "fractions", "decimal", "decimals"} & tags:
        return "Try converting to the same form first (fraction or decimal), then simplify."
    if answer_type == "percentage" or {"percent", "percentage", "percentages"} & tags:
        return "Turn percent into decimal by dividing by 100, then calculate step by step."
    if answer_type == "algebra" or {"algebra", "simplify", "like terms"} & tags:
        return "Collect like terms carefully and simplify each side before your final answer."
    if answer_type == "angles" or {"angle", "angles", "geometry"} & tags:
        return "Remember: straight line = 180, triangle = 180, full turn = 360."
    if answer_type == "ratio" or {"ratio", "ratios"} & tags:
        return "Add ratio parts, divide by total parts, then scale each share."
    return None


def _stable_index(session_id: str, salt: str, size: int) -> int:
    digest = hashlib.sha256(f"{session_id}:{salt}".encode("utf-8")).hexdigest()
    return int(digest, 16) % size


def select_deterministic_question(candidates: list[Question], session_id: str, salt: str) -> Question | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda q: q.id or 0)
    idx = _stable_index(session_id, salt, len(ordered))
    return ordered[idx]


def rolling_accuracy(results: list[bool], window: int = 5) -> float:
    if not results:
        return 0.0
    sample = results[-window:]
    return (sum(1 for v in sample if v) / len(sample)) * 100


def determine_ladder_difficulty(attempts: list[tuple[str, bool]]) -> str:
    easy_results = [is_correct for diff, is_correct in attempts if diff == "easy"]
    if len(easy_results) < 5 or rolling_accuracy(easy_results) <= 70.0:
        return "easy"

    medium_results = [is_correct for diff, is_correct in attempts if diff == "medium"]
    if len(medium_results) < 5 or rolling_accuracy(medium_results) <= 70.0:
        return "medium"

    return "hard"


def _decode_topic_ids(topic_ids_json: str) -> list[int]:
    try:
        values = json.loads(topic_ids_json)
    except json.JSONDecodeError:
        return []
    topic_ids: list[int] = []
    for value in values:
        try:
            topic_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return topic_ids


def start_session(topic_ids: list[int] | int, mode: str = "topic") -> str:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in SUPPORTED_MODES:
        raise ValueError("Unsupported mode")

    if isinstance(topic_ids, int):
        normalized_topic_ids = [topic_ids]
    else:
        normalized_topic_ids = sorted({int(tid) for tid in topic_ids})

    if not normalized_topic_ids:
        raise ValueError("At least one topic must be selected")
    if normalized_mode == "topic" and len(normalized_topic_ids) != 1:
        raise ValueError("Topic Practice mode requires exactly one topic")

    session_id = uuid4().hex
    with Session(engine) as db:
        existing_topic_ids = set(
            db.exec(select(Topic.id).where(Topic.id.in_(normalized_topic_ids))).all()
        )
        if len(existing_topic_ids) != len(normalized_topic_ids):
            raise ValueError("Invalid topic selection")

        db.add(
            QuizSession(
                session_id=session_id,
                mode=normalized_mode,
                topic_ids_json=json.dumps(normalized_topic_ids),
            )
        )
        db.commit()

    return session_id


def get_session_info(session_id: str) -> dict | None:
    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return None
        topic_ids = _decode_topic_ids(quiz_session.topic_ids_json)

        topics = db.exec(select(Topic).where(Topic.id.in_(topic_ids))).all()
        topic_by_id = {topic.id: topic for topic in topics}
        ordered_topics = [topic_by_id[tid] for tid in topic_ids if tid in topic_by_id]

    return {
        "session_id": quiz_session.session_id,
        "mode": quiz_session.mode,
        "topic_ids": topic_ids,
        "topics": ordered_topics,
    }


def get_next_question(session_id: str, difficulty_level: str = "any") -> Question | None:
    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return None

        mode = quiz_session.mode
        topic_ids = _decode_topic_ids(quiz_session.topic_ids_json)
        if mode == "topic" and topic_ids:
            topic_ids = [topic_ids[0]]
        if not topic_ids:
            return None

        attempted_question_ids = set(
            db.exec(
                select(Attempt.question_id)
                .join(Question, Attempt.question_id == Question.id)
                .where(
                    Attempt.user_session == session_id,
                    Question.topic_id.in_(topic_ids),
                )
            ).all()
        )

        base_stmt = select(Question).where(Question.topic_id.in_(topic_ids))
        if attempted_question_ids:
            base_stmt = base_stmt.where(Question.id.notin_(attempted_question_ids))
        available_questions = db.exec(base_stmt).all()
        if not available_questions:
            return None

        requested_difficulty = normalize_answer(difficulty_level)
        if requested_difficulty not in SUPPORTED_DIFFICULTIES:
            requested_difficulty = "any"

        target_difficulty = "all"
        if requested_difficulty in {"easy", "medium", "hard"}:
            filtered_questions = [q for q in available_questions if q.difficulty == requested_difficulty]
            if not filtered_questions:
                return None
            available_questions = filtered_questions
            target_difficulty = requested_difficulty
        elif mode == "ladder":
            attempts = db.exec(
                select(Question.difficulty, Attempt.is_correct)
                .join(Attempt, Attempt.question_id == Question.id)
                .where(
                    Attempt.user_session == session_id,
                    Question.topic_id.in_(topic_ids),
                )
                .order_by(Attempt.created_at)
            ).all()
            target_difficulty = determine_ladder_difficulty(attempts)
            difficulty_questions = [q for q in available_questions if q.difficulty == target_difficulty]
            if difficulty_questions:
                available_questions = difficulty_questions

        salt = f"{mode}:{target_difficulty}:{len(attempted_question_ids)}"
        return select_deterministic_question(available_questions, session_id, salt)


def submit_answer(question_id: int, session_id: str, answer: str) -> AttemptResult:
    normalized_user_answer = normalize_answer(answer)
    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            raise ValueError("Session not found")

        topic_ids = _decode_topic_ids(quiz_session.topic_ids_json)
        if quiz_session.mode == "topic" and topic_ids:
            topic_ids = [topic_ids[0]]

        question = db.get(Question, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")
        if question.topic_id not in topic_ids:
            raise ValueError("Question is not part of this session")

        is_correct = answers_match(answer, question.answer_text, question.answer_type)
        db.add(
            Attempt(
                question_id=question.id,
                user_session=session_id,
                submitted_answer=answer,
                is_correct=is_correct,
                time_taken_sec=None,
            )
        )
        db.commit()

        hint = None
        if not is_correct:
            hint = question.explanation_hint or generate_explanation_hint(question)

        return AttemptResult(
            is_correct=is_correct,
            correct_answer=question.answer_text,
            normalized_user_answer=normalized_user_answer,
            explanation_hint=hint,
        )


def get_progress(session_id: str) -> dict[str, int | float]:
    with Session(engine) as db:
        quiz_session = db.get(QuizSession, session_id)
        if not quiz_session:
            return {"attempted_count": 0, "correct_count": 0, "accuracy_pct": 0.0}

        topic_ids = _decode_topic_ids(quiz_session.topic_ids_json)
        if quiz_session.mode == "topic" and topic_ids:
            topic_ids = [topic_ids[0]]

        attempts = db.exec(
            select(Attempt.is_correct)
            .join(Question, Attempt.question_id == Question.id)
            .where(
                Attempt.user_session == session_id,
                Question.topic_id.in_(topic_ids),
            )
        ).all()

    attempted_count = len(attempts)
    correct_count = sum(1 for is_correct in attempts if is_correct)
    accuracy = round((correct_count / attempted_count) * 100, 1) if attempted_count else 0.0
    return {
        "attempted_count": attempted_count,
        "correct_count": correct_count,
        "accuracy_pct": accuracy,
    }


def load_seed_questions_if_empty(session: Session, seed_path: str) -> int:
    repo = QuestionRepository(session)
    if repo.count_topics() > 0 or repo.count_questions() > 0:
        return 0

    data = json.loads(Path(seed_path).read_text(encoding="utf-8"))

    topics = [Topic(name=row["name"], key=row["key"], stage=row["stage"]) for row in data["topics"]]

    topic_id_by_key: dict[str, int] = {}
    for topic in topics:
        session.add(topic)
    session.flush()
    for topic in topics:
        topic_id_by_key[topic.key] = topic.id  # type: ignore[assignment]

    questions = []
    for row in data["questions"]:
        topic_id = topic_id_by_key[row["topic_key"]]
        questions.append(
            Question(
                topic_id=topic_id,
                prompt_text=row["prompt_text"],
                answer_text=row["answer_text"],
                answer_type=row.get("answer_type", "text"),
                difficulty=row.get("difficulty", "easy"),
                marks=row.get("marks", 1),
                source=row.get("source", "seed"),
                tags_json=json.dumps(row.get("tags", [])),
                explanation_hint=row.get("explanation_hint"),
            )
        )

    for question in questions:
        session.add(question)
    session.commit()
    return len(questions)


def check_answer(question: Question, submitted_answer: str) -> dict:
    is_correct = answers_match(submitted_answer, question.answer_text, question.answer_type)
    hint = None
    if not is_correct:
        hint = question.explanation_hint or generate_explanation_hint(question)
    return {
        "is_correct": is_correct,
        "submitted_answer": submitted_answer,
        "correct_answer": question.answer_text,
        "answer_type": question.answer_type,
        "explanation_hint": hint,
    }
