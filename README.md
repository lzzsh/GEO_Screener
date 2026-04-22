# GEO Screener

A web application for searching, screening, and managing GEO (Gene Expression Omnibus) datasets. Designed to accelerate systematic literature review by combining automated GEO data retrieval with LLM-based inclusion/exclusion screening.

## Features

- **GEO Search** — query NCBI GEO by keyword, GSE/GSM accession, or BioSample ID with pagination and column sorting
- **Screening Tasks** — create batch screening tasks; a Celery worker fetches dataset metadata and runs LLM-based inclusion/exclusion decisions against configurable criteria
- **GSM Annotation** — drill into individual samples within a dataset, annotate availability and metadata fields
- **Paper Calibration** — sync LLM decisions against manually reviewed papers to measure and improve screening accuracy
- **Library** — save datasets to named literature libraries for downstream analysis
- **Export** — download screened results as CSV, using manual decision overrides when available
- **Criteria Management** — define and edit inclusion/exclusion criteria used by the LLM screener

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), SQLite |
| Task Queue | Celery + Redis |
| LLM | OpenAI-compatible API (configurable) |
| Frontend | Jinja2 templates, Alpine.js, Tailwind CSS |
| PDF | pdfplumber |
| Auth | JWT (python-jose + passlib) |

## Getting Started

### Prerequisites

- Python 3.11+
- Redis (for Celery)

### Installation

```bash
git clone https://github.com/lzzsh/GEO_search.git
cd GEO_search
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1   # or any compatible endpoint
OPENAI_MODEL=gpt-4o-mini
```

### Running

Start the FastAPI server:

```bash
uvicorn backend.main:app --reload
```

Start the Celery worker (in a separate terminal):

```bash
celery -A backend.worker.celery_app worker --loglevel=info
```

Open [http://localhost:8000](http://localhost:8000).

## Project Structure

```
backend/
  routers/        # FastAPI route handlers (geo, tasks, annotate, library, llm, criteria, auth)
  worker/         # Celery tasks, GEO fetcher, LLM client, PDF fetcher
  models.py       # SQLAlchemy ORM models
  database.py     # Async DB session setup
  decision_sync.py # Paper calibration sync logic
  label_schema.py # GSM annotation field definitions
frontend/
  templates/      # Jinja2 HTML templates
  static/         # JS / CSS assets
```

## Running Tests

```bash
pytest backend/tests/
```

## Contributing

See [CLAUDE.md](CLAUDE.md) for coding guidelines used in this project.
