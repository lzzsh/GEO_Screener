# GEO Search & Screening Platform — Design Spec

**Date:** 2026-04-14  
**Status:** Approved

---

## Overview

A web platform for searching GEO datasets by keyword and screening them against user-defined inclusion/exclusion criteria using LLM judgment. Designed for small teams (multi-user with accounts), with each user managing their own criteria templates and LLM API configuration.

---

## Architecture

### Stack

- **Backend:** FastAPI + SQLite + Celery (async task queue)
- **Frontend:** HTML + Alpine.js + Tailwind CSS
- **Queue broker:** Redis
- **Auth:** JWT tokens

### System Diagram

```
Browser (Alpine.js + Tailwind)
  └── HTTP ──► FastAPI Backend
                 ├── SQLite (users, criteria, tasks, results, llm_configs)
                 └── Celery Worker (via Redis queue)
                       ├── GEO API / CSV parser
                       └── LLM API (DeepSeek / GLM / MiniMax)
```

### Data Flow

1. User uploads CSV or enters GEO search keywords → selects criteria template → submits task
2. FastAPI creates task record, pushes to Celery queue
3. Worker processes each dataset: fetch/parse → build prompt → call LLM → store result
4. Frontend polls `/tasks/{id}` every 3 seconds for progress and partial results
5. On completion, user can export results as CSV

---

## Database Schema

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE criteria_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    criteria_text TEXT NOT NULL,  -- raw natural language criteria
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE screening_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    template_id INTEGER NOT NULL,
    task_name VARCHAR(255),
    source_type VARCHAR(20),       -- 'csv_upload' or 'geo_search'
    search_query TEXT,             -- GEO search keywords (if geo_search)
    csv_filename VARCHAR(255),     -- uploaded filename (if csv_upload)
    status VARCHAR(20) DEFAULT 'pending',  -- pending/processing/completed/failed
    total_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    passed_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (template_id) REFERENCES criteria_templates(id)
);

CREATE TABLE screening_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    accession VARCHAR(50),
    title TEXT,
    description TEXT,
    organism VARCHAR(100),
    type VARCHAR(100),
    samples INTEGER,
    decision VARCHAR(10),   -- 'pass' or 'fail'
    confidence INTEGER,     -- 0-100
    summary TEXT,           -- one-line judgment reason
    rule_checks JSON,       -- per-criterion check details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES screening_tasks(id)
);

CREATE TABLE llm_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider VARCHAR(50),       -- 'deepseek' / 'glm' / 'minimax' / 'custom'
    api_key VARCHAR(255) NOT NULL,
    model_name VARCHAR(100),
    base_url VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

---

## API Endpoints

```
POST   /auth/register
POST   /auth/login
POST   /auth/logout

GET    /criteria
POST   /criteria
GET    /criteria/{id}
PUT    /criteria/{id}
DELETE /criteria/{id}

POST   /tasks                    # create task (CSV upload or GEO search)
GET    /tasks                    # list user's tasks
GET    /tasks/{id}               # task detail + progress
GET    /tasks/{id}/results       # paginated results
GET    /tasks/{id}/export        # download CSV

GET    /llm/config
PUT    /llm/config
POST   /llm/test

GET    /geo/search?q=...         # preview GEO search results (no screening)
```

---

## LLM Integration

All three providers (DeepSeek, GLM, MiniMax) are compatible with the OpenAI API format. A single `LLMClient` class handles all providers by switching `base_url` and `api_key`:

```python
class LLMClient:
    def __init__(self, provider, api_key, model_name, base_url=None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model_name

    async def screen(self, prompt: str) -> dict:
        # returns standardized JSON screening result
        ...
```

**Provider base URLs:**
- DeepSeek: `https://api.deepseek.com`
- GLM: `https://open.bigmodel.cn/api/paas/v4`
- MiniMax: `https://api.minimax.chat/v1`

### Prompt Template

The user's raw criteria text is injected directly — no parsing, no transformation:

```
你是一个生物信息学专家，请判断以下 GEO 数据集是否符合纳入标准。

【纳入标准】
{criteria_text}

【数据集信息】
Accession: {accession}
Title: {title}
Description: {description}
Organism: {organism}
Type: {type}
Samples: {samples}

【输出要求】
以 JSON 格式返回，字段包括：
- decision: "pass" 或 "fail"
- confidence: 0-100
- summary: 一句话总结判定理由
- rule_checks: 针对标准中每个要点的逐条判定，每条包含 status 和 reason
```

---

## Frontend Pages

| Route | Description |
|---|---|
| `/login` | Login / register |
| `/tasks` | Task list (default landing after login) |
| `/tasks/new` | Create new task |
| `/tasks/{id}` | Task detail: progress + results table |
| `/criteria` | Criteria template management |
| `/settings` | LLM API configuration |

### Key Interactions

**`/tasks/new`**
- Tab switch: "Upload CSV" (drag & drop, preview 5 rows) vs "GEO Search" (keyword input, preview result count)
- Dropdown to select criteria template (with link to create new)
- Submit → redirect to task detail page

**`/tasks/{id}`**
- Progress bar + counters (total / processed / pass / fail)
- Results table: Accession | Title | Decision | Confidence | Summary | Expand
- Expandable rows: per-criterion check details
- Filter by pass/fail
- Export CSV button

**`/criteria`**
- Left panel: template list
- Right panel: name input + large textarea for natural language criteria
- Save / Delete buttons

**`/settings`**
- Provider dropdown (DeepSeek / GLM / MiniMax / Custom)
- API Key, Model Name, Base URL fields
- "Test Connection" button

### Polling

While a task is processing, the frontend polls `/tasks/{id}` every 3 seconds to update progress and append new results. Polling stops when `status` is `completed` or `failed`.

---

## Project Structure

```
GEO_search/
├── backend/
│   ├── main.py                  # FastAPI app entry
│   ├── database.py              # SQLite connection + table init
│   ├── models.py                # SQLAlchemy models
│   ├── auth.py                  # JWT auth
│   ├── routers/
│   │   ├── criteria.py
│   │   ├── tasks.py
│   │   ├── llm.py
│   │   └── geo.py
│   ├── worker/
│   │   ├── celery_app.py        # Celery config
│   │   ├── tasks.py             # screening task logic
│   │   ├── llm_client.py        # unified LLM client
│   │   ├── geo_fetcher.py       # NCBI GEO API wrapper
│   │   └── csv_parser.py        # CSV upload parser
│   └── requirements.txt
├── frontend/
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── tasks.html
│   │   ├── tasks_new.html
│   │   ├── tasks_detail.html
│   │   ├── criteria.html
│   │   └── settings.html
│   └── static/
│       └── app.js               # Alpine.js components
├── docker-compose.yml
└── docs/
    └── superpowers/specs/
        └── 2026-04-14-geo-search-design.md
```

---

## Error Handling

- LLM API failure on a single dataset: mark result as `error`, continue processing remaining datasets, report error count in task summary
- GEO API rate limit: exponential backoff with max 3 retries
- CSV parse error: reject upload with clear error message listing problematic rows
- Invalid LLM JSON response: retry once with stricter prompt; if still invalid, mark as `error`
