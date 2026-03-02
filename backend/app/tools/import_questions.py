import argparse
import csv
import hashlib
import json
from pathlib import Path

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Question, Topic

ALLOWED_ANSWER_TYPES = {"text", "numeric", "fraction", "decimal", "percentage", "algebra", "angles", "ratio"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard", "year8"}
CSV_COLUMNS = {
    "topic_key",
    "prompt_text",
    "answer_text",
    "answer_type",
    "difficulty",
    "marks",
    "source",
    "tags",
}


def normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def slug_to_name(topic_key: str) -> str:
    return normalize_text(topic_key.replace("-", " ").replace("_", " ").title())


def record_hash(topic_key: str, prompt_text: str) -> str:
    raw = f"{normalize_text(topic_key).lower()}::{normalize_text(prompt_text).lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_tags(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_text(v) for v in value if normalize_text(str(v))]

    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [normalize_text(str(v)) for v in parsed if normalize_text(str(v))]
        except json.JSONDecodeError:
            pass

    if "|" in text:
        parts = text.split("|")
    elif ";" in text:
        parts = text.split(";")
    else:
        parts = [text]
    return [normalize_text(p) for p in parts if normalize_text(p)]


def parse_marks(value: str | int | None) -> int:
    if value is None:
        return 1
    if isinstance(value, int):
        return value
    return int(value)


def validate_record(record: dict) -> list[str]:
    errors: list[str] = []
    required = ["topic_key", "prompt_text", "answer_text", "answer_type"]
    for key in required:
        if not normalize_text(str(record.get(key, ""))):
            errors.append(f"missing {key}")

    answer_type = normalize_text(str(record.get("answer_type", "")).lower())
    if answer_type and answer_type not in ALLOWED_ANSWER_TYPES:
        errors.append(f"invalid answer_type '{answer_type}'")

    difficulty = normalize_text(str(record.get("difficulty", "easy")).lower())
    if difficulty and difficulty not in ALLOWED_DIFFICULTIES:
        errors.append(f"invalid difficulty '{difficulty}'")

    try:
        marks = parse_marks(record.get("marks"))
        if marks < 1:
            errors.append("marks must be >= 1")
    except (TypeError, ValueError):
        errors.append("invalid marks")

    return errors


def load_json_records(path: Path) -> tuple[dict[str, dict], list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    topics_payload = payload.get("topics", [])
    questions_payload = payload.get("questions", [])

    topics_by_key: dict[str, dict] = {}
    for topic in topics_payload:
        key = normalize_text(str(topic.get("key", ""))).lower()
        if not key:
            continue
        topics_by_key[key] = {
            "key": key,
            "name": normalize_text(str(topic.get("name", ""))) or slug_to_name(key),
            "stage": normalize_text(str(topic.get("stage", "KS3"))).upper() or "KS3",
        }

    records: list[dict] = []
    for row in questions_payload:
        topic_key = normalize_text(str(row.get("topic_key", ""))).lower()
        if topic_key and topic_key not in topics_by_key:
            topics_by_key[topic_key] = {
                "key": topic_key,
                "name": slug_to_name(topic_key),
                "stage": "KS3",
            }

        records.append(
            {
                "topic_key": topic_key,
                "prompt_text": normalize_text(str(row.get("prompt_text", ""))),
                "answer_text": normalize_text(str(row.get("answer_text", ""))),
                "answer_type": normalize_text(str(row.get("answer_type", "text")).lower()),
                "difficulty": normalize_text(str(row.get("difficulty", "easy")).lower()),
                "marks": row.get("marks", 1),
                "source": normalize_text(str(row.get("source", "import"))) or "import",
                "tags": parse_tags(row.get("tags", [])),
                "explanation_hint": normalize_text(str(row.get("explanation_hint", ""))) or None,
            }
        )

    return topics_by_key, records


def load_csv_records(path: Path) -> tuple[dict[str, dict], list[dict]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = set(reader.fieldnames or [])
        missing = CSV_COLUMNS - fieldnames
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")

        topics_by_key: dict[str, dict] = {}
        records: list[dict] = []
        for row in reader:
            topic_key = normalize_text(row.get("topic_key", "")).lower()
            if topic_key and topic_key not in topics_by_key:
                topics_by_key[topic_key] = {
                    "key": topic_key,
                    "name": slug_to_name(topic_key),
                    "stage": "KS3",
                }

            records.append(
                {
                    "topic_key": topic_key,
                    "prompt_text": normalize_text(row.get("prompt_text", "")),
                    "answer_text": normalize_text(row.get("answer_text", "")),
                    "answer_type": normalize_text(row.get("answer_type", "text")).lower(),
                    "difficulty": normalize_text(row.get("difficulty", "easy")).lower(),
                    "marks": row.get("marks", "1"),
                    "source": normalize_text(row.get("source", "import")) or "import",
                    "tags": parse_tags(row.get("tags", "")),
                    "explanation_hint": normalize_text(row.get("explanation_hint", "")) or None,
                }
            )

    return topics_by_key, records


def infer_format(path: Path, explicit: str | None) -> str:
    if explicit in {"json", "csv"}:
        return explicit
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    raise ValueError("Cannot infer format from file extension; pass --format json|csv")


def import_questions(input_path: Path, file_format: str) -> dict:
    if file_format == "json":
        topics_by_key, records = load_json_records(input_path)
    else:
        topics_by_key, records = load_csv_records(input_path)

    create_db_and_tables()

    created_topics = 0
    inserted_questions = 0
    skipped_duplicates = 0
    invalid_records = 0

    with Session(engine) as session:
        existing_topics = {topic.key: topic for topic in session.exec(select(Topic)).all()}
        existing_pairs = session.exec(
            select(Topic.key, Question.prompt_text)
            .join(Question, Topic.id == Question.topic_id)
        ).all()
        existing_hashes = {record_hash(topic_key, prompt_text) for topic_key, prompt_text in existing_pairs}

        for key, data in topics_by_key.items():
            if key in existing_topics:
                continue
            topic = Topic(name=data["name"], key=key, stage=data.get("stage", "KS3") or "KS3")
            session.add(topic)
            session.flush()
            existing_topics[key] = topic
            created_topics += 1

        import_hashes: set[str] = set()
        for idx, record in enumerate(records, start=1):
            errors = validate_record(record)
            if errors:
                invalid_records += 1
                print(f"skip row {idx}: {', '.join(errors)}")
                continue

            topic_key = record["topic_key"]
            q_hash = record_hash(topic_key, record["prompt_text"])
            if q_hash in existing_hashes or q_hash in import_hashes:
                skipped_duplicates += 1
                continue

            topic = existing_topics.get(topic_key)
            if not topic:
                topic = Topic(name=slug_to_name(topic_key), key=topic_key, stage="KS3")
                session.add(topic)
                session.flush()
                existing_topics[topic_key] = topic
                created_topics += 1

            session.add(
                Question(
                    topic_id=topic.id,
                    prompt_text=record["prompt_text"],
                    answer_text=record["answer_text"],
                    answer_type=record["answer_type"],
                    difficulty=record["difficulty"] or "easy",
                    marks=parse_marks(record.get("marks")),
                    source=record["source"] or "import",
                    tags_json=json.dumps(record.get("tags", [])),
                    explanation_hint=record.get("explanation_hint"),
                )
            )
            import_hashes.add(q_hash)
            inserted_questions += 1

        session.commit()

    return {
        "created_topics": created_topics,
        "inserted_questions": inserted_questions,
        "skipped_duplicates": skipped_duplicates,
        "invalid_records": invalid_records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import user-provided extracted maths questions (JSON or CSV) into SQLite."
    )
    parser.add_argument("--input", required=True, help="Path to JSON or CSV file")
    parser.add_argument("--format", choices=["json", "csv"], default=None, help="Optional explicit format")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    file_format = infer_format(input_path, args.format)
    summary = import_questions(input_path, file_format)

    print("Import complete")
    print(f"created topics: {summary['created_topics']}")
    print(f"inserted questions: {summary['inserted_questions']}")
    print(f"skipped duplicates: {summary['skipped_duplicates']}")
    print(f"invalid records: {summary['invalid_records']}")


if __name__ == "__main__":
    main()
