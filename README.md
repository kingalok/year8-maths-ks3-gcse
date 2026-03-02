# Year 8 Maths Practice Web App

A local-first maths practice platform for Year 8 (KS3) with GCSE-style progression.
Built for home revision, quick daily practice, and exam warmups.

## Why This Project

- Fast and simple for students: one question at a time, instant feedback.
- Parent-friendly: runs fully on your own machine/home network.
- Practical for exam prep: focused revision, mixed exams, adaptive challenge, printable papers.

## Highlights

- Server-rendered UI (Jinja2 + HTMX), no heavy frontend framework.
- FastAPI backend with SQLModel + SQLite.
- Dockerized deployment (`docker compose up`) for reliable local usage.
- Session-based quiz engine with progress tracking:
  - attempted count
  - correct count
  - accuracy %
- Difficulty controls:
  - Any / Easy / Medium / Hard
  - One-click **Exam Boost** (Hard + Mixed all topics)
- Rule-based hints (no LLM) for common mistake patterns.
- Built-in question import pipeline (JSON/CSV) with validation + deduplication.
- Practice and test paper pages with answer keys.

## Curriculum Coverage

Includes broad KS3 + GCSE-support topics, including:

- Number, BIDMAS, negatives, powers/roots
- Fractions, decimals, percentages
- Ratio and proportion
- Algebra expressions/equations/inequalities/sequences
- Coordinates and graphs
- Angles, polygons, perimeter, area, trapezium
- Circles, volume, surface area
- Probability and statistics
- Transformations and Pythagoras
- Plus targeted school exam topic sets

## Tech Stack

- Backend: FastAPI
- Database: SQLite + SQLModel
- Frontend: Jinja2 templates + HTMX
- Container: Docker + Docker Compose

## Quick Start

### Prerequisites

- Docker
- Docker Compose

### Run

```bash
docker compose up --build -d
```

Open:

- App: [http://localhost:8080](http://localhost:8080)
- Health: [http://localhost:8080/health](http://localhost:8080/health)

Stop:

```bash
docker compose down
```

## Screenshots

Home / Revision setup  
![Home](docs/screenshots/Screenshot%202026-03-02%20at%2019.29.51.png)

Quiz experience  
![Quiz 1](docs/screenshots/Screenshot%202026-03-02%20at%2019.38.07.png)

Quiz feedback and progress  
![Quiz 2](docs/screenshots/Screenshot%202026-03-02%20at%2019.39.15.png)

Topic and mode flow  
![Quiz 3](docs/screenshots/Screenshot%202026-03-02%20at%2019.39.40.png)

Papers page  
![Papers](docs/screenshots/Screenshot%202026-03-02%20at%2019.40.20.png)

Paper view and answer key  
![Paper View](docs/screenshots/Screenshot%202026-03-02%20at%2019.40.35.png)

## LAN Access (Home Network)

1. Find your laptop IP:

```bash
ipconfig getifaddr en0
```

2. Open from another device on the same network:

```text
http://<your-laptop-ip>:8080
```

## Quiz Modes

- **Focused Revision**: best for mastering one topic.
- **Exam Mix**: random exam-style questions across selected topics.
- **Adaptive Challenge**: performance-based progression.
- **Exam Boost**: one-click hard mixed practice across all topics.

## Papers

- Papers home: [http://localhost:8080/papers](http://localhost:8080/papers)
- Practice paper: [http://localhost:8080/papers/practice](http://localhost:8080/papers/practice)
- Test paper: [http://localhost:8080/papers/test](http://localhost:8080/papers/test)

## Import Your Own Questions

Supports:

1. JSON in seed format (`topics` + `questions`)
2. CSV columns:
   `topic_key,prompt_text,answer_text,answer_type,difficulty,marks,source,tags`
   Optional: `explanation_hint`

### Run Importer in Container

```bash
docker exec -it year8-maths-api python -m app.tools.import_questions --input /app/app/data/my_questions.json
```

or

```bash
docker exec -it year8-maths-api python -m app.tools.import_questions --input /app/app/data/my_questions.csv
```

### Run Importer Locally

```bash
cd backend
python -m app.tools.import_questions --input app/data/my_questions.json
```

## Project Structure

```text
backend/
  app/
    main.py
    db.py
    models.py
    repository.py
    services/
      quiz_service.py
    tools/
      import_questions.py
    templates/
    static/
    data/
      seed_questions.json
      papers/
        practice_paper.json
        test_paper.json
docker-compose.yml
```

## Safety and Content Note

This project is designed for original or user-owned educational content.
Do not import copyrighted or restricted exam papers.

## License

MIT (see [LICENSE](/Users/Alok_Sharma/Documents/myrepo/year8-maths-ks3-gcse/LICENSE)).
