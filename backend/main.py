import os
from contextlib import asynccontextmanager
from pathlib import Path
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
from backend.routers import annotate as annotate_router

BASE_DIR = Path(__file__).resolve().parent.parent
frontend_dir_value = os.getenv("FRONTEND_DIR", "frontend")
FRONTEND_DIR = Path(frontend_dir_value)
if not FRONTEND_DIR.is_absolute():
    FRONTEND_DIR = (BASE_DIR / FRONTEND_DIR).resolve()

templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="GEO Search & Screening", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

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
async def task_detail_page(request: Request, task_id: int):
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

app.include_router(auth_router.router)
app.include_router(criteria_router.router)
app.include_router(llm_router.router)
app.include_router(tasks_router.router)
app.include_router(geo_router.router)
app.include_router(annotate_router.router)
