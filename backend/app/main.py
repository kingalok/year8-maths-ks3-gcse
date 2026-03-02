import logging
import os
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import create_db_and_tables, engine, get_session
from app.models import Topic
from app.services.quiz_service import (
    get_next_question,
    get_progress,
    get_session_info,
    load_seed_questions_if_empty,
    start_session,
    submit_answer,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("year8-maths")

COOKIE_SESSION_ID = "quiz_session_id"
COOKIE_DIFFICULTY = "quiz_difficulty"
DIFFICULTY_OPTIONS = {"any", "easy", "medium", "hard"}
MODE_OPTIONS = [
    {
        "value": "topic",
        "label": "Focused Revision",
        "description": "Best for mastering one topic deeply.",
    },
    {
        "value": "mixed",
        "label": "Exam Mix",
        "description": "Random exam-style mix from selected topics.",
    },
    {
        "value": "ladder",
        "label": "Adaptive Challenge",
        "description": "Starts easier and steps up when accuracy improves.",
    },
]
MODE_LABELS = {item["value"]: item["label"] for item in MODE_OPTIONS}

app = FastAPI(title="Year 8 Maths Practice", version="0.1.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
PAPER_FILES = {
    "practice": Path("app/data/papers/practice_paper.json"),
    "test": Path("app/data/papers/test_paper.json"),
}


def load_paper(kind: str) -> dict | None:
    path = PAPER_FILES.get(kind)
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_topic_id_values(topic_values: list[str]) -> list[int]:
    topic_ids: set[int] = set()
    for raw_value in topic_values:
        for part in str(raw_value).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                topic_ids.add(int(part))
            except ValueError:
                continue
    return sorted(topic_ids)


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        inserted = load_seed_questions_if_empty(session, "app/data/seed_questions.json")
        logger.info("startup complete; seeded_questions=%s", inserted)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/papers", response_class=HTMLResponse)
def papers_home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "papers_home.html",
        {
            "request": request,
        },
    )


@app.get("/papers/{kind}", response_class=HTMLResponse)
def paper_view(request: Request, kind: str) -> HTMLResponse:
    paper = load_paper(kind)
    if not paper:
        return RedirectResponse(url="/papers", status_code=303)
    return templates.TemplateResponse(
        "paper_view.html",
        {
            "request": request,
            "paper": paper,
            "paper_kind": kind,
        },
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    topics = session.exec(select(Topic).order_by(Topic.stage, Topic.name)).all()
    grouped_topics: dict[str, list[dict]] = defaultdict(list)
    topic_groups: dict[tuple[str, str], dict] = {}
    for topic in topics:
        key = (topic.stage, topic.name.strip().lower())
        if key not in topic_groups:
            topic_groups[key] = {
                "name": topic.name,
                "stage": topic.stage,
                "ids": [],
            }
        if topic.id is not None:
            topic_groups[key]["ids"].append(topic.id)

    for group in topic_groups.values():
        group["ids"] = sorted(set(group["ids"]))
        group["ids_csv"] = ",".join(str(topic_id) for topic_id in group["ids"])
        grouped_topics[group["stage"]].append(group)

    for stage_topics in grouped_topics.values():
        stage_topics.sort(key=lambda item: item["name"].lower())

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "grouped_topics": dict(sorted(grouped_topics.items())),
            "modes": MODE_OPTIONS,
            "difficulties": [
                {"value": "any", "label": "Any"},
                {"value": "easy", "label": "Easy"},
                {"value": "medium", "label": "Medium"},
                {"value": "hard", "label": "Hard"},
            ],
            "error": request.query_params.get("error"),
        },
    )


@app.post("/start")
def start(
    mode: str = Form("topic"),
    topic_ids: list[str] = Form(default=[]),
    difficulty: str = Form("medium"),
) -> RedirectResponse:
    parsed_topic_ids = parse_topic_id_values(topic_ids)
    try:
        session_id = start_session(parsed_topic_ids, mode)
    except ValueError as exc:
        return RedirectResponse(url=f"/?error={quote_plus(str(exc))}", status_code=303)

    difficulty_value = difficulty.strip().lower()
    if difficulty_value not in DIFFICULTY_OPTIONS:
        difficulty_value = "medium"

    response = RedirectResponse(url="/quiz", status_code=303)
    response.set_cookie(key=COOKIE_SESSION_ID, value=session_id, httponly=True, samesite="lax")
    response.set_cookie(key=COOKIE_DIFFICULTY, value=difficulty_value, httponly=True, samesite="lax")
    return response


@app.post("/start-hard")
def start_hard(session: Session = Depends(get_session)) -> RedirectResponse:
    topic_ids = [topic_id for topic_id in session.exec(select(Topic.id)).all() if topic_id is not None]
    if not topic_ids:
        return RedirectResponse(url=f"/?error={quote_plus('No topics available')}", status_code=303)

    try:
        session_id = start_session(topic_ids, "mixed")
    except ValueError as exc:
        return RedirectResponse(url=f"/?error={quote_plus(str(exc))}", status_code=303)

    response = RedirectResponse(url="/quiz", status_code=303)
    response.set_cookie(key=COOKIE_SESSION_ID, value=session_id, httponly=True, samesite="lax")
    response.set_cookie(key=COOKIE_DIFFICULTY, value="hard", httponly=True, samesite="lax")
    return response


@app.get("/quiz", response_class=HTMLResponse)
def quiz_page(request: Request) -> HTMLResponse:
    session_id = request.cookies.get(COOKIE_SESSION_ID)
    if not session_id:
        return RedirectResponse(url="/", status_code=303)
    difficulty = request.cookies.get(COOKIE_DIFFICULTY, "medium")
    if difficulty not in DIFFICULTY_OPTIONS:
        difficulty = "medium"

    session_info = get_session_info(session_id)
    if not session_info:
        return RedirectResponse(url="/", status_code=303)

    progress = get_progress(session_id)
    return templates.TemplateResponse(
        "quiz.html",
        {
            "request": request,
            "session_info": session_info,
            "progress": progress,
            "difficulty": difficulty,
            "mode_label": MODE_LABELS.get(session_info["mode"], session_info["mode"].title()),
        },
    )


@app.get("/question", response_class=HTMLResponse)
def next_question(request: Request) -> HTMLResponse:
    session_id = request.cookies.get(COOKIE_SESSION_ID)
    if not session_id:
        return templates.TemplateResponse(
            "partials/question.html",
            {"request": request, "question": None, "session_info": None, "no_session": True},
        )

    difficulty = request.cookies.get(COOKIE_DIFFICULTY, "medium")
    if difficulty not in DIFFICULTY_OPTIONS:
        difficulty = "medium"

    session_info = get_session_info(session_id)
    if not session_info:
        return templates.TemplateResponse(
            "partials/question.html",
            {"request": request, "question": None, "session_info": None, "no_session": True},
        )

    question = get_next_question(session_id, difficulty_level=difficulty)
    return templates.TemplateResponse(
        "partials/question.html",
        {
            "request": request,
            "question": question,
            "session_info": session_info,
            "no_session": False,
            "difficulty": difficulty,
        },
    )


@app.post("/answer", response_class=HTMLResponse)
def answer(
    request: Request,
    question_id: int = Form(...),
    answer_text: str = Form(...),
) -> HTMLResponse:
    session_id = request.cookies.get(COOKIE_SESSION_ID)
    if not session_id:
        return templates.TemplateResponse(
            "partials/feedback.html",
            {"request": request, "error": "Please start a quiz session first."},
        )

    try:
        result = submit_answer(question_id, session_id, answer_text)
    except ValueError as exc:
        return templates.TemplateResponse(
            "partials/feedback.html",
            {"request": request, "error": str(exc)},
        )

    progress = get_progress(session_id)
    return templates.TemplateResponse(
        "partials/feedback.html",
        {
            "request": request,
            "result": result,
            "progress": progress,
        },
    )
