import random

from sqlmodel import Session, select

from app.models import Attempt, Question, Topic


class QuestionRepository:
    def __init__(self, session: Session):
        self.session = session

    def count_questions(self) -> int:
        return len(self.session.exec(select(Question.id)).all())

    def count_topics(self) -> int:
        return len(self.session.exec(select(Topic.id)).all())

    def list_topics(self) -> list[Topic]:
        return list(self.session.exec(select(Topic).order_by(Topic.name)).all())

    def get_topic_by_key(self, topic_key: str) -> Topic | None:
        return self.session.exec(select(Topic).where(Topic.key == topic_key)).first()

    def get_topic_by_id(self, topic_id: int) -> Topic | None:
        return self.session.get(Topic, topic_id)

    def get_by_id(self, question_id: int) -> Question | None:
        return self.session.get(Question, question_id)

    def get_random_question(self, topic_key: str | None = None) -> Question | None:
        stmt = select(Question)
        if topic_key:
            topic = self.get_topic_by_key(topic_key)
            if not topic:
                return None
            stmt = stmt.where(Question.topic_id == topic.id)

        questions = self.session.exec(stmt).all()
        if not questions:
            return None
        return random.choice(questions)

    def add_topics_and_questions(self, topics: list[Topic], questions: list[Question]) -> int:
        for topic in topics:
            self.session.add(topic)
        self.session.flush()

        for question in questions:
            self.session.add(question)

        self.session.commit()
        return len(questions)

    def add_attempt(
        self,
        question_id: int,
        user_session: str,
        submitted_answer: str,
        is_correct: bool,
        time_taken_sec: int | None,
    ) -> Attempt:
        attempt = Attempt(
            question_id=question_id,
            user_session=user_session,
            submitted_answer=submitted_answer,
            is_correct=is_correct,
            time_taken_sec=time_taken_sec,
        )
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)
        return attempt
