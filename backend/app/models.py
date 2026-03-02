from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Topic(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    key: str = Field(index=True, unique=True)
    stage: str = Field(index=True)


class Question(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    prompt_text: str
    answer_text: str
    answer_type: str = Field(default="text", index=True)
    difficulty: str = Field(default="year8", index=True)
    marks: int = Field(default=1)
    source: str = Field(default="seed")
    tags_json: str = Field(default="[]")
    explanation_hint: str | None = Field(default=None)


class Attempt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="question.id", index=True)
    user_session: str = Field(index=True)
    submitted_answer: str
    is_correct: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    time_taken_sec: int | None = Field(default=None)


class QuizSession(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    mode: str = Field(index=True)
    topic_ids_json: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
