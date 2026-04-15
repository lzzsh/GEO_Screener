# GEO Search & Screening Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web platform for searching GEO datasets and screening them with configurable LLM-based criteria.

**Architecture:** FastAPI backend with SQLite + Celery/Redis for async task processing. Alpine.js + Tailwind frontend served via Jinja2 templates. All LLM providers unified through OpenAI-compatible client.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Celery, Redis, openai SDK, Alpine.js, Tailwind CSS, Jinja2

---

### Task 1: Project Scaffold + requirements.txt + docker-compose.yml

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `backend/__init__.py`
- Create: `backend/routers/__init__.py`
- Create: `backend/worker/__init__.py`
- Create: `frontend/static/app.js`

- [ ] Step 1: Create directory structure:
  ```bash
  mkdir -p backend/routers backend/worker backend/tests frontend/templates frontend/static
  touch backend/__init__.py backend/routers/__init__.py backend/worker/__init__.py backend/tests/__init__.py
  ```

- [ ] Step 2: Write `backend/requirements.txt`:
  ```
  fastapi==0.111.0
  uvicorn[standard]==0.29.0
  sqlalchemy==2.0.30
  aiosqlite==0.20.0
  python-jose[cryptography]==3.3.0
  passlib[bcrypt]==1.7.4
  python-multipart==0.0.9
  celery==5.4.0
  redis==5.0.4
  openai==1.30.1
  httpx==0.27.0
  jinja2==3.1.4
  aiofiles==23.2.1
  pydantic-settings==2.2.1
  pytest==8.2.0
  pytest-asyncio==0.23.6
  anyio==4.3.0
  email-validator==2.1.1
  ```

- [ ] Step 3: Write `backend/Dockerfile`:
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  ```

- [ ] Step 4: Write `docker-compose.yml`:
  ```yaml
  version: "3.9"
  services:
    redis:
      image: redis:7-alpine
      ports:
        - "6379:6379"
    backend:
      build: ./backend
      command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
      volumes:
        - ./backend:/app
        - ./frontend:/frontend
      ports:
        - "8000:8000"
      environment:
        - REDIS_URL=redis://redis:6379/0
        - DATABASE_URL=sqlite+aiosqlite:///./geo_search.db
        - SECRET_KEY=change-me-in-production
      depends_on:
        - redis
    worker:
      build: ./backend
      command: celery -A worker.celery_app worker --loglevel=info -c 2
      volumes:
        - ./backend:/app
      environment:
        - REDIS_URL=redis://redis:6379/0
        - DATABASE_URL=sqlite+aiosqlite:///./geo_search.db
        - SECRET_KEY=change-me-in-production
      depends_on:
        - redis
  ```

- [ ] Step 5: Create `frontend/static/app.js` placeholder:
  ```javascript
  // Populated in Task 12
  ```

- [ ] Step 6: Commit:
  ```bash
  git init && git add -A && git commit -m "chore: project scaffold, requirements, docker-compose"
  ```

---

### Task 2: Database Setup (database.py + models.py)

**Files:**
- Create: `backend/database.py`
- Create: `backend/models.py`
- Create: `backend/tests/test_models.py`

- [ ] Step 1: Write `backend/database.py`:
  ```python
  import os
  from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
  from sqlalchemy.orm import DeclarativeBase

  DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./geo_search.db")

  engine = create_async_engine(DATABASE_URL, echo=False)
  AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

  class Base(DeclarativeBase):
      pass

  async def get_db() -> AsyncSession:
      async with AsyncSessionLocal() as session:
          yield session

  async def init_db():
      async with engine.begin() as conn:
          import backend.models  # noqa: F401
          await conn.run_sync(Base.metadata.create_all)
  ```

- [ ] Step 2: Write `backend/models.py`:
  ```python
  from datetime import datetime
  from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey
  from sqlalchemy.orm import Mapped, mapped_column, relationship
  from backend.database import Base

  class User(Base):
      __tablename__ = "users"
      id: Mapped[int] = mapped_column(Integer, primary_key=True)
      username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
      email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
      hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
      created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
      tasks: Mapped[list["ScreeningTask"]] = relationship(back_populates="owner")

  class CriteriaTemplate(Base):
      __tablename__ = "criteria_templates"
      id: Mapped[int] = mapped_column(Integer, primary_key=True)
      name: Mapped[str] = mapped_column(String(128), nullable=False)
      criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
      owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
      created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
      updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

  class ScreeningTask(Base):
      __tablename__ = "screening_tasks"
      id: Mapped[int] = mapped_column(Integer, primary_key=True)
      name: Mapped[str] = mapped_column(String(256), nullable=False)
      source: Mapped[str] = mapped_column(String(16), nullable=False)  # csv | geo
      status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|done|error
      total: Mapped[int] = mapped_column(Integer, default=0)
      processed: Mapped[int] = mapped_column(Integer, default=0)
      criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
      owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
      created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
      owner: Mapped["User"] = relationship(back_populates="tasks")
      results: Mapped[list["ScreeningResult"]] = relationship(back_populates="task")

  class ScreeningResult(Base):
      __tablename__ = "screening_results"
      id: Mapped[int] = mapped_column(Integer, primary_key=True)
      task_id: Mapped[int] = mapped_column(ForeignKey("screening_tasks.id"), nullable=False)
      dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
      title: Mapped[str] = mapped_column(String(512), nullable=True)
      decision: Mapped[str] = mapped_column(String(16), nullable=True)  # include|exclude|uncertain
      confidence: Mapped[float] = mapped_column(Float, nullable=True)
      summary: Mapped[str] = mapped_column(Text, nullable=True)
      rule_checks: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
      status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|error
      error_msg: Mapped[str] = mapped_column(Text, nullable=True)
      task: Mapped["ScreeningTask"] = relationship(back_populates="results")

  class LLMConfig(Base):
      __tablename__ = "llm_configs"
      id: Mapped[int] = mapped_column(Integer, primary_key=True)
      owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
      provider: Mapped[str] = mapped_column(String(32), default="deepseek")
      base_url: Mapped[str] = mapped_column(String(256), nullable=True)
      api_key: Mapped[str] = mapped_column(String(256), nullable=True)
      model: Mapped[str] = mapped_column(String(128), default="deepseek-chat")
      temperature: Mapped[float] = mapped_column(Float, default=0.1)
  ```

- [ ] Step 3: Write `backend/tests/test_models.py`:
  ```python
  import pytest
  from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
  from backend.database import Base
  from backend import models

  @pytest.fixture
  async def db():
      engine = create_async_engine("sqlite+aiosqlite:///:memory:")
      async with engine.begin() as conn:
          await conn.run_sync(Base.metadata.create_all)
      factory = async_sessionmaker(engine, expire_on_commit=False)
      async with factory() as session:
          yield session
      await engine.dispose()

  @pytest.mark.asyncio
  async def test_create_user(db):
      user = models.User(username="alice", email="alice@example.com", hashed_password="hash")
      db.add(user)
      await db.commit()
      await db.refresh(user)
      assert user.id is not None

  @pytest.mark.asyncio
  async def test_all_tables_created(db):
      for table in ["users", "criteria_templates", "screening_tasks", "screening_results", "llm_configs"]:
          assert table in Base.metadata.tables
  ```

- [ ] Step 4: Run tests:
  ```bash
  cd backend && pytest tests/test_models.py -v
  ```

- [ ] Step 5: Commit:
  ```bash
  git add -A && git commit -m "feat: SQLAlchemy 2.0 models for all 5 tables"
  ```

---

### Task 3: Auth System (auth.py + routers/auth.py)

**Files:**
- Create: `backend/auth.py`
- Create: `backend/routers/auth.py`
- Create: `backend/tests/test_auth.py`

- [ ] Step 1: Write `backend/auth.py`:
  ```python
  import os
  from datetime import datetime, timedelta
  from typing import Optional
  from jose import JWTError, jwt
  from passlib.context import CryptContext
  from fastapi import Depends, HTTPException, status, Cookie
```

---

## 2026-04-14 Plan Update: GEO Candidate Workflow Revision

**Goal:** Change GEO tasks from "manually select GEO IDs then screen datasets" to "search GEO by literature keywords, persist all GEO candidates, and optionally screen candidate descriptions with natural-language criteria while preserving pre/post-screening visibility."

**Architecture:** Keep the existing FastAPI + Celery task flow, but create GEO tasks from `search_query` instead of selected IDs. Persist every GEO search hit as a `ScreeningResult`, then use the worker to apply optional natural-language screening against each candidate's `title + description/summary`. Update the task detail page to show candidate counts and post-screening counts together.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Celery, httpx, Alpine.js, Jinja2, Tailwind CSS

### Task 16: Revise GEO Task Semantics

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/routers/tasks.py`
- Modify: `backend/worker/tasks.py`
- Modify: `backend/worker/geo_fetcher.py`
- Modify: `backend/tests/test_tasks_router.py`
- Modify: `backend/tests/test_e2e_smoke.py`

- [ ] Step 1: Write failing tests for `search_query`-driven task creation, candidate persistence, and optional screening skip behavior.
- [ ] Step 2: Update task/result models to store `search_query`, candidate counts, per-result descriptions, and screening counters.
- [ ] Step 3: Change task creation so GEO tasks search GEO immediately from the query and persist every returned candidate record.
- [ ] Step 4: Change worker screening so it evaluates candidate `title + description` and updates include/exclude/uncertain counters.
- [ ] Step 5: Run `PYTHONPATH=. conda run -n autofigure pytest -q backend/tests/test_tasks_router.py backend/tests/test_e2e_smoke.py` and commit.

### Task 17: Update Task UI for Pre/Post Screening Visibility

**Files:**
- Modify: `frontend/templates/tasks_new.html`
- Modify: `frontend/templates/tasks_detail.html`
- Modify: `backend/tests/test_pages.py`

- [ ] Step 1: Write failing tests or assertions for the new page routes/data expectations where practical.
- [ ] Step 2: Replace manual GEO checkbox selection with keyword search preview plus optional natural-language criteria entry.
- [ ] Step 3: Update task detail to show candidate count, included/excluded/uncertain counters, and decision-based filtering while keeping all candidates visible.
- [ ] Step 4: Run `PYTHONPATH=. conda run -n autofigure pytest -q` and commit.
  from fastapi.security import OAuth2PasswordBearer
  from sqlalchemy.ext.asyncio import AsyncSession
  from sqlalchemy import select
  from backend.database import get_db
  from backend.models import User

  SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
  ALGORITHM = "HS256"
  ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

  pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
  oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

  def hash_password(password: str) -> str:
      return pwd_context.hash(password)

  def verify_password(plain: str, hashed: str) -> bool:
      return pwd_context.verify(plain, hashed)

  def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
      to_encode = data.copy()
      expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
      to_encode["exp"] = expire
      return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

  async def get_current_user(
      token: Optional[str] = Depends(oauth2_scheme),
      access_token: Optional[str] = Cookie(default=None),
      db: AsyncSession = Depends(get_db),
  ) -> User:
      tok = token or access_token
      if not tok:
          raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
      try:
          payload = jwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
          user_id: int = int(payload["sub"])
      except (JWTError, TypeError, ValueError, KeyError):
          raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
      result = await db.execute(select(User).where(User.id == user_id))
      user = result.scalar_one_or_none()
      if user is None:
          raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
      return user
  ```

- [ ] Step 2: Write `backend/routers/auth.py`:
  ```python
  from fastapi import APIRouter, Depends, HTTPException, Response
  from sqlalchemy.ext.asyncio import AsyncSession
  from sqlalchemy import select
  from pydantic import BaseModel, EmailStr
  from backend.database import get_db
  from backend.models import User
  from backend.auth import hash_password, verify_password, create_access_token

  router = APIRouter(prefix="/auth", tags=["auth"])

  class RegisterRequest(BaseModel):
      username: str
      email: EmailStr
      password: str

  class LoginRequest(BaseModel):
      username: str
      password: str

  @router.post("/register", status_code=201)
  async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
      existing = await db.execute(select(User).where(User.username == req.username))
      if existing.scalar_one_or_none():
          raise HTTPException(status_code=400, detail="Username already taken")
      user = User(username=req.username, email=req.email, hashed_password=hash_password(req.password))
      db.add(user)
      await db.commit()
      await db.refresh(user)
      return {"id": user.id, "username": user.username}

  @router.post("/login")
  async def login(req: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
      result = await db.execute(select(User).where(User.username == req.username))
      user = result.scalar_one_or_none()
      if not user or not verify_password(req.password, user.hashed_password):
          raise HTTPException(status_code=401, detail="Invalid credentials")
      token = create_access_token({"sub": str(user.id)})
      response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=86400)
      return {"access_token": token, "token_type": "bearer"}

  @router.post("/logout")
  async def logout(response: Response):
      response.delete_cookie("access_token")
      return {"message": "Logged out"}
  ```

- [ ] Step 3: Write `backend/tests/test_auth.py`:
  ```python
  import pytest
  from httpx import AsyncClient, ASGITransport

  @pytest.mark.asyncio
  async def test_register_and_login():
      from backend.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          r = await client.post("/auth/register", json={"username": "bob", "email": "bob@test.com", "password": "secret"})
          assert r.status_code == 201
          r2 = await client.post("/auth/login", json={"username": "bob", "password": "secret"})
          assert r2.status_code == 200
          assert "access_token" in r2.json()

  @pytest.mark.asyncio
  async def test_login_wrong_password():
      from backend.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          await client.post("/auth/register", json={"username": "carol", "email": "carol@test.com", "password": "right"})
          r = await client.post("/auth/login", json={"username": "carol", "password": "wrong"})
          assert r.status_code == 401
  ```

- [ ] Step 4: Create minimal `backend/main.py` stub (will be replaced in Task 11):
  ```python
  from contextlib import asynccontextmanager
  from fastapi import FastAPI
  from backend.database import init_db
  from backend.routers import auth as auth_router

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      await init_db()
      yield

  app = FastAPI(lifespan=lifespan)
  app.include_router(auth_router.router)
  ```

- [ ] Step 5: Run tests:
  ```bash
  cd backend && pytest tests/test_auth.py -v
  ```

- [ ] Step 6: Commit:
  ```bash
  git add -A && git commit -m "feat: JWT auth with register/login/logout"
  ```

---

### Task 4: Criteria CRUD (routers/criteria.py)

**Files:**
- Create: `backend/routers/criteria.py`
- Create: `backend/tests/test_criteria.py`

- [ ] Step 1: Write `backend/routers/criteria.py`:
  ```python
  from typing import Optional
  from fastapi import APIRouter, Depends, HTTPException
  from sqlalchemy.ext.asyncio import AsyncSession
  from sqlalchemy import select
  from pydantic import BaseModel
  from backend.database import get_db
  from backend.models import CriteriaTemplate, User
  from backend.auth import get_current_user

  router = APIRouter(prefix="/criteria", tags=["criteria"])

  class CriteriaCreate(BaseModel):
      name: str
      criteria_text: str

  class CriteriaUpdate(BaseModel):
      name: Optional[str] = None
      criteria_text: Optional[str] = None

  def _serialize(c: CriteriaTemplate) -> dict:
      return {"id": c.id, "name": c.name, "criteria_text": c.criteria_text,
              "created_at": c.created_at, "updated_at": c.updated_at}

  @router.get("")
  async def list_criteria(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      result = await db.execute(select(CriteriaTemplate).where(CriteriaTemplate.owner_id == user.id))
      return [_serialize(c) for c in result.scalars().all()]

  @router.post("", status_code=201)
  async def create_criteria(req: CriteriaCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      c = CriteriaTemplate(name=req.name, criteria_text=req.criteria_text, owner_id=user.id)
      db.add(c)
      await db.commit()
      await db.refresh(c)
      return _serialize(c)

  @router.get("/{criteria_id}")
  async def get_criteria(criteria_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      result = await db.execute(select(CriteriaTemplate).where(
          CriteriaTemplate.id == criteria_id, CriteriaTemplate.owner_id == user.id))
      c = result.scalar_one_or_none()
      if not c:
          raise HTTPException(status_code=404, detail="Not found")
      return _serialize(c)

  @router.put("/{criteria_id}")
  async def update_criteria(criteria_id: int, req: CriteriaUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      result = await db.execute(select(CriteriaTemplate).where(
          CriteriaTemplate.id == criteria_id, CriteriaTemplate.owner_id == user.id))
      c = result.scalar_one_or_none()
      if not c:
          raise HTTPException(status_code=404, detail="Not found")
      if req.name is not None:
          c.name = req.name
      if req.criteria_text is not None:
          c.criteria_text = req.criteria_text
      await db.commit()
      await db.refresh(c)
      return _serialize(c)

  @router.delete("/{criteria_id}", status_code=204)
  async def delete_criteria(criteria_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      result = await db.execute(select(CriteriaTemplate).where(
          CriteriaTemplate.id == criteria_id, CriteriaTemplate.owner_id == user.id))
      c = result.scalar_one_or_none()
      if not c:
          raise HTTPException(status_code=404, detail="Not found")
      await db.delete(c)
      await db.commit()
  ```

- [ ] Step 2: Write `backend/tests/test_criteria.py`:
  ```python
  import pytest
  from httpx import AsyncClient, ASGITransport

  @pytest.fixture
  async def auth_client():
      from backend.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          await client.post("/auth/register", json={"username": "u1", "email": "u1@test.com", "password": "pw"})
          r = await client.post("/auth/login", json={"username": "u1", "password": "pw"})
          token = r.json()["access_token"]
          client.headers["Authorization"] = f"Bearer {token}"
          yield client

  @pytest.mark.asyncio
  async def test_criteria_crud(auth_client):
      r = await auth_client.post("/criteria", json={"name": "RCT only", "criteria_text": "Must be RCT"})
      assert r.status_code == 201
      cid = r.json()["id"]
      r2 = await auth_client.get(f"/criteria/{cid}")
      assert r2.json()["name"] == "RCT only"
      r3 = await auth_client.put(f"/criteria/{cid}", json={"name": "Updated"})
      assert r3.json()["name"] == "Updated"
      r4 = await auth_client.delete(f"/criteria/{cid}")
      assert r4.status_code == 204
  ```

- [ ] Step 3: Add criteria router to `backend/main.py` stub:
  ```python
  from backend.routers import criteria as criteria_router
  app.include_router(criteria_router.router)
  ```

- [ ] Step 4: Run tests:
  ```bash
  cd backend && pytest tests/test_criteria.py -v
  ```

- [ ] Step 5: Commit:
  ```bash
  git add -A && git commit -m "feat: criteria template CRUD endpoints"
  ```

---

### Task 5: LLM Client (worker/llm_client.py)

**Files:**
- Create: `backend/worker/llm_client.py`
- Create: `backend/tests/test_llm_client.py`

- [ ] Step 1: Write `backend/worker/llm_client.py`:
  ```python
  import json
  import re
  from typing import Optional
  from openai import AsyncOpenAI

  PROVIDER_DEFAULTS: dict[str, dict] = {
      "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
      "glm":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4"},
      "minimax":  {"base_url": "https://api.minimax.chat/v1", "model": "abab6.5s-chat"},
  }

  SCREENING_PROMPT_TEMPLATE = """\
  You are a systematic review screener. Evaluate the following dataset against the criteria.

  ## Screening Criteria
  {criteria_text}

  ## Dataset Information
  ID: {dataset_id}
  Title: {title}
  Description: {description}

  ## Instructions
  Return ONLY valid JSON with this exact structure:
  {{
    "decision": "include" | "exclude" | "uncertain",
    "confidence": 0.0-1.0,
    "summary": "one sentence rationale",
    "rule_checks": {{"criterion_key": true|false}}
  }}
  """

  class LLMClient:
      def __init__(self, provider: str, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.1):
          defaults = PROVIDER_DEFAULTS.get(provider, {})
          self.model = model or defaults.get("model", "gpt-3.5-turbo")
          self.temperature = temperature
          self._client = AsyncOpenAI(
              api_key=api_key,
              base_url=base_url or defaults.get("base_url"),
          )

      async def screen_dataset(self, dataset_id: str, title: str, description: str, criteria_text: str) -> dict:
          prompt = SCREENING_PROMPT_TEMPLATE.format(
              criteria_text=criteria_text,
              dataset_id=dataset_id,
              title=title,
              description=description,
          )
          response = await self._client.chat.completions.create(
              model=self.model,
              temperature=self.temperature,
              messages=[{"role": "user", "content": prompt}],
          )
          raw = response.choices[0].message.content.strip()
          return self._parse_json(raw)

      def _parse_json(self, raw: str) -> dict:
          # Strip markdown code fences if present
          match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
          text = match.group(1) if match else raw
          return json.loads(text)

      async def test_connection(self) -> bool:
          response = await self._client.chat.completions.create(
              model=self.model,
              temperature=0,
              messages=[{"role": "user", "content": "Reply with the single word: ok"}],
              max_tokens=5,
          )
          return bool(response.choices[0].message.content)
  ```

- [ ] Step 2: Write `backend/tests/test_llm_client.py`:
  ```python
  import pytest
  import json
  from unittest.mock import AsyncMock, MagicMock, patch
  from backend.worker.llm_client import LLMClient

  @pytest.mark.asyncio
  async def test_parse_clean_json():
      client = LLMClient(provider="deepseek", api_key="fake")
      result = client._parse_json('{"decision":"include","confidence":0.9,"summary":"ok","rule_checks":{}}')
      assert result["decision"] == "include"

  @pytest.mark.asyncio
  async def test_parse_fenced_json():
      client = LLMClient(provider="deepseek", api_key="fake")
      raw = '```json\n{"decision":"exclude","confidence":0.8,"summary":"no","rule_checks":{}}\n```'
      result = client._parse_json(raw)
      assert result["decision"] == "exclude"

  @pytest.mark.asyncio
  async def test_screen_dataset_calls_api():
      client = LLMClient(provider="deepseek", api_key="fake")
      mock_resp = MagicMock()
      mock_resp.choices[0].message.content = '{"decision":"include","confidence":0.95,"summary":"fits","rule_checks":{}}'
      with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)):
          result = await client.screen_dataset("GSE001", "Test", "A study", "Must be human")
      assert result["decision"] == "include"
  ```

- [ ] Step 3: Run tests:
  ```bash
  cd backend && pytest tests/test_llm_client.py -v
  ```

- [ ] Step 4: Commit:
  ```bash
  git add -A && git commit -m "feat: unified LLM client for DeepSeek/GLM/MiniMax/custom"
  ```

---

### Task 6: LLM Config API (routers/llm.py)

**Files:**
- Create: `backend/routers/llm.py`
- Create: `backend/tests/test_llm_router.py`

- [ ] Step 1: Write `backend/routers/llm.py`:
  ```python
  from typing import Optional
  from fastapi import APIRouter, Depends, HTTPException
  from sqlalchemy.ext.asyncio import AsyncSession
  from sqlalchemy import select
  from pydantic import BaseModel
  from backend.database import get_db
  from backend.models import LLMConfig, User
  from backend.auth import get_current_user

  router = APIRouter(prefix="/llm", tags=["llm"])

  class LLMConfigUpdate(BaseModel):
      provider: Optional[str] = None
      base_url: Optional[str] = None
      api_key: Optional[str] = None
      model: Optional[str] = None
      temperature: Optional[float] = None

  def _serialize(c: LLMConfig) -> dict:
      return {"provider": c.provider, "base_url": c.base_url,
              "api_key": "***" if c.api_key else None,
              "model": c.model, "temperature": c.temperature}

  async def _get_or_create_config(user: User, db: AsyncSession) -> LLMConfig:
      result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == user.id))
      cfg = result.scalar_one_or_none()
      if not cfg:
          cfg = LLMConfig(owner_id=user.id)
          db.add(cfg)
          await db.commit()
          await db.refresh(cfg)
      return cfg

  @router.get("/config")
  async def get_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      cfg = await _get_or_create_config(user, db)
      return _serialize(cfg)

  @router.put("/config")
  async def update_config(req: LLMConfigUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      cfg = await _get_or_create_config(user, db)
      for field, value in req.model_dump(exclude_none=True).items():
          setattr(cfg, field, value)
      await db.commit()
      await db.refresh(cfg)
      return _serialize(cfg)

  @router.post("/test")
  async def test_connection(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      cfg = await _get_or_create_config(user, db)
      if not cfg.api_key:
          raise HTTPException(status_code=400, detail="API key not configured")
      from backend.worker.llm_client import LLMClient
      client = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                         base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature)
      try:
          ok = await client.test_connection()
          return {"success": ok}
      except Exception as e:
          raise HTTPException(status_code=502, detail=str(e))
  ```

- [ ] Step 2: Write `backend/tests/test_llm_router.py`:
  ```python
  import pytest
  from httpx import AsyncClient, ASGITransport
  from unittest.mock import AsyncMock, patch

  @pytest.fixture
  async def auth_client():
      from backend.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          await client.post("/auth/register", json={"username": "llmuser", "email": "llm@test.com", "password": "pw"})
          r = await client.post("/auth/login", json={"username": "llmuser", "password": "pw"})
          client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
          yield client

  @pytest.mark.asyncio
  async def test_get_and_update_config(auth_client):
      r = await auth_client.get("/llm/config")
      assert r.status_code == 200
      r2 = await auth_client.put("/llm/config", json={"provider": "glm", "model": "glm-4", "api_key": "sk-test"})
      assert r2.json()["provider"] == "glm"
      assert r2.json()["api_key"] == "***"
  ```

- [ ] Step 3: Add llm router to `backend/main.py` stub:
  ```python
  from backend.routers import llm as llm_router
  app.include_router(llm_router.router)
  ```

- [ ] Step 4: Run tests:
  ```bash
  cd backend && pytest tests/test_llm_router.py -v
  ```

- [ ] Step 5: Commit:
  ```bash
  git add -A && git commit -m "feat: LLM config get/update/test endpoints"
  ```

---

### Task 7: GEO Fetcher (worker/geo_fetcher.py)

**Files:**
- Create: `backend/worker/geo_fetcher.py`
- Create: `backend/tests/test_geo_fetcher.py`

- [ ] Step 1: Write `backend/worker/geo_fetcher.py`:
  ```python
  import asyncio
  import httpx
  from typing import Optional
  from xml.etree import ElementTree as ET

  NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
  MAX_RETRIES = 3

  async def search_geo(query: str, retmax: int = 20) -> list[dict]:
      """Search GEO datasets via NCBI eutils. Returns list of {id, title, summary}."""
      ids = await _esearch(query, retmax)
      if not ids:
          return []
      return await _efetch_summaries(ids)

  async def _esearch(query: str, retmax: int) -> list[str]:
      url = f"{NCBI_BASE}/esearch.fcgi"
      params = {"db": "gds", "term": query, "retmax": retmax, "retmode": "json"}
      async with httpx.AsyncClient(timeout=30) as client:
          for attempt in range(MAX_RETRIES):
              try:
                  r = await client.get(url, params=params)
                  r.raise_for_status()
                  return r.json()["esearchresult"]["idlist"]
              except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                  if attempt == MAX_RETRIES - 1:
                      raise
                  await asyncio.sleep(2 ** attempt)
      return []

  async def _efetch_summaries(ids: list[str]) -> list[dict]:
      url = f"{NCBI_BASE}/esummary.fcgi"
      params = {"db": "gds", "id": ",".join(ids), "retmode": "json"}
      async with httpx.AsyncClient(timeout=30) as client:
          for attempt in range(MAX_RETRIES):
              try:
                  r = await client.get(url, params=params)
                  r.raise_for_status()
                  data = r.json()
                  results = []
                  for uid in ids:
                      doc = data.get("result", {}).get(uid, {})
                      results.append({
                          "id": doc.get("accession", uid),
                          "title": doc.get("title", ""),
                          "summary": doc.get("summary", ""),
                          "organism": doc.get("taxon", ""),
                          "n_samples": doc.get("n_samples", 0),
                      })
                  return results
              except (httpx.HTTPStatusError, httpx.TimeoutException):
                  if attempt == MAX_RETRIES - 1:
                      raise
                  await asyncio.sleep(2 ** attempt)
  return []
  ```

- [ ] Step 2: Write `backend/tests/test_geo_fetcher.py`:
  ```python
  import pytest
  from unittest.mock import AsyncMock, patch, MagicMock
  from backend.worker.geo_fetcher import search_geo, _esearch

  @pytest.mark.asyncio
  async def test_search_geo_returns_list():
      mock_search = AsyncMock(return_value=["200012345"])
      mock_fetch = AsyncMock(return_value=[{"id": "GSE12345", "title": "Test", "summary": "A study", "organism": "Homo sapiens", "n_samples": 10}])
      with patch("backend.worker.geo_fetcher._esearch", mock_search), \
           patch("backend.worker.geo_fetcher._efetch_summaries", mock_fetch):
          results = await search_geo("cancer RNA-seq")
      assert len(results) == 1
      assert results[0]["id"] == "GSE12345"

  @pytest.mark.asyncio
  async def test_search_geo_empty_query():
      mock_search = AsyncMock(return_value=[])
      with patch("backend.worker.geo_fetcher._esearch", mock_search):
          results = await search_geo("xyznonexistent12345")
      assert results == []
  ```

- [ ] Step 3: Run tests:
  ```bash
  cd backend && pytest tests/test_geo_fetcher.py -v
  ```

- [ ] Step 4: Commit:
  ```bash
  git add -A && git commit -m "feat: NCBI GEO fetcher with exponential backoff retry"
  ```

---

### Task 8: CSV Parser (worker/csv_parser.py)

**Files:**
- Create: `backend/worker/csv_parser.py`
- Create: `backend/tests/test_csv_parser.py`

- [ ] Step 1: Write `backend/worker/csv_parser.py`:
  ```python
  import csv
  import io
  from typing import Optional

  # Expected columns from general.csv format (flexible — uses first matching alias)
  COLUMN_ALIASES = {
      "id":          ["GSE", "gse", "accession", "id", "dataset_id"],
      "title":       ["title", "Title", "study_title"],
      "description": ["summary", "Summary", "description", "abstract"],
  }

  def _find_col(headers: list[str], aliases: list[str]) -> Optional[str]:
      for alias in aliases:
          if alias in headers:
              return alias
      return None

  def parse_csv(content: bytes) -> list[dict]:
      """Parse CSV bytes into list of {id, title, description} dicts."""
      text = content.decode("utf-8-sig")  # handle BOM
      reader = csv.DictReader(io.StringIO(text))
      headers = reader.fieldnames or []

      id_col = _find_col(headers, COLUMN_ALIASES["id"])
      title_col = _find_col(headers, COLUMN_ALIASES["title"])
      desc_col = _find_col(headers, COLUMN_ALIASES["description"])

      if not id_col:
          raise ValueError(f"CSV missing ID column. Found columns: {headers}")

      results = []
      for row in reader:
          dataset_id = row.get(id_col, "").strip()
          if not dataset_id:
              continue
          results.append({
              "id": dataset_id,
              "title": row.get(title_col, "").strip() if title_col else "",
              "description": row.get(desc_col, "").strip() if desc_col else "",
          })
      return results
  ```

- [ ] Step 2: Write `backend/tests/test_csv_parser.py`:
  ```python
  import pytest
  from backend.worker.csv_parser import parse_csv

  def test_parse_standard_csv():
      content = b"GSE,title,summary\nGSE001,Study A,A human study\nGSE002,Study B,A mouse study\n"
      rows = parse_csv(content)
      assert len(rows) == 2
      assert rows[0]["id"] == "GSE001"
      assert rows[0]["title"] == "Study A"
      assert rows[0]["description"] == "A human study"

  def test_parse_bom_csv():
      content = "\ufeffGSE,title,summary\nGSE003,Study C,desc\n".encode("utf-8-sig")
      rows = parse_csv(content)
      assert rows[0]["id"] == "GSE003"

  def test_parse_missing_id_column():
      content = b"name,description\nfoo,bar\n"
      with pytest.raises(ValueError, match="missing ID column"):
          parse_csv(content)

  def test_parse_skips_empty_ids():
      content = b"GSE,title\nGSE001,A\n,B\nGSE002,C\n"
      rows = parse_csv(content)
      assert len(rows) == 2
  ```

- [ ] Step 3: Run tests:
  ```bash
  cd backend && pytest tests/test_csv_parser.py -v
  ```

- [ ] Step 4: Commit:
  ```bash
  git add -A && git commit -m "feat: CSV parser for general.csv format with flexible column aliases"
  ```

---

### Task 9: Celery Worker + Screening Pipeline (worker/celery_app.py + worker/tasks.py)

**Files:**
- Create: `backend/worker/celery_app.py`
- Create: `backend/worker/tasks.py`

- [ ] Step 1: Write `backend/worker/celery_app.py`:
  ```python
  import os
  from celery import Celery

  REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

  celery_app = Celery(
      "geo_search",
      broker=REDIS_URL,
      backend=REDIS_URL,
      include=["worker.tasks"],
  )
  celery_app.conf.update(
      task_serializer="json",
      result_serializer="json",
      accept_content=["json"],
      timezone="UTC",
      enable_utc=True,
      task_track_started=True,
  )
  ```

- [ ] Step 2: Write `backend/worker/tasks.py`:
  ```python
  import asyncio
  import json
  import logging
  from sqlalchemy import select, update
  from backend.worker.celery_app import celery_app
  from backend.database import AsyncSessionLocal
  from backend.models import ScreeningTask, ScreeningResult, LLMConfig
  from backend.worker.llm_client import LLMClient

  logger = logging.getLogger(__name__)

  def _run(coro):
      return asyncio.get_event_loop().run_until_complete(coro)

  @celery_app.task(bind=True, name="worker.tasks.run_screening")
  def run_screening(self, task_id: int):
      _run(_run_screening_async(task_id))

  async def _run_screening_async(task_id: int):
      async with AsyncSessionLocal() as db:
          result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))
          task = result.scalar_one_or_none()
          if not task:
              return

          # Mark running
          task.status = "running"
          await db.commit()

          # Load LLM config for task owner
          cfg_result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id))
          cfg = cfg_result.scalar_one_or_none()
          if not cfg or not cfg.api_key:
              task.status = "error"
              await db.commit()
              return

          llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                          base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature)

          # Load pending results
          res_result = await db.execute(
              select(ScreeningResult).where(ScreeningResult.task_id == task_id, ScreeningResult.status == "pending"))
          pending = res_result.scalars().all()

          for sr in pending:
              await _screen_one(db, task, sr, llm)

          task.status = "done"
          await db.commit()

  async def _screen_one(db, task: ScreeningTask, sr: ScreeningResult, llm: LLMClient):
      try:
          result = await llm.screen_dataset(
              dataset_id=sr.dataset_id,
              title=sr.title or "",
              description="",
              criteria_text=task.criteria_text,
          )
          sr.decision = result.get("decision")
          sr.confidence = result.get("confidence")
          sr.summary = result.get("summary")
          sr.rule_checks = json.dumps(result.get("rule_checks", {}))
          sr.status = "done"
      except json.JSONDecodeError:
          # Retry once with stricter prompt by appending reminder
          try:
              from backend.worker.llm_client import SCREENING_PROMPT_TEMPLATE
              result = await llm.screen_dataset(
                  dataset_id=sr.dataset_id, title=sr.title or "", description="",
                  criteria_text=task.criteria_text + "\n\nIMPORTANT: Return ONLY raw JSON, no markdown.",
              )
              sr.decision = result.get("decision")
              sr.confidence = result.get("confidence")
              sr.summary = result.get("summary")
              sr.rule_checks = json.dumps(result.get("rule_checks", {}))
              sr.status = "done"
          except Exception as e:
              sr.status = "error"
              sr.error_msg = str(e)
      except Exception as e:
          sr.status = "error"
          sr.error_msg = str(e)
          logger.warning("LLM error for %s: %s", sr.dataset_id, e)
      finally:
          task.processed += 1
          await db.commit()
  ```

- [ ] Step 3: Verify Celery can discover the task (no live broker needed):
  ```bash
  cd backend && python -c "from worker.tasks import run_screening; print(run_screening.name)"
  # Expected: worker.tasks.run_screening
  ```

- [ ] Step 4: Commit:
  ```bash
  git add -A && git commit -m "feat: Celery screening pipeline with LLM error handling and JSON retry"
  ```

---

### Task 10: Tasks API (routers/tasks.py)

**Files:**
- Create: `backend/routers/tasks.py`
- Create: `backend/tests/test_tasks_router.py`

- [ ] Step 1: Write `backend/routers/tasks.py`:
  ```python
  import csv
  import io
  import json
  from typing import Optional
  from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
  from fastapi.responses import StreamingResponse
  from sqlalchemy.ext.asyncio import AsyncSession
  from sqlalchemy import select, func
  from pydantic import BaseModel
  from backend.database import get_db
  from backend.models import ScreeningTask, ScreeningResult, User
  from backend.auth import get_current_user
  from backend.worker.csv_parser import parse_csv

  router = APIRouter(prefix="/tasks", tags=["tasks"])

  class TaskCreate(BaseModel):
      name: str
      criteria_text: str
      source: str  # "csv" | "geo"
      geo_ids: Optional[list[str]] = None  # used when source="geo"

  @router.post("", status_code=201)
  async def create_task(
      name: str,
      criteria_text: str,
      source: str,
      file: Optional[UploadFile] = File(default=None),
      geo_ids: Optional[str] = Query(default=None),  # comma-separated
      db: AsyncSession = Depends(get_db),
      user: User = Depends(get_current_user),
  ):
      task = ScreeningTask(name=name, source=source, criteria_text=criteria_text, owner_id=user.id)
      db.add(task)
      await db.flush()

      datasets: list[dict] = []
      if source == "csv" and file:
          content = await file.read()
          datasets = parse_csv(content)
      elif source == "geo" and geo_ids:
          for gid in geo_ids.split(","):
              gid = gid.strip()
              if gid:
                  datasets.append({"id": gid, "title": "", "description": ""})

      task.total = len(datasets)
      for d in datasets:
          sr = ScreeningResult(task_id=task.id, dataset_id=d["id"], title=d.get("title", ""))
          db.add(sr)

      await db.commit()
      await db.refresh(task)

      # Dispatch Celery task
      from backend.worker.tasks import run_screening
      run_screening.delay(task.id)

      return {"id": task.id, "name": task.name, "status": task.status, "total": task.total}

  @router.get("")
  async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      result = await db.execute(select(ScreeningTask).where(ScreeningTask.owner_id == user.id).order_by(ScreeningTask.created_at.desc()))
      tasks = result.scalars().all()
      return [{"id": t.id, "name": t.name, "status": t.status, "total": t.total,
               "processed": t.processed, "created_at": t.created_at} for t in tasks]

  @router.get("/{task_id}")
  async def get_task(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id))
      task = result.scalar_one_or_none()
      if not task:
          raise HTTPException(status_code=404, detail="Not found")
      return {"id": task.id, "name": task.name, "status": task.status,
              "total": task.total, "processed": task.processed, "created_at": task.created_at}

  @router.get("/{task_id}/results")
  async def get_results(
      task_id: int,
      page: int = Query(default=1, ge=1),
      page_size: int = Query(default=20, ge=1, le=100),
      db: AsyncSession = Depends(get_db),
      user: User = Depends(get_current_user),
  ):
      task_result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id))
      if not task_result.scalar_one_or_none():
          raise HTTPException(status_code=404, detail="Not found")
      offset = (page - 1) * page_size
      count_result = await db.execute(select(func.count()).select_from(ScreeningResult).where(ScreeningResult.task_id == task_id))
      total = count_result.scalar()
      rows_result = await db.execute(
          select(ScreeningResult).where(ScreeningResult.task_id == task_id).offset(offset).limit(page_size))
      rows = rows_result.scalars().all()
      return {
          "total": total, "page": page, "page_size": page_size,
          "items": [{"id": r.id, "dataset_id": r.dataset_id, "title": r.title,
                     "decision": r.decision, "confidence": r.confidence,
                     "summary": r.summary, "rule_checks": r.rule_checks,
                     "status": r.status, "error_msg": r.error_msg} for r in rows],
      }

  @router.get("/{task_id}/export")
  async def export_results(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
      task_result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id))
      task = task_result.scalar_one_or_none()
      if not task:
          raise HTTPException(status_code=404, detail="Not found")
      rows_result = await db.execute(select(ScreeningResult).where(ScreeningResult.task_id == task_id))
      rows = rows_result.scalars().all()
      output = io.StringIO()
      writer = csv.writer(output)
      writer.writerow(["dataset_id", "title", "decision", "confidence", "summary", "rule_checks", "status"])
      for r in rows:
          writer.writerow([r.dataset_id, r.title, r.decision, r.confidence, r.summary, r.rule_checks, r.status])
      output.seek(0)
      return StreamingResponse(output, media_type="text/csv",
                               headers={"Content-Disposition": f"attachment; filename=task_{task_id}_results.csv"})
  ```

- [ ] Step 2: Write `backend/tests/test_tasks_router.py`:
  ```python
  import pytest
  from httpx import AsyncClient, ASGITransport
  from unittest.mock import patch, MagicMock

  @pytest.fixture
  async def auth_client():
      from backend.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          await client.post("/auth/register", json={"username": "taskuser", "email": "task@test.com", "password": "pw"})
          r = await client.post("/auth/login", json={"username": "taskuser", "password": "pw"})
          client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
          yield client

  @pytest.mark.asyncio
  async def test_create_geo_task(auth_client):
      with patch("backend.worker.tasks.run_screening.delay"):
          r = await auth_client.post("/tasks", params={
              "name": "Test Task", "criteria_text": "Must be human", "source": "geo", "geo_ids": "GSE001,GSE002"})
      assert r.status_code == 201
      assert r.json()["total"] == 2

  @pytest.mark.asyncio
  async def test_list_and_get_task(auth_client):
      with patch("backend.worker.tasks.run_screening.delay"):
          r = await auth_client.post("/tasks", params={
              "name": "List Test", "criteria_text": "criteria", "source": "geo", "geo_ids": "GSE003"})
      task_id = r.json()["id"]
      r2 = await auth_client.get("/tasks")
      assert any(t["id"] == task_id for t in r2.json())
      r3 = await auth_client.get(f"/tasks/{task_id}")
      assert r3.json()["id"] == task_id
  ```

- [ ] Step 3: Add tasks router to `backend/main.py` stub:
  ```python
  from backend.routers import tasks as tasks_router
  app.include_router(tasks_router.router)
  ```

- [ ] Step 4: Run tests:
  ```bash
  cd backend && pytest tests/test_tasks_router.py -v
  ```

- [ ] Step 5: Commit:
  ```bash
  git add -A && git commit -m "feat: tasks API with create/list/detail/results/export"
  ```

---

### Task 11: FastAPI Main App Wiring (main.py)

**Files:**
- Create: `backend/routers/geo.py`
- Replace: `backend/main.py`

- [ ] Step 1: Write `backend/routers/geo.py`:
  ```python
  from fastapi import APIRouter, Depends, Query
  from backend.auth import get_current_user
  from backend.models import User
  from backend.worker.geo_fetcher import search_geo

  router = APIRouter(prefix="/geo", tags=["geo"])

  @router.get("/search")
  async def geo_search(q: str = Query(..., min_length=2), user: User = Depends(get_current_user)):
      results = await search_geo(q, retmax=20)
      return results
  ```

- [ ] Step 2: Write final `backend/main.py`:
  ```python
  import os
  from contextlib import asynccontextmanager
  from fastapi import FastAPI, Request
  from fastapi.staticfiles import StaticFiles
  from fastapi.templating import Jinja2Templates
  from fastapi.responses import RedirectResponse
  from backend.database import init_db
  from backend.routers import auth as auth_router
  from backend.routers import criteria as criteria_router
  from backend.routers import llm as llm_router
  from backend.routers import tasks as tasks_router
  from backend.routers import geo as geo_router

  FRONTEND_DIR = os.getenv("FRONTEND_DIR", "../frontend")
  templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      await init_db()
      yield

  app = FastAPI(title="GEO Search & Screening", lifespan=lifespan)

  app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")

  app.include_router(auth_router.router)
  app.include_router(criteria_router.router)
  app.include_router(llm_router.router)
  app.include_router(tasks_router.router)
  app.include_router(geo_router.router)

  @app.get("/")
  async def root():
      return RedirectResponse(url="/tasks")

  @app.get("/login")
  async def login_page(request: Request):
      return templates.TemplateResponse("login.html", {"request": request})

  @app.get("/tasks")
  async def tasks_page(request: Request):
      return templates.TemplateResponse("tasks.html", {"request": request})

  @app.get("/tasks/new")
  async def tasks_new_page(request: Request):
      return templates.TemplateResponse("tasks_new.html", {"request": request})

  @app.get("/tasks/{task_id}")
  async def task_detail_page(request: Request, task_id: int):
      return templates.TemplateResponse("tasks_detail.html", {"request": request, "task_id": task_id})

  @app.get("/criteria")
  async def criteria_page(request: Request):
      return templates.TemplateResponse("criteria.html", {"request": request})

  @app.get("/settings")
  async def settings_page(request: Request):
      return templates.TemplateResponse("settings.html", {"request": request})
  ```

- [ ] Step 3: Run full test suite:
  ```bash
  cd backend && pytest -v
  ```

- [ ] Step 4: Commit:
  ```bash
  git add -A && git commit -m "feat: main.py wires all routers, serves Jinja2 templates"
  ```

---

### Task 12: Frontend Base Template + Login Page

**Files:**
- Create: `frontend/templates/base.html`
- Create: `frontend/templates/login.html`
- Replace: `frontend/static/app.js`

- [ ] Step 1: Write `frontend/templates/base.html`:
  ```html
  <!DOCTYPE html>
  <html lang="en" x-data="appState()" x-init="init()">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{% block title %}GEO Screener{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <script src="/static/app.js"></script>
  </head>
  <body class="bg-gray-50 text-gray-900 min-h-screen">
    <nav class="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <a href="/tasks" class="font-semibold text-blue-600 text-lg">GEO Screener</a>
      <div class="flex gap-4 text-sm">
        <a href="/tasks" class="hover:text-blue-600">Tasks</a>
        <a href="/criteria" class="hover:text-blue-600">Criteria</a>
        <a href="/settings" class="hover:text-blue-600">Settings</a>
        <button @click="logout()" class="text-red-500 hover:text-red-700">Logout</button>
      </div>
    </nav>
    <main class="max-w-6xl mx-auto px-6 py-8">
      {% block content %}{% endblock %}
    </main>
  </body>
  </html>
  ```

- [ ] Step 2: Write `frontend/templates/login.html`:
  ```html
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Login — GEO Screener</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
  </head>
  <body class="bg-gray-50 flex items-center justify-center min-h-screen">
    <div x-data="loginForm()" class="bg-white rounded-xl shadow p-8 w-full max-w-sm">
      <h1 class="text-2xl font-bold mb-6 text-center">GEO Screener</h1>
      <div x-show="error" class="mb-4 text-red-600 text-sm" x-text="error"></div>
      <form @submit.prevent="submit()">
        <label class="block text-sm font-medium mb-1">Username</label>
        <input x-model="username" type="text" required
               class="w-full border rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-400" />
        <label class="block text-sm font-medium mb-1">Password</label>
        <input x-model="password" type="password" required
               class="w-full border rounded-lg px-3 py-2 mb-6 focus:outline-none focus:ring-2 focus:ring-blue-400" />
        <button type="submit" :disabled="loading"
                class="w-full bg-blue-600 text-white rounded-lg py-2 font-medium hover:bg-blue-700 disabled:opacity-50">
          <span x-text="loading ? 'Signing in…' : 'Sign in'"></span>
        </button>
      </form>
    </div>
    <script>
      function loginForm() {
        return {
          username: '', password: '', error: '', loading: false,
          async submit() {
            this.loading = true; this.error = '';
            const r = await fetch('/auth/login', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({username: this.username, password: this.password})
            });
            this.loading = false;
            if (r.ok) { window.location.href = '/tasks'; }
            else { const d = await r.json(); this.error = d.detail || 'Login failed'; }
          }
        }
      }
    </script>
  </body>
  </html>
  ```

- [ ] Step 3: Write `frontend/static/app.js`:
  ```javascript
  function appState() {
    return {
      async init() {
        const r = await fetch('/auth/login', {method: 'HEAD'}).catch(() => null);
        // Redirect to login if cookie auth fails on protected pages
      },
      async logout() {
        await fetch('/auth/logout', {method: 'POST'});
        window.location.href = '/login';
      },
      async api(method, path, body) {
        const opts = {method, headers: {'Content-Type': 'application/json'}};
        if (body) opts.body = JSON.stringify(body);
        const r = await fetch(path, opts);
        if (r.status === 401) { window.location.href = '/login'; return null; }
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Request failed'); }
        return r.json();
      }
    }
  }
  ```

- [ ] Step 4: Manual test — start server and visit `http://localhost:8000/login`:
  ```bash
  cd backend && uvicorn main:app --reload --port 8000
  ```
  Verify login form renders, submitting with wrong credentials shows error, correct credentials redirect to `/tasks`.

- [ ] Step 5: Commit:
  ```bash
  git add -A && git commit -m "feat: base template, login page, Alpine.js app state"
  ```

---

### Task 13: Frontend Tasks List Page (tasks.html)

**Files:**
- Create: `frontend/templates/tasks.html`

- [ ] Step 1: Write `frontend/templates/tasks.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Tasks — GEO Screener{% endblock %}
  {% block content %}
  <div x-data="tasksPage()" x-init="load()">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Screening Tasks</h1>
      <a href="/tasks/new" class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm font-medium">
        + New Task
      </a>
    </div>

    <div x-show="loading" class="text-gray-400 text-sm">Loading…</div>
    <div x-show="!loading && tasks.length === 0" class="text-gray-400 text-sm">No tasks yet.</div>

    <div class="space-y-3">
      <template x-for="t in tasks" :key="t.id">
        <a :href="'/tasks/' + t.id"
           class="block bg-white rounded-xl border border-gray-200 px-5 py-4 hover:border-blue-300 transition">
          <div class="flex items-center justify-between">
            <div>
              <p class="font-medium" x-text="t.name"></p>
              <p class="text-xs text-gray-400 mt-1" x-text="new Date(t.created_at).toLocaleString()"></p>
            </div>
            <div class="text-right">
              <span :class="statusClass(t.status)"
                    class="text-xs font-semibold px-2 py-1 rounded-full" x-text="t.status"></span>
              <p class="text-xs text-gray-400 mt-1" x-text="t.processed + ' / ' + t.total"></p>
            </div>
          </div>
          <div x-show="t.status === 'running'" class="mt-3">
            <div class="w-full bg-gray-100 rounded-full h-1.5">
              <div class="bg-blue-500 h-1.5 rounded-full transition-all"
                   :style="'width:' + (t.total ? Math.round(t.processed/t.total*100) : 0) + '%'"></div>
            </div>
          </div>
        </a>
      </template>
    </div>
  </div>

  <script>
    function tasksPage() {
      return {
        tasks: [], loading: true,
        async load() {
          this.loading = true;
          const r = await fetch('/tasks');
          if (r.status === 401) { window.location.href = '/login'; return; }
          this.tasks = await r.json();
          this.loading = false;
        },
        statusClass(s) {
          return {
            pending:  'bg-gray-100 text-gray-600',
            running:  'bg-blue-100 text-blue-700',
            done:     'bg-green-100 text-green-700',
            error:    'bg-red-100 text-red-700',
          }[s] || 'bg-gray-100 text-gray-600';
        }
      }
    }
  </script>
  {% endblock %}
  ```

- [ ] Step 2: Manual test — visit `http://localhost:8000/tasks` after login. Verify task list renders, empty state shows, status badges display correctly.

- [ ] Step 3: Commit:
  ```bash
  git add -A && git commit -m "feat: tasks list page with status badges and progress bars"
  ```

---

### Task 14: Frontend New Task Page (tasks_new.html)

**Files:**
- Create: `frontend/templates/tasks_new.html`

- [ ] Step 1: Write `frontend/templates/tasks_new.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}New Task — GEO Screener{% endblock %}
  {% block content %}
  <div x-data="newTaskPage()" x-init="loadCriteria()">
    <h1 class="text-2xl font-bold mb-6">New Screening Task</h1>

    <div x-show="error" class="mb-4 text-red-600 text-sm bg-red-50 rounded-lg px-4 py-2" x-text="error"></div>

    <div class="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
      <div>
        <label class="block text-sm font-medium mb-1">Task Name</label>
        <input x-model="name" type="text" placeholder="e.g. Cancer RNA-seq screen"
               class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1">Screening Criteria</label>
        <select x-model="criteriaId" @change="onCriteriaSelect()"
                class="w-full border rounded-lg px-3 py-2 mb-2 focus:outline-none focus:ring-2 focus:ring-blue-400">
          <option value="">— Select template or write custom —</option>
          <template x-for="c in criteriaList" :key="c.id">
            <option :value="c.id" x-text="c.name"></option>
          </template>
        </select>
        <textarea x-model="criteriaText" rows="5" placeholder="Enter criteria in natural language…"
                  class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400 font-mono text-sm"></textarea>
      </div>

      <!-- Source tabs -->
      <div>
        <label class="block text-sm font-medium mb-2">Dataset Source</label>
        <div class="flex gap-2 mb-4">
          <button @click="source='csv'" :class="source==='csv' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'"
                  class="px-4 py-1.5 rounded-lg text-sm font-medium">Upload CSV</button>
          <button @click="source='geo'" :class="source==='geo' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'"
                  class="px-4 py-1.5 rounded-lg text-sm font-medium">GEO Search</button>
        </div>

        <!-- CSV tab -->
        <div x-show="source==='csv'">
          <input type="file" accept=".csv" @change="onFile($event)"
                 class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700" />
          <p x-show="csvRows > 0" class="text-xs text-gray-400 mt-1" x-text="csvRows + ' datasets detected'"></p>
        </div>

        <!-- GEO search tab -->
        <div x-show="source==='geo'" class="space-y-3">
          <div class="flex gap-2">
            <input x-model="geoQuery" type="text" placeholder="Search GEO (e.g. cancer RNA-seq human)"
                   @keydown.enter="searchGEO()"
                   class="flex-1 border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
            <button @click="searchGEO()" :disabled="geoLoading"
                    class="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
              Search
            </button>
          </div>
          <div x-show="geoResults.length > 0" class="border rounded-lg divide-y max-h-64 overflow-y-auto">
            <template x-for="r in geoResults" :key="r.id">
              <label class="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer">
                <input type="checkbox" :value="r.id" x-model="selectedGeoIds" class="mt-1" />
                <div>
                  <p class="text-sm font-medium" x-text="r.id + ' — ' + r.title"></p>
                  <p class="text-xs text-gray-400 line-clamp-2" x-text="r.summary"></p>
                </div>
              </label>
            </template>
          </div>
          <p x-show="selectedGeoIds.length > 0" class="text-xs text-gray-400"
             x-text="selectedGeoIds.length + ' datasets selected'"></p>
        </div>
      </div>

      <button @click="submit()" :disabled="submitting"
              class="w-full bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50">
        <span x-text="submitting ? 'Creating…' : 'Start Screening'"></span>
      </button>
    </div>
  </div>

  <script>
    function newTaskPage() {
      return {
        name: '', criteriaId: '', criteriaText: '', criteriaList: [],
        source: 'csv', csvFile: null, csvRows: 0,
        geoQuery: '', geoResults: [], geoLoading: false, selectedGeoIds: [],
        submitting: false, error: '',

        async loadCriteria() {
          const r = await fetch('/criteria');
          if (r.ok) this.criteriaList = await r.json();
        },
        onCriteriaSelect() {
          const c = this.criteriaList.find(x => x.id == this.criteriaId);
          if (c) this.criteriaText = c.criteria_text;
        },
        onFile(e) {
          this.csvFile = e.target.files[0];
          if (!this.csvFile) return;
          const reader = new FileReader();
          reader.onload = (ev) => {
            const lines = ev.target.result.split('\n').filter(l => l.trim());
            this.csvRows = Math.max(0, lines.length - 1);
          };
          reader.readAsText(this.csvFile);
        },
        async searchGEO() {
          if (!this.geoQuery.trim()) return;
          this.geoLoading = true;
          const r = await fetch('/geo/search?q=' + encodeURIComponent(this.geoQuery));
          this.geoLoading = false;
          if (r.ok) this.geoResults = await r.json();
        },
        async submit() {
          if (!this.name.trim() || !this.criteriaText.trim()) {
            this.error = 'Task name and criteria are required.'; return;
          }
          this.submitting = true; this.error = '';
          try {
            let r;
            if (this.source === 'csv') {
              const fd = new FormData();
              fd.append('name', this.name);
              fd.append('criteria_text', this.criteriaText);
              fd.append('source', 'csv');
              if (this.csvFile) fd.append('file', this.csvFile);
              r = await fetch('/tasks', {method: 'POST', body: fd});
            } else {
              const params = new URLSearchParams({
                name: this.name, criteria_text: this.criteriaText,
                source: 'geo', geo_ids: this.selectedGeoIds.join(',')
              });
              r = await fetch('/tasks?' + params, {method: 'POST'});
            }
            if (r.ok) {
              const d = await r.json();
              window.location.href = '/tasks/' + d.id;
            } else {
              const d = await r.json();
              this.error = d.detail || 'Failed to create task';
            }
          } finally { this.submitting = false; }
        }
      }
    }
  </script>
  {% endblock %}
  ```

- [ ] Step 2: Manual test — visit `/tasks/new`. Verify: CSV tab shows file picker, GEO tab shows search + checkbox list, criteria dropdown populates from API, form submits and redirects to task detail.

- [ ] Step 3: Commit:
  ```bash
  git add -A && git commit -m "feat: new task page with CSV upload and GEO search tabs"
  ```

---

### Task 15: Frontend Task Detail Page (tasks_detail.html)

**Files:**
- Create: `frontend/templates/tasks_detail.html`

- [ ] Step 1: Write `frontend/templates/tasks_detail.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Task Detail — GEO Screener{% endblock %}
  {% block content %}
  <div x-data="taskDetailPage({{ task_id }})" x-init="init()">
    <div class="flex items-center gap-3 mb-6">
      <a href="/tasks" class="text-gray-400 hover:text-gray-600 text-sm">← Tasks</a>
      <h1 class="text-2xl font-bold" x-text="task.name || 'Loading…'"></h1>
      <span :class="statusClass(task.status)"
            class="text-xs font-semibold px-2 py-1 rounded-full" x-text="task.status"></span>
    </div>

    <!-- Progress bar -->
    <div x-show="task.status === 'running' || task.status === 'done'" class="mb-6">
      <div class="flex justify-between text-xs text-gray-400 mb-1">
        <span x-text="task.processed + ' / ' + task.total + ' processed'"></span>
        <span x-text="task.total ? Math.round(task.processed/task.total*100) + '%' : '0%'"></span>
      </div>
      <div class="w-full bg-gray-100 rounded-full h-2">
        <div class="bg-blue-500 h-2 rounded-full transition-all"
             :style="'width:' + (task.total ? Math.round(task.processed/task.total*100) : 0) + '%'"></div>
      </div>
    </div>

    <!-- Export button -->
    <div class="flex justify-end mb-4">
      <a :href="'/tasks/' + taskId + '/export'"
         class="text-sm bg-gray-100 hover:bg-gray-200 px-4 py-2 rounded-lg font-medium">
        Export CSV
      </a>
    </div>

    <!-- Results table -->
    <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 border-b">
          <tr>
            <th class="text-left px-4 py-3 font-medium text-gray-600">Dataset</th>
            <th class="text-left px-4 py-3 font-medium text-gray-600">Decision</th>
            <th class="text-left px-4 py-3 font-medium text-gray-600">Confidence</th>
            <th class="text-left px-4 py-3 font-medium text-gray-600">Summary</th>
            <th class="text-left px-4 py-3 font-medium text-gray-600">Status</th>
          </tr>
        </thead>
        <tbody class="divide-y">
          <template x-for="r in results" :key="r.id">
            <tr @click="toggleExpand(r.id)" class="cursor-pointer hover:bg-gray-50">
              <td class="px-4 py-3 font-mono text-xs" x-text="r.dataset_id"></td>
              <td class="px-4 py-3">
                <span :class="decisionClass(r.decision)"
                      class="text-xs font-semibold px-2 py-0.5 rounded-full" x-text="r.decision || '—'"></span>
              </td>
              <td class="px-4 py-3 text-xs" x-text="r.confidence != null ? (r.confidence*100).toFixed(0)+'%' : '—'"></td>
              <td class="px-4 py-3 text-xs text-gray-600 max-w-xs truncate" x-text="r.summary || r.error_msg || '—'"></td>
              <td class="px-4 py-3">
                <span :class="statusClass(r.status)"
                      class="text-xs font-semibold px-2 py-0.5 rounded-full" x-text="r.status"></span>
              </td>
            </tr>
            <!-- Expanded row -->
            <tr x-show="expanded.has(r.id)" class="bg-blue-50">
              <td colspan="5" class="px-4 py-3">
                <p class="text-xs font-medium text-gray-500 mb-1">Title</p>
                <p class="text-sm mb-3" x-text="r.title || '—'"></p>
                <p class="text-xs font-medium text-gray-500 mb-1">Rule Checks</p>
                <pre class="text-xs bg-white rounded p-2 overflow-x-auto" x-text="formatRuleChecks(r.rule_checks)"></pre>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div x-show="results.length === 0 && !loading" class="text-center text-gray-400 py-8 text-sm">No results yet.</div>
    </div>

    <!-- Pagination -->
    <div class="flex justify-between items-center mt-4 text-sm">
      <button @click="prevPage()" :disabled="page <= 1"
              class="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40">← Prev</button>
      <span class="text-gray-400" x-text="'Page ' + page + ' of ' + totalPages"></span>
      <button @click="nextPage()" :disabled="page >= totalPages"
              class="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40">Next →</button>
    </div>
  </div>

  <script>
    function taskDetailPage(taskId) {
      return {
        taskId, task: {}, results: [], loading: true,
        page: 1, pageSize: 20, total: 0, expanded: new Set(),
        pollTimer: null,

        async init() {
          await this.loadTask();
          await this.loadResults();
          if (this.task.status === 'running' || this.task.status === 'pending') {
            this.pollTimer = setInterval(() => this.poll(), 3000);
          }
        },
        async loadTask() {
          const r = await fetch('/tasks/' + this.taskId);
          if (r.ok) this.task = await r.json();
        },
        async loadResults() {
          this.loading = true;
          const r = await fetch(`/tasks/${this.taskId}/results?page=${this.page}&page_size=${this.pageSize}`);
          if (r.ok) {
            const d = await r.json();
            this.results = d.items; this.total = d.total;
          }
          this.loading = false;
        },
        async poll() {
          await this.loadTask();
          await this.loadResults();
          if (this.task.status !== 'running' && this.task.status !== 'pending') {
            clearInterval(this.pollTimer);
          }
        },
        get totalPages() { return Math.max(1, Math.ceil(this.total / this.pageSize)); },
        async prevPage() { if (this.page > 1) { this.page--; await this.loadResults(); } },
        async nextPage() { if (this.page < this.totalPages) { this.page++; await this.loadResults(); } },
        toggleExpand(id) {
          if (this.expanded.has(id)) this.expanded.delete(id);
          else this.expanded.add(id);
          this.expanded = new Set(this.expanded);
        },
        formatRuleChecks(raw) {
          try { return JSON.stringify(JSON.parse(raw), null, 2); } catch { return raw || '—'; }
        },
        statusClass(s) {
          return {pending:'bg-gray-100 text-gray-600',running:'bg-blue-100 text-blue-700',
                  done:'bg-green-100 text-green-700',error:'bg-red-100 text-red-700'}[s] || 'bg-gray-100 text-gray-600';
        },
        decisionClass(d) {
          return {include:'bg-green-100 text-green-700',exclude:'bg-red-100 text-red-700',
                  uncertain:'bg-yellow-100 text-yellow-700'}[d] || 'bg-gray-100 text-gray-500';
        }
      }
    }
  </script>
  {% endblock %}
  ```

- [ ] Step 2: Manual test — create a task, visit its detail page. Verify: progress bar updates every 3s while running, results table shows with expandable rows, export button downloads CSV.

- [ ] Step 3: Commit:
  ```bash
  git add -A && git commit -m "feat: task detail page with polling, results table, expandable rows, export"
  ```

---

### Task 16: Frontend Criteria Management Page (criteria.html)

**Files:**
- Create: `frontend/templates/criteria.html`

- [ ] Step 1: Write `frontend/templates/criteria.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Criteria — GEO Screener{% endblock %}
  {% block content %}
  <div x-data="criteriaPage()" x-init="load()">
    <h1 class="text-2xl font-bold mb-6">Screening Criteria</h1>

    <div class="flex gap-6">
      <!-- Left panel: list -->
      <div class="w-64 flex-shrink-0">
        <button @click="newCriteria()"
                class="w-full mb-3 bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700">
          + New Criteria
        </button>
        <div class="space-y-1">
          <template x-for="c in list" :key="c.id">
            <button @click="select(c)"
                    :class="selected && selected.id === c.id ? 'bg-blue-50 border-blue-300' : 'bg-white border-gray-200'"
                    class="w-full text-left px-3 py-2.5 rounded-lg border text-sm hover:border-blue-300 transition">
              <p class="font-medium truncate" x-text="c.name"></p>
              <p class="text-xs text-gray-400 mt-0.5" x-text="new Date(c.updated_at).toLocaleDateString()"></p>
            </button>
          </template>
        </div>
      </div>

      <!-- Right panel: editor -->
      <div class="flex-1 bg-white rounded-xl border border-gray-200 p-6">
        <div x-show="!selected" class="text-gray-400 text-sm text-center py-16">
          Select a criteria template or create a new one.
        </div>
        <div x-show="selected">
          <div x-show="saveMsg" class="mb-3 text-green-600 text-sm" x-text="saveMsg"></div>
          <div x-show="error" class="mb-3 text-red-600 text-sm" x-text="error"></div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-1">Name</label>
            <input x-model="editName" type="text"
                   class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-1">Criteria Text</label>
            <textarea x-model="editText" rows="12"
                      placeholder="Describe your inclusion/exclusion criteria in natural language…"
                      class="w-full border rounded-lg px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"></textarea>
          </div>
          <div class="flex gap-3">
            <button @click="save()" :disabled="saving"
                    class="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              <span x-text="saving ? 'Saving…' : 'Save'"></span>
            </button>
            <button @click="deleteCriteria()" x-show="selected && selected.id"
                    class="text-red-500 hover:text-red-700 px-4 py-2 text-sm">Delete</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    function criteriaPage() {
      return {
        list: [], selected: null, editName: '', editText: '',
        saving: false, saveMsg: '', error: '',

        async load() {
          const r = await fetch('/criteria');
          if (r.status === 401) { window.location.href = '/login'; return; }
          this.list = await r.json();
        },
        select(c) {
          this.selected = c; this.editName = c.name; this.editText = c.criteria_text;
          this.saveMsg = ''; this.error = '';
        },
        newCriteria() {
          this.selected = {id: null, name: '', criteria_text: ''};
          this.editName = ''; this.editText = ''; this.saveMsg = ''; this.error = '';
        },
        async save() {
          this.saving = true; this.error = ''; this.saveMsg = '';
          try {
            const body = {name: this.editName, criteria_text: this.editText};
            let r;
            if (this.selected.id) {
              r = await fetch('/criteria/' + this.selected.id, {
                method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            } else {
              r = await fetch('/criteria', {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            }
            if (r.ok) {
              const updated = await r.json();
              this.selected = updated;
              await this.load();
              this.saveMsg = 'Saved!';
              setTimeout(() => this.saveMsg = '', 2000);
            } else {
              const d = await r.json(); this.error = d.detail || 'Save failed';
            }
          } finally { this.saving = false; }
        },
        async deleteCriteria() {
          if (!confirm('Delete this criteria template?')) return;
          await fetch('/criteria/' + this.selected.id, {method: 'DELETE'});
          this.selected = null;
          await this.load();
        }
      }
    }
  </script>
  {% endblock %}
  ```

- [ ] Step 2: Manual test — visit `/criteria`. Verify: left panel lists templates, clicking selects and populates editor, save creates/updates, delete removes from list.

- [ ] Step 3: Commit:
  ```bash
  git add -A && git commit -m "feat: criteria management page with split-panel editor"
  ```

---

### Task 17: Frontend Settings Page (settings.html)

**Files:**
- Create: `frontend/templates/settings.html`

- [ ] Step 1: Write `frontend/templates/settings.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Settings — GEO Screener{% endblock %}
  {% block content %}
  <div x-data="settingsPage()" x-init="load()">
    <h1 class="text-2xl font-bold mb-6">LLM Settings</h1>

    <div class="bg-white rounded-xl border border-gray-200 p-6 max-w-lg space-y-5">
      <div x-show="saveMsg" class="text-green-600 text-sm" x-text="saveMsg"></div>
      <div x-show="error" class="text-red-600 text-sm" x-text="error"></div>

      <div>
        <label class="block text-sm font-medium mb-1">Provider</label>
        <select x-model="form.provider" @change="onProviderChange()"
                class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400">
          <option value="deepseek">DeepSeek</option>
          <option value="glm">GLM (Zhipu)</option>
          <option value="minimax">MiniMax</option>
          <option value="custom">Custom (OpenAI-compatible)</option>
        </select>
      </div>

      <div x-show="form.provider === 'custom'">
        <label class="block text-sm font-medium mb-1">Base URL</label>
        <input x-model="form.base_url" type="url" placeholder="https://api.example.com/v1"
               class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1">API Key</label>
        <input x-model="form.api_key" type="password" placeholder="sk-…"
               class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1">Model</label>
        <input x-model="form.model" type="text" placeholder="e.g. deepseek-chat"
               class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1">Temperature
          <span class="text-gray-400 font-normal" x-text="'(' + form.temperature + ')'"></span>
        </label>
        <input x-model.number="form.temperature" type="range" min="0" max="1" step="0.05" class="w-full" />
      </div>

      <div class="flex gap-3">
        <button @click="save()" :disabled="saving"
                class="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          <span x-text="saving ? 'Saving…' : 'Save'"></span>
        </button>
        <button @click="testConn()" :disabled="testing"
                class="bg-gray-100 text-gray-700 px-5 py-2 rounded-lg text-sm font-medium hover:bg-gray-200 disabled:opacity-50">
          <span x-text="testing ? 'Testing…' : 'Test Connection'"></span>
        </button>
      </div>

      <div x-show="testResult !== null">
        <span x-show="testResult === true" class="text-green-600 text-sm font-medium">✓ Connection successful</span>
        <span x-show="testResult === false" class="text-red-600 text-sm font-medium" x-text="testError"></span>
      </div>
    </div>
  </div>

  <script>
    const PROVIDER_MODELS = {
      deepseek: 'deepseek-chat', glm: 'glm-4', minimax: 'abab6.5s-chat', custom: ''
    };

    function settingsPage() {
      return {
        form: {provider: 'deepseek', base_url: '', api_key: '', model: 'deepseek-chat', temperature: 0.1},
        saving: false, testing: false, saveMsg: '', error: '', testResult: null, testError: '',

        async load() {
          const r = await fetch('/llm/config');
          if (r.status === 401) { window.location.href = '/login'; return; }
          if (r.ok) {
            const d = await r.json();
            this.form = {...this.form, ...d, api_key: ''};
          }
        },
        onProviderChange() {
          this.form.model = PROVIDER_MODELS[this.form.provider] || '';
        },
        async save() {
          this.saving = true; this.error = ''; this.saveMsg = '';
          const body = {...this.form};
          if (!body.api_key) delete body.api_key;
          const r = await fetch('/llm/config', {
            method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
          this.saving = false;
          if (r.ok) { this.saveMsg = 'Saved!'; setTimeout(() => this.saveMsg = '', 2000); }
          else { const d = await r.json(); this.error = d.detail || 'Save failed'; }
        },
        async testConn() {
          this.testing = true; this.testResult = null; this.testError = '';
          const r = await fetch('/llm/test', {method: 'POST'});
          this.testing = false;
          if (r.ok) { this.testResult = true; }
          else { this.testResult = false; const d = await r.json(); this.testError = d.detail || 'Connection failed'; }
        }
      }
    }
  </script>
  {% endblock %}
  ```

- [ ] Step 2: Manual test — visit `/settings`. Verify: form loads current config, provider dropdown changes model default, save updates config, test connection calls `/llm/test` and shows result.

- [ ] Step 3: Commit:
  ```bash
  git add -A && git commit -m "feat: settings page with LLM config form and test connection"
  ```

---

### Task 18: End-to-End Smoke Test

**Files:**
- Create: `backend/tests/test_e2e_smoke.py`

- [ ] Step 1: Write `backend/tests/test_e2e_smoke.py`:
  ```python
  """
  End-to-end smoke test: register → login → create criteria → create GEO task →
  poll until done (mocked LLM) → fetch results → export CSV.
  """
  import asyncio
  import json
  import pytest
  from httpx import AsyncClient, ASGITransport
  from unittest.mock import AsyncMock, patch, MagicMock

  def _mock_llm_response():
      mock_resp = MagicMock()
      mock_resp.choices[0].message.content = json.dumps({
          "decision": "include", "confidence": 0.9,
          "summary": "Meets all criteria", "rule_checks": {"human": True}
      })
      return mock_resp

  @pytest.fixture
  async def client():
      from backend.main import app
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
          yield c

  @pytest.mark.asyncio
  async def test_full_workflow(client):
      # 1. Register
      r = await client.post("/auth/register", json={"username": "smokeuser", "email": "smoke@test.com", "password": "pw123"})
      assert r.status_code == 201

      # 2. Login
      r = await client.post("/auth/login", json={"username": "smokeuser", "password": "pw123"})
      assert r.status_code == 200
      token = r.json()["access_token"]
      client.headers["Authorization"] = f"Bearer {token}"

      # 3. Create criteria
      r = await client.post("/criteria", json={"name": "Human RCT", "criteria_text": "Must be human RCT"})
      assert r.status_code == 201
      criteria_id = r.json()["id"]

      # 4. Get criteria
      r = await client.get(f"/criteria/{criteria_id}")
      assert r.json()["name"] == "Human RCT"

      # 5. Update LLM config
      r = await client.put("/llm/config", json={"provider": "deepseek", "api_key": "sk-fake", "model": "deepseek-chat"})
      assert r.status_code == 200

      # 6. Create GEO task (mock Celery dispatch)
      with patch("backend.worker.tasks.run_screening.delay"):
          r = await client.post("/tasks", params={
              "name": "Smoke Test Task", "criteria_text": "Must be human RCT",
              "source": "geo", "geo_ids": "GSE001,GSE002,GSE003"})
      assert r.status_code == 201
      task_id = r.json()["id"]
      assert r.json()["total"] == 3

      # 7. Simulate worker running (call internal async function directly)
      mock_resp = _mock_llm_response()
      with patch("openai.resources.chat.completions.AsyncCompletions.create", new=AsyncMock(return_value=mock_resp)):
          from backend.worker.tasks import _run_screening_async
          await _run_screening_async(task_id)

      # 8. Poll task — should be done
      r = await client.get(f"/tasks/{task_id}")
      assert r.json()["status"] == "done"
      assert r.json()["processed"] == 3

      # 9. Fetch results
      r = await client.get(f"/tasks/{task_id}/results")
      assert r.status_code == 200
      items = r.json()["items"]
      assert len(items) == 3
      assert all(i["decision"] == "include" for i in items)

      # 10. Export CSV
      r = await client.get(f"/tasks/{task_id}/export")
      assert r.status_code == 200
      assert "text/csv" in r.headers["content-type"]
      lines = r.text.strip().split("\n")
      assert len(lines) == 4  # header + 3 rows

      # 11. Logout
      r = await client.post("/auth/logout")
      assert r.status_code == 200
  ```

- [ ] Step 2: Run full test suite:
  ```bash
  cd backend && pytest -v --tb=short
  ```
  All tests must pass.

- [ ] Step 3: Start services and do a manual browser walkthrough:
  ```bash
  # Terminal 1: Redis
  docker run --rm -p 6379:6379 redis:7-alpine

  # Terminal 2: Backend
  cd backend && uvicorn main:app --reload --port 8000

  # Terminal 3: Celery worker
  cd backend && celery -A worker.celery_app worker --loglevel=info
  ```
  Manual checklist:
  - [ ] Visit `http://localhost:8000` → redirects to `/tasks` → redirects to `/login`
  - [ ] Register a new user, login
  - [ ] Go to Settings, enter a real API key, click Test Connection
  - [ ] Go to Criteria, create a template
  - [ ] Go to New Task, search GEO for "cancer", select 3 datasets, pick criteria, submit
  - [ ] Watch task detail page — progress bar advances, results populate
  - [ ] Expand a result row to see rule_checks
  - [ ] Click Export CSV, verify download

- [ ] Step 4: Final commit:
  ```bash
  git add -A && git commit -m "test: end-to-end smoke test covering full screening workflow"
  ```

- [ ] Step 5: Tag release:
  ```bash
  git tag v0.1.0 && echo "GEO Search & Screening Platform v0.1.0 complete"
  ```

---

## 2026-04-15 Plan Update: GSE/GSM Rich Data + Annotation System

**Goal:** Enrich GEO data with full GSE metadata fields and GSM sub-samples, add a per-task LLM annotation system with human review, and redesign the task detail UI to match the reference layout.

**Architecture:** Extend existing FastAPI + SQLAlchemy stack with two new tables (`GeoSample`, `GeoLabel`), a new Celery annotation task, and a new `/annotate` router. Frontend task detail page rebuilt as a rich table with expandable GSM panels and inline label editing.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Celery, httpx, Alpine.js, Jinja2, Tailwind CSS

---

### Task 18: Extend Data Models (GeoSample + GeoLabel + ScreeningResult fields)

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/tests/test_models.py`

- [ ] Step 1: Write failing tests for new models:

```python
# backend/tests/test_models.py — add to existing file
@pytest.mark.asyncio
async def test_geo_sample_model(db):
    user = models.User(username="u1", email="u1@test.com", hashed_password="h")
    db.add(user)
    await db.flush()
    task = models.ScreeningTask(name="t", source="geo", criteria_text="", owner_id=user.id)
    db.add(task)
    await db.flush()
    sr = models.ScreeningResult(task_id=task.id, dataset_id="GSE001")
    db.add(sr)
    await db.flush()
    sample = models.GeoSample(
        result_id=sr.id, gsm_id="GSM001", title="Sample 1",
        organism="Homo sapiens", biosample_id="SAMN001", cell_count=None
    )
    db.add(sample)
    await db.commit()
    await db.refresh(sample)
    assert sample.id is not None
    assert sample.gsm_id == "GSM001"

@pytest.mark.asyncio
async def test_geo_label_model(db):
    user = models.User(username="u2", email="u2@test.com", hashed_password="h")
    db.add(user)
    await db.flush()
    task = models.ScreeningTask(name="t2", source="geo", criteria_text="", owner_id=user.id)
    db.add(task)
    await db.flush()
    sr = models.ScreeningResult(task_id=task.id, dataset_id="GSE002")
    db.add(sr)
    await db.flush()
    label = models.GeoLabel(result_id=sr.id, key="起始细胞类型", value="iPSC", source="llm")
    db.add(label)
    await db.commit()
    await db.refresh(label)
    assert label.source == "llm"
```

- [ ] Step 2: Run test to verify it fails:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_models.py -v -k "geo_sample or geo_label"
```
Expected: FAIL with `AttributeError: GeoSample` or similar.

- [ ] Step 3: Add new models and fields to `backend/models.py`:

```python
# Add to ScreeningResult class (after existing fields):
    gse_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pubdate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    update_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_raw_data: Mapped[bool] = mapped_column(default=False)
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    samples: Mapped[list["GeoSample"]] = relationship(back_populates="result", cascade="all, delete-orphan")
    labels: Mapped[list["GeoLabel"]] = relationship(back_populates="result", cascade="all, delete-orphan")

# Add to ScreeningTask class (after existing fields):
    label_schema: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of dimension names

# Add new classes at end of file:
class GeoSample(Base):
    __tablename__ = "geo_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    gsm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    organism: Mapped[str | None] = mapped_column(String(128), nullable=True)
    biosample_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped["ScreeningResult"] = relationship(back_populates="samples")

class GeoLabel(Base):
    __tablename__ = "geo_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="llm")  # llm | human
    result: Mapped["ScreeningResult"] = relationship(back_populates="labels")
```

- [ ] Step 4: Run tests:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_models.py -v
```
Expected: all PASS.

- [ ] Step 5: Commit:
```bash
git add backend/models.py backend/tests/test_models.py
git commit -m "feat: add GeoSample, GeoLabel models and enrich ScreeningResult fields"
```

---

### Task 19: Enrich GEO Fetcher (full GSE fields + GSM sub-samples)

**Files:**
- Modify: `backend/worker/geo_fetcher.py`
- Modify: `backend/tests/test_geo_fetcher.py`

- [ ] Step 1: Write failing tests:

```python
# backend/tests/test_geo_fetcher.py — replace existing content
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

MOCK_ESEARCH = {"esearchresult": {"idlist": ["200305128"]}}

MOCK_ESUMMARY = {
    "result": {
        "200305128": {
            "accession": "GSE305128",
            "title": "PreciCE study",
            "summary": "iPSC differentiation study",
            "taxon": "Homo sapiens",
            "n_samples": 3,
            "gse": "GSE305128",
            "entrytype": "GSE",
            "gdstype": "Expression profiling by high throughput sequencing",
            "pdat": "2026/04/01",
            "update_date": "2026/04/14",
            "ftplink": "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE305nnn/GSE305128/",
        }
    }
}

MOCK_GSM_ESEARCH = {"esearchresult": {"idlist": ["9162575", "9162576"]}}

MOCK_GSM_ESUMMARY = {
    "result": {
        "9162575": {
            "accession": "GSM9162575",
            "title": "Experiment 23-001",
            "organism": "Homo sapiens",
            "biosample": "SAMN50564034",
        },
        "9162576": {
            "accession": "GSM9162576",
            "title": "Experiment 23-006",
            "organism": "Homo sapiens",
            "biosample": "SAMN50564033",
        },
    }
}


@pytest.mark.asyncio
async def test_search_geo_returns_enriched_fields():
    from backend.worker.geo_fetcher import search_geo

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        if "esearch" in url:
            m.json.return_value = MOCK_ESEARCH
        else:
            m.json.return_value = MOCK_ESUMMARY
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        results = await search_geo("iPSC", retmax=10)

    assert len(results) == 1
    r = results[0]
    assert r["id"] == "GSE305128"
    assert r["gse_type"] == "Expression profiling by high throughput sequencing"
    assert r["pubdate"] == "2026/04/01"
    assert r["update_date"] == "2026/04/14"
    assert r["has_raw_data"] is True
    assert r["n_samples"] == 3


@pytest.mark.asyncio
async def test_fetch_gsm_samples():
    from backend.worker.geo_fetcher import fetch_gsm_samples

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        if "esearch" in url:
            m.json.return_value = MOCK_GSM_ESEARCH
        else:
            m.json.return_value = MOCK_GSM_ESUMMARY
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        samples = await fetch_gsm_samples("GSE305128")

    assert len(samples) == 2
    assert samples[0]["gsm_id"] == "GSM9162575"
    assert samples[0]["organism"] == "Homo sapiens"
    assert samples[0]["biosample_id"] == "SAMN50564034"
```

- [ ] Step 2: Run to verify failure:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_geo_fetcher.py -v
```
Expected: FAIL — `fetch_gsm_samples` not defined, missing fields in `search_geo`.

- [ ] Step 3: Update `backend/worker/geo_fetcher.py`:

```python
import asyncio
import httpx
from typing import Optional

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_RETRIES = 3
ESUMMARY_BATCH_SIZE = 100


async def search_geo(query: str, retmax: int = 20) -> list[dict]:
    """Search GEO datasets. Returns enriched list with GSE metadata."""
    ids = await _esearch("gds", query, retmax)
    if not ids:
        return []
    return await _efetch_gse_summaries(ids)


async def fetch_gsm_samples(gse_accession: str, retmax: int = 1000) -> list[dict]:
    """Fetch all GSM samples for a given GSE accession."""
    query = f"{gse_accession}[Accession] AND gsm[EntryType]"
    ids = await _esearch("gds", query, retmax)
    if not ids:
        return []
    return await _efetch_gsm_summaries(ids)


async def _esearch(db: str, query: str, retmax: int) -> list[str]:
    url = f"{NCBI_BASE}/esearch.fcgi"
    params = {"db": db, "term": query, "retmax": retmax, "retmode": "json"}
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return r.json()["esearchresult"]["idlist"]
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return []


async def _efetch_gse_summaries(ids: list[str]) -> list[dict]:
    url = f"{NCBI_BASE}/esummary.fcgi"
    async with httpx.AsyncClient(timeout=30) as client:
        results = []
        for start in range(0, len(ids), ESUMMARY_BATCH_SIZE):
            batch_ids = ids[start:start + ESUMMARY_BATCH_SIZE]
            params = {"db": "gds", "id": ",".join(batch_ids), "retmode": "json"}
            for attempt in range(MAX_RETRIES):
                try:
                    r = await client.get(url, params=params)
                    r.raise_for_status()
                    data = r.json()
                    for uid in batch_ids:
                        doc = data.get("result", {}).get(uid, {})
                        results.append({
                            "id": doc.get("accession", uid),
                            "title": doc.get("title", ""),
                            "summary": doc.get("summary", ""),
                            "organism": doc.get("taxon", ""),
                            "n_samples": doc.get("n_samples", 0),
                            "gse_type": doc.get("gdstype", ""),
                            "pubdate": doc.get("pdat", ""),
                            "update_date": doc.get("update_date", ""),
                            "has_raw_data": bool(doc.get("ftplink", "")),
                        })
                    break
                except (httpx.HTTPStatusError, httpx.TimeoutException):
                    if attempt == MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)
        return results


async def _efetch_gsm_summaries(ids: list[str]) -> list[dict]:
    url = f"{NCBI_BASE}/esummary.fcgi"
    async with httpx.AsyncClient(timeout=30) as client:
        results = []
        for start in range(0, len(ids), ESUMMARY_BATCH_SIZE):
            batch_ids = ids[start:start + ESUMMARY_BATCH_SIZE]
            params = {"db": "gds", "id": ",".join(batch_ids), "retmode": "json"}
            for attempt in range(MAX_RETRIES):
                try:
                    r = await client.get(url, params=params)
                    r.raise_for_status()
                    data = r.json()
                    for uid in batch_ids:
                        doc = data.get("result", {}).get(uid, {})
                        results.append({
                            "gsm_id": doc.get("accession", uid),
                            "title": doc.get("title", ""),
                            "organism": doc.get("organism", ""),
                            "biosample_id": doc.get("biosample", ""),
                        })
                    break
                except (httpx.HTTPStatusError, httpx.TimeoutException):
                    if attempt == MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)
        return results
```

- [ ] Step 4: Run tests:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_geo_fetcher.py -v
```
Expected: all PASS.

- [ ] Step 5: Commit:
```bash
git add backend/worker/geo_fetcher.py backend/tests/test_geo_fetcher.py
git commit -m "feat: enrich GEO fetcher with full GSE fields and GSM sub-sample fetching"
```

---

### Task 20: Update Task Creation to Persist GSM Samples + New Fields

**Files:**
- Modify: `backend/routers/tasks.py`
- Modify: `backend/tests/test_tasks_router.py`

- [ ] Step 1: Write failing test:

```python
# Add to backend/tests/test_tasks_router.py
@pytest.mark.asyncio
async def test_create_geo_task_persists_gsm_samples(auth_client):
    geo_candidates = [
        {"id": "GSE001", "title": "Study one", "summary": "iPSC study",
         "gse_type": "Expression profiling by high throughput sequencing",
         "pubdate": "2026/01/01", "update_date": "2026/04/14",
         "has_raw_data": True, "n_samples": 2, "organism": "Homo sapiens"},
    ]
    gsm_samples = [
        {"gsm_id": "GSM001", "title": "Sample 1", "organism": "Homo sapiens", "biosample_id": "SAMN001"},
        {"gsm_id": "GSM002", "title": "Sample 2", "organism": "Homo sapiens", "biosample_id": "SAMN002"},
    ]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=gsm_samples)), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await auth_client.post("/tasks", params={
            "name": "GSM Test",
            "criteria_text": "human iPSC",
            "source": "geo",
            "search_query": "iPSC liver",
            "label_schema": '["起始细胞类型","分化体系"]',
        })
    assert r.status_code == 201
    task_id = r.json()["id"]

    results_r = await auth_client.get(f"/tasks/{task_id}/results")
    items = results_r.json()["items"]
    assert len(items) == 1
    assert items[0]["gse_type"] == "Expression profiling by high throughput sequencing"
    assert items[0]["has_raw_data"] is True
    assert len(items[0]["samples"]) == 2
    assert items[0]["samples"][0]["gsm_id"] == "GSM001"
```

- [ ] Step 2: Run to verify failure:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_tasks_router.py::test_create_geo_task_persists_gsm_samples -v
```
Expected: FAIL.

- [ ] Step 3: Update `backend/routers/tasks.py` — add import and update `create_task`:

At top, add:
```python
from backend.worker.geo_fetcher import search_geo, fetch_gsm_samples
from backend.models import GeoSample
```

In `create_task`, replace the GEO candidate persistence block:
```python
    task.total = len(datasets)
    task.candidate_count = len(datasets)
    for d in datasets:
        sr = ScreeningResult(
            task_id=task.id,
            dataset_id=d["id"],
            title=d.get("title", ""),
            description=d.get("description") or d.get("summary", ""),
            keyword_matched=True,
            gse_type=d.get("gse_type", ""),
            pubdate=d.get("pubdate", ""),
            update_date=d.get("update_date", ""),
            has_raw_data=d.get("has_raw_data", False),
            n_samples=d.get("n_samples", 0),
        )
        db.add(sr)
        await db.flush()
        # Fetch and persist GSM samples for GEO tasks
        if source == "geo":
            gsm_list = await fetch_gsm_samples(d["id"])
            for gsm in gsm_list:
                db.add(GeoSample(
                    result_id=sr.id,
                    gsm_id=gsm["gsm_id"],
                    title=gsm.get("title", ""),
                    organism=gsm.get("organism", ""),
                    biosample_id=gsm.get("biosample_id", ""),
                ))
```

Also add `label_schema` param to `create_task` signature:
```python
    label_schema: Optional[str] = Query(default=None),
```
And set it on the task:
```python
    task = ScreeningTask(
        name=name, source=source, search_query=search_query,
        criteria_text=criteria_text, owner_id=user.id,
        label_schema=label_schema,
    )
```

Update `get_results` to include samples in each item:
```python
from sqlalchemy.orm import selectinload
# In get_results, change the query:
rows_result = await db.execute(
    base_query.options(selectinload(ScreeningResult.samples)).offset(offset).limit(page_size)
)
# In the items list comprehension, add:
"samples": [{"gsm_id": s.gsm_id, "title": s.title, "organism": s.organism,
              "biosample_id": s.biosample_id, "cell_count": s.cell_count} for s in r.samples],
"gse_type": r.gse_type, "pubdate": r.pubdate, "update_date": r.update_date,
"has_raw_data": r.has_raw_data, "n_samples": r.n_samples,
```

- [ ] Step 4: Run all task router tests:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_tasks_router.py -v
```
Expected: all PASS.

- [ ] Step 5: Commit:
```bash
git add backend/routers/tasks.py backend/tests/test_tasks_router.py
git commit -m "feat: persist GSM samples and enriched GSE fields on task creation"
```

---

### Task 21: Annotation Router + LLM Label Extraction Worker

**Files:**
- Create: `backend/routers/annotate.py`
- Modify: `backend/worker/tasks.py`
- Modify: `backend/worker/llm_client.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_annotate_router.py`

- [ ] Step 1: Write failing tests:

```python
# backend/tests/test_annotate_router.py
import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
async def auth_client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/register", json={"username": "annuser", "email": "ann@test.com", "password": "pw"})
        r = await client.post("/auth/login", json={"username": "annuser", "password": "pw"})
        client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield client


@pytest.mark.asyncio
async def test_get_labels_empty(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="ann_task", source="geo", criteria_text="", owner_id=1,
                             label_schema='["起始细胞类型"]')
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE999")
        db.add(sr)
        await db.commit()
        result_id = sr.id

    r = await auth_client.get(f"/annotate/results/{result_id}/labels")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_upsert_label_human(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="ann_task2", source="geo", criteria_text="", owner_id=1,
                             label_schema='["起始细胞类型"]')
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE998")
        db.add(sr)
        await db.commit()
        result_id = sr.id

    r = await auth_client.put(f"/annotate/results/{result_id}/labels", json={
        "key": "起始细胞类型", "value": "iPSC"
    })
    assert r.status_code == 200
    assert r.json()["source"] == "human"
    assert r.json()["value"] == "iPSC"

    # Second upsert updates value
    r2 = await auth_client.put(f"/annotate/results/{result_id}/labels", json={
        "key": "起始细胞类型", "value": "ESC"
    })
    assert r2.json()["value"] == "ESC"
    assert r2.json()["source"] == "human"
```

- [ ] Step 2: Run to verify failure:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_annotate_router.py -v
```
Expected: FAIL — router not found.

- [ ] Step 3: Create `backend/routers/annotate.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import ScreeningResult, GeoLabel, ScreeningTask, User
from backend.auth import get_current_user

router = APIRouter(prefix="/annotate", tags=["annotate"])


class LabelUpsert(BaseModel):
    key: str
    value: str | None = None


@router.get("/results/{result_id}/labels")
async def get_labels(result_id: int, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(GeoLabel).where(GeoLabel.result_id == result_id)
    )).scalars().all()
    return [{"id": r.id, "key": r.key, "value": r.value, "source": r.source} for r in rows]


@router.put("/results/{result_id}/labels")
async def upsert_label(result_id: int, body: LabelUpsert,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    existing = (await db.execute(
        select(GeoLabel).where(GeoLabel.result_id == result_id, GeoLabel.key == body.key)
    )).scalar_one_or_none()
    if existing:
        existing.value = body.value
        existing.source = "human"
        await db.commit()
        await db.refresh(existing)
        return {"id": existing.id, "key": existing.key, "value": existing.value, "source": existing.source}
    label = GeoLabel(result_id=result_id, key=body.key, value=body.value, source="human")
    db.add(label)
    await db.commit()
    await db.refresh(label)
    return {"id": label.id, "key": label.key, "value": label.value, "source": label.source}


@router.post("/tasks/{task_id}/run")
async def trigger_annotation(task_id: int, db: AsyncSession = Depends(get_db),
                              user: User = Depends(get_current_user)):
    task = (await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    if not task.label_schema:
        raise HTTPException(status_code=400, detail="No label_schema defined for this task")
    from backend.worker.tasks import run_annotation
    run_annotation.delay(task_id)
    return {"status": "queued"}
```

- [ ] Step 4: Add `extract_labels` method to `backend/worker/llm_client.py`:

```python
LABEL_PROMPT_TEMPLATE = """\
You are a biomedical data annotator. Extract the following information from the GEO dataset description.

## Dimensions to extract
{dimensions}

## Dataset Information
ID: {dataset_id}
Title: {title}
Description: {description}

## Instructions
Return ONLY valid JSON where each key is a dimension name and the value is the extracted string (or null if not determinable).
Example: {{"起始细胞类型": "iPSC", "分化体系": "2D", "数据平台": null}}
"""

    async def extract_labels(self, dataset_id: str, title: str, description: str,
                              dimensions: list[str]) -> dict:
        prompt = LABEL_PROMPT_TEMPLATE.format(
            dimensions="\n".join(f"- {d}" for d in dimensions),
            dataset_id=dataset_id, title=title, description=description,
        )
        response = await self._client.chat.completions.create(
            model=self.model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)
```

- [ ] Step 5: Add `run_annotation` Celery task to `backend/worker/tasks.py`:

```python
@celery_app.task(bind=True, name="worker.tasks.run_annotation")
def run_annotation(self, task_id: int):
    _run(_run_annotation_async(task_id))

async def _run_annotation_async(task_id: int):
    import json
    async with AsyncSessionLocal() as db:
        task = (await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))).scalar_one_or_none()
        if not task or not task.label_schema:
            return
        dimensions = json.loads(task.label_schema)
        cfg = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id))).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return
        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        results = (await db.execute(
            select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalars().all()
        for sr in results:
            try:
                extracted = await llm.extract_labels(
                    dataset_id=sr.dataset_id, title=sr.title or "",
                    description=sr.description or "", dimensions=dimensions,
                )
                for key, value in extracted.items():
                    existing = (await db.execute(
                        select(GeoLabel).where(GeoLabel.result_id == sr.id, GeoLabel.key == key)
                    )).scalar_one_or_none()
                    if existing and existing.source == "human":
                        continue  # don't overwrite human labels
                    if existing:
                        existing.value = str(value) if value is not None else None
                    else:
                        db.add(GeoLabel(result_id=sr.id, key=key,
                                        value=str(value) if value is not None else None, source="llm"))
            except Exception:
                pass
        await db.commit()
```

Add missing import at top of `backend/worker/tasks.py`:
```python
from backend.models import ScreeningTask, ScreeningResult, LLMConfig, GeoLabel
```

- [ ] Step 6: Register router in `backend/main.py`:
```python
from backend.routers import annotate as annotate_router
# after existing include_router calls:
app.include_router(annotate_router.router)
```

- [ ] Step 7: Run tests:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_annotate_router.py -v
```
Expected: all PASS.

- [ ] Step 8: Run full suite:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/ -q
```
Expected: all PASS.

- [ ] Step 9: Commit:
```bash
git add backend/routers/annotate.py backend/worker/tasks.py backend/worker/llm_client.py backend/main.py backend/tests/test_annotate_router.py
git commit -m "feat: annotation router with LLM label extraction and human upsert"
```

---

### Task 22: Redesign Task Detail Frontend (GSE table + GSM panel + label editing)

**Files:**
- Modify: `frontend/templates/tasks_detail.html`
- Modify: `frontend/templates/tasks_new.html`
- Modify: `backend/tests/test_pages.py`

- [ ] Step 1: Update `frontend/templates/tasks_new.html` — add `label_schema` input to the GEO tab:

In the GEO search tab section, after the existing `<p class="text-xs text-gray-500">` paragraph, add:
```html
        <div x-show="source==='geo'" class="mt-3">
          <label class="block text-sm font-medium mb-1">标注维度
            <span class="text-gray-400 font-normal">（每行一个，LLM 将自动提取）</span>
          </label>
          <textarea x-model="labelSchema" rows="5"
                    placeholder="起始细胞类型&#10;分化体系&#10;数据平台&#10;是否提供原始测序数据&#10;单细胞测序数据类型"
                    class="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400 font-mono text-sm"></textarea>
        </div>
```

In the Alpine.js data object, add `labelSchema: ''` to the return object.

In `submit()`, for the GEO branch, add `label_schema` to params:
```javascript
        const schemaArr = this.labelSchema.split('\n').map(s => s.trim()).filter(Boolean);
        const params = new URLSearchParams({
          name: this.name,
          criteria_text: this.criteriaText,
          source: 'geo',
          search_query: this.geoQuery,
          label_schema: JSON.stringify(schemaArr),
        });
```

- [ ] Step 2: Replace `frontend/templates/tasks_detail.html` with the new layout:

```html
{% extends "base.html" %}
{% block title %}Task Detail — GEO Screener{% endblock %}
{% block content %}
<div x-data="taskDetailPage({{ task_id }})" x-init="init()">
  <div class="flex items-center gap-3 mb-6">
    <a href="/tasks-list" class="text-gray-400 hover:text-gray-600 text-sm">← Tasks</a>
    <h1 class="text-2xl font-bold" x-text="task.name || 'Loading…'"></h1>
    <span :class="statusClass(task.status)"
          class="text-xs font-semibold px-2 py-1 rounded-full" x-text="task.status"></span>
  </div>

  <!-- Stats row -->
  <div class="grid gap-3 md:grid-cols-5 mb-6">
    <div class="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <p class="text-xs text-gray-400">GEO Candidates</p>
      <p class="text-2xl font-semibold" x-text="task.candidate_count || 0"></p>
    </div>
    <div class="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <p class="text-xs text-gray-400">Included</p>
      <p class="text-2xl font-semibold text-green-700" x-text="task.included_count || 0"></p>
    </div>
    <div class="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <p class="text-xs text-gray-400">Excluded</p>
      <p class="text-2xl font-semibold text-red-700" x-text="task.excluded_count || 0"></p>
    </div>
    <div class="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <p class="text-xs text-gray-400">Uncertain</p>
      <p class="text-2xl font-semibold text-yellow-700" x-text="task.uncertain_count || 0"></p>
    </div>
    <div class="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center">
      <button @click="triggerAnnotation()" :disabled="annotating"
              class="w-full text-sm bg-blue-600 text-white rounded-lg py-1.5 hover:bg-blue-700 disabled:opacity-50">
        <span x-text="annotating ? 'Running…' : 'Run LLM Annotation'"></span>
      </button>
    </div>
  </div>

  <!-- Progress bar -->
  <div x-show="task.status === 'running'" class="mb-6">
    <div class="flex justify-between text-xs text-gray-400 mb-1">
      <span x-text="task.processed + ' / ' + task.total + ' processed'"></span>
      <span x-text="task.total ? Math.round(task.processed/task.total*100) + '%' : '0%'"></span>
    </div>
    <div class="w-full bg-gray-100 rounded-full h-2">
      <div class="bg-blue-500 h-2 rounded-full transition-all"
           :style="'width:' + (task.total ? Math.round(task.processed/task.total*100) : 0) + '%'"></div>
    </div>
  </div>

  <!-- Toolbar -->
  <div class="flex justify-between items-center mb-4 gap-3">
    <div class="flex items-center gap-2">
      <label class="text-sm text-gray-500">筛选</label>
      <select x-model="decisionFilter" @change="reloadResults()"
              class="border rounded-lg px-3 py-2 text-sm bg-white">
        <option value="">全部候选</option>
        <option value="include">Included</option>
        <option value="exclude">Excluded</option>
        <option value="uncertain">Uncertain</option>
      </select>
    </div>
    <a :href="'/tasks/' + taskId + '/export'"
       class="text-sm bg-gray-100 hover:bg-gray-200 px-4 py-2 rounded-lg font-medium">导出 CSV</a>
  </div>

  <!-- GSE Table -->
  <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
    <table class="w-full text-sm">
      <thead class="bg-gray-50 border-b">
        <tr>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-36">Accession</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600">标题</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-20">Samples</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-48">实验类型</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-28">论文更新日期</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-28">最后更新</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-16">原始数据</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-24">决策</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-16">操作</th>
        </tr>
      </thead>
      <tbody class="divide-y">
        <template x-for="r in results" :key="r.id">
          <>
          <tr @click="toggleExpand(r.id)" class="cursor-pointer hover:bg-gray-50">
            <td class="px-4 py-3">
              <p class="font-mono text-xs font-semibold text-blue-700" x-text="r.dataset_id"></p>
              <p class="text-xs text-gray-400" x-text="r.n_samples ? r.n_samples + ' samples' : ''"></p>
            </td>
            <td class="px-4 py-3 text-xs text-gray-800 max-w-xs">
              <p class="line-clamp-2" x-text="r.title || '—'"></p>
            </td>
            <td class="px-4 py-3 text-xs text-center" x-text="r.n_samples || '—'"></td>
            <td class="px-4 py-3 text-xs text-gray-500 truncate max-w-xs" x-text="r.gse_type || '—'"></td>
            <td class="px-4 py-3 text-xs text-gray-500" x-text="r.pubdate || '—'"></td>
            <td class="px-4 py-3 text-xs text-gray-500" x-text="r.update_date || '—'"></td>
            <td class="px-4 py-3 text-center">
              <span x-show="r.has_raw_data" class="text-green-500 text-base">✓</span>
              <span x-show="!r.has_raw_data" class="text-gray-300 text-base">—</span>
            </td>
            <td class="px-4 py-3">
              <span :class="decisionClass(r.decision)"
                    class="text-xs font-semibold px-2 py-0.5 rounded-full" x-text="r.decision || '—'"></span>
            </td>
            <td class="px-4 py-3 text-xs text-blue-600 cursor-pointer"
                x-text="expanded.has(r.id) ? '收起' : '展开'"></td>
          </tr>
          <!-- Expanded panel -->
          <tr x-show="expanded.has(r.id)" class="bg-slate-50">
            <td colspan="9" class="px-4 py-4">
              <!-- Labels section -->
              <div class="mb-4" x-data="labelEditor(r.id, r.dataset_id)" x-init="loadLabels()">
                <p class="text-xs font-semibold text-gray-500 mb-2">标注</p>
                <div class="flex flex-wrap gap-2 mb-2">
                  <template x-for="lbl in labels" :key="lbl.key">
                    <div class="flex items-center gap-1 bg-white border rounded-lg px-2 py-1 text-xs">
                      <span class="text-gray-500" x-text="lbl.key + ':'"></span>
                      <span x-show="!lbl.editing" :class="lbl.source==='human' ? 'text-blue-700 font-medium' : 'text-gray-700'"
                            x-text="lbl.value || '—'"></span>
                      <input x-show="lbl.editing" x-model="lbl.editVal" @keydown.enter="saveLabel(lbl)"
                             @keydown.escape="lbl.editing=false"
                             class="border-b border-blue-400 outline-none text-xs w-24 px-1" />
                      <button @click="lbl.editing ? saveLabel(lbl) : (lbl.editing=true, lbl.editVal=lbl.value)"
                              class="text-gray-400 hover:text-blue-600 ml-1"
                              x-text="lbl.editing ? '✓' : '✎'"></button>
                    </div>
                  </template>
                </div>
              </div>
              <!-- GSM samples table -->
              <div x-show="r.samples && r.samples.length > 0">
                <p class="text-xs font-semibold text-gray-500 mb-2">样本列表 (GSM)</p>
                <table class="w-full text-xs border rounded-lg overflow-hidden">
                  <thead class="bg-gray-100">
                    <tr>
                      <th class="text-left px-3 py-2 font-medium text-gray-600">样本名称</th>
                      <th class="text-left px-3 py-2 font-medium text-gray-600">标题</th>
                      <th class="text-left px-3 py-2 font-medium text-gray-600">生物体</th>
                      <th class="text-left px-3 py-2 font-medium text-gray-600">生物样本关系ID</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y bg-white">
                    <template x-for="s in r.samples" :key="s.gsm_id">
                      <tr>
                        <td class="px-3 py-2 font-mono text-blue-700" x-text="s.gsm_id"></td>
                        <td class="px-3 py-2 text-gray-700" x-text="s.title || '—'"></td>
                        <td class="px-3 py-2 text-gray-500" x-text="s.organism || '—'"></td>
                        <td class="px-3 py-2 text-blue-600" x-text="s.biosample_id || '—'"></td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>
              <!-- LLM summary -->
              <div x-show="r.summary" class="mt-3">
                <p class="text-xs font-semibold text-gray-500 mb-1">筛选摘要</p>
                <p class="text-xs text-gray-600" x-text="r.summary"></p>
              </div>
            </td>
          </tr>
          </>
        </template>
      </tbody>
    </table>
    <div x-show="results.length === 0 && !loading" class="text-center text-gray-400 py-8 text-sm">暂无结果</div>
  </div>

  <!-- Pagination -->
  <div class="flex justify-between items-center mt-4 text-sm">
    <button @click="prevPage()" :disabled="page <= 1"
            class="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40">← Prev</button>
    <span class="text-gray-400" x-text="'第 ' + page + ' 页，共 ' + totalPages + ' 页'"></span>
    <button @click="nextPage()" :disabled="page >= totalPages"
            class="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40">Next →</button>
  </div>
</div>

<script>
  function taskDetailPage(taskId) {
    return {
      taskId, task: {}, results: [], loading: true,
      page: 1, pageSize: 20, total: 0, expanded: new Set(),
      decisionFilter: '', annotating: false, pollTimer: null,

      async init() {
        await this.loadTask();
        await this.loadResults();
        if (this.task.status === 'running' || this.task.status === 'pending') {
          this.pollTimer = setInterval(() => this.poll(), 3000);
        }
      },
      async loadTask() {
        const r = await fetch('/tasks/' + this.taskId);
        if (r.ok) this.task = await r.json();
      },
      async loadResults() {
        this.loading = true;
        const params = new URLSearchParams({page: this.page, page_size: this.pageSize});
        if (this.decisionFilter) params.set('decision', this.decisionFilter);
        const r = await fetch(`/tasks/${this.taskId}/results?` + params.toString());
        if (r.ok) { const d = await r.json(); this.results = d.items; this.total = d.total; }
        this.loading = false;
      },
      async reloadResults() { this.page = 1; await this.loadResults(); },
      async poll() {
        await this.loadTask();
        await this.loadResults();
        if (this.task.status !== 'running' && this.task.status !== 'pending') clearInterval(this.pollTimer);
      },
      async triggerAnnotation() {
        this.annotating = true;
        await fetch(`/annotate/tasks/${this.taskId}/run`, {method: 'POST'});
        this.annotating = false;
      },
      get totalPages() { return Math.max(1, Math.ceil(this.total / this.pageSize)); },
      async prevPage() { if (this.page > 1) { this.page--; await this.loadResults(); } },
      async nextPage() { if (this.page < this.totalPages) { this.page++; await this.loadResults(); } },
      toggleExpand(id) {
        if (this.expanded.has(id)) this.expanded.delete(id); else this.expanded.add(id);
        this.expanded = new Set(this.expanded);
      },
      statusClass(s) {
        return {pending:'bg-gray-100 text-gray-600',running:'bg-blue-100 text-blue-700',
                done:'bg-green-100 text-green-700',error:'bg-red-100 text-red-700'}[s]||'bg-gray-100 text-gray-600';
      },
      decisionClass(d) {
        return {include:'bg-green-100 text-green-700',exclude:'bg-red-100 text-red-700',
                uncertain:'bg-yellow-100 text-yellow-700'}[d]||'bg-gray-100 text-gray-500';
      }
    }
  }

  function labelEditor(resultId, datasetId) {
    return {
      resultId, datasetId, labels: [],
      async loadLabels() {
        const r = await fetch(`/annotate/results/${this.resultId}/labels`);
        if (r.ok) {
          const data = await r.json();
          this.labels = data.map(l => ({...l, editing: false, editVal: l.value}));
        }
      },
      async saveLabel(lbl) {
        const r = await fetch(`/annotate/results/${this.resultId}/labels`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({key: lbl.key, value: lbl.editVal}),
        });
        if (r.ok) {
          const updated = await r.json();
          lbl.value = updated.value;
          lbl.source = updated.source;
          lbl.editing = false;
        }
      }
    }
  }
</script>
{% endblock %}
```

- [ ] Step 3: Run page tests:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/test_pages.py -v
```
Expected: all PASS.

- [ ] Step 4: Run full suite:
```bash
PYTHONPATH=. conda run -n autofigure pytest backend/tests/ -q
```
Expected: all PASS, 0 warnings about TemplateResponse.

- [ ] Step 5: Commit:
```bash
git add frontend/templates/tasks_detail.html frontend/templates/tasks_new.html
git commit -m "feat: redesign task detail with GSE table, GSM panel, and inline label editing"
```

- [ ] Step 6: Final commit and push:
```bash
git push
```
