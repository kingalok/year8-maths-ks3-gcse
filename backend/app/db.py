import os
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

DB_URL = os.getenv("DB_URL", "sqlite:////data/year8_maths.db")
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"

engine = create_engine(DB_URL, echo=SQL_ECHO, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
