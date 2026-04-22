import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import Cookie, Depends, FastAPI, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from backend.database import init_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from backend.auth import resolve_current_user
from backend.database import get_db
from backend.models import Library, ScreeningTask, ScreeningResult, GeoSample, GsmLabel
from backend.routers import auth as auth_router
from backend.routers import criteria as criteria_router
from backend.routers import llm as llm_router
from backend.routers import tasks as tasks_router
from backend.routers import geo as geo_router
from backend.routers import annotate as annotate_router
from backend.routers import library as library_router

BASE_DIR = Path(__file__).resolve().parent.parent
frontend_dir_value = os.getenv("FRONTEND_DIR", "frontend")
FRONTEND_DIR = Path(frontend_dir_value)
if not FRONTEND_DIR.is_absolute():
    FRONTEND_DIR = (BASE_DIR / FRONTEND_DIR).resolve()

templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="GEO Search & Screening", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

import os as _os
_os.makedirs("pdfs", exist_ok=True)
app.mount("/pdfs", StaticFiles(directory="pdfs"), name="pdfs")

@app.get("/")
async def root():
    return RedirectResponse(url="/search")

@app.get("/search")
async def search_page(request: Request):
    return templates.TemplateResponse(request, "search.html")

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.get("/tasks/new")
async def tasks_new_page(request: Request):
    return templates.TemplateResponse(request, "tasks_new.html")

@app.get("/tasks/{task_id}/detail")
async def task_detail_page(
    request: Request,
    task_id: int,
    token: Optional[str] = Depends(oauth2_scheme),
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException as _HTTPException
    try:
        user = await resolve_current_user(token=token, access_token=access_token, db=db)
    except _HTTPException:
        return templates.TemplateResponse(request, "tasks_detail.html", {"task_id": task_id})

    task = (await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )).scalar_one_or_none()

    if task and task.task_type == "gsm_annotation":
        # Load results with samples and their gsm labels
        results_rows = (await db.execute(
            select(ScreeningResult)
            .where(ScreeningResult.task_id == task_id)
            .options(
                selectinload(ScreeningResult.samples).selectinload(GeoSample.labels)
            )
        )).scalars().all()

        total_samples = sum(len(r.samples) for r in results_rows)
        annotated_samples = sum(
            1 for r in results_rows for s in r.samples if s.labels
        )
        available_count = sum(
            1 for r in results_rows for s in r.samples
            if any(l.key == "avail" and l.value == "True" for l in s.labels)
        )

        results_data = []
        for r in results_rows:
            annotated_count = sum(1 for s in r.samples if s.labels)
            samples_data = [
                {
                    "id": s.id,
                    "gsm_id": s.gsm_id,
                    "title": s.title,
                    "organism": s.organism,
                    "labels": {l.key: l.value for l in s.labels},
                }
                for s in r.samples
            ]
            results_data.append({
                "id": r.id,
                "dataset_id": r.dataset_id,
                "title": r.title,
                "n_samples": r.n_samples,
                "decision": r.decision,
                "annotated_count": annotated_count,
                "samples": samples_data,
            })

        task_data = {
            "id": task.id,
            "name": task.name,
            "status": task.status,
            "total": task.total,
            "task_type": task.task_type,
        }
        return templates.TemplateResponse(request, "gsm_task_detail.html", {
            "task": task_data,
            "total_samples": total_samples,
            "annotated_samples": annotated_samples,
            "available_count": available_count,
            "results": results_data,
        })

    return templates.TemplateResponse(request, "tasks_detail.html", {"task_id": task_id})

@app.get("/tasks-list")
async def tasks_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html")

@app.get("/criteria-page")
async def criteria_page(request: Request):
    return templates.TemplateResponse(request, "criteria.html")

@app.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html")


@app.get("/library")
async def library_list_page(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html:
        return templates.TemplateResponse(request, "library_list.html")

    user = await resolve_current_user(token=token, access_token=access_token, db=db)
    rows = (
        await db.execute(
            select(Library)
            .where(Library.owner_id == user.id)
            .order_by(Library.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "search_query": row.search_query,
            "created_at": row.created_at,
        }
        for row in rows
    ]

app.include_router(auth_router.router)
app.include_router(criteria_router.router)
app.include_router(llm_router.router)
app.include_router(tasks_router.router)
app.include_router(geo_router.router)
app.include_router(annotate_router.router)
app.include_router(library_router.router)

@app.get("/library/{library_id}")
async def library_detail_page(request: Request, library_id: int):
    return templates.TemplateResponse(request, "library_detail.html", {"library_id": library_id})
