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

@app.get("/")
async def root():
    return RedirectResponse(url="/tasks-list")

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/tasks/new")
async def tasks_new_page(request: Request):
    return templates.TemplateResponse("tasks_new.html", {"request": request})

@app.get("/tasks/{task_id}/detail")
async def task_detail_page(request: Request, task_id: int):
    return templates.TemplateResponse("tasks_detail.html", {"request": request, "task_id": task_id})

@app.get("/tasks-list")
async def tasks_page(request: Request):
    return templates.TemplateResponse("tasks.html", {"request": request})

@app.get("/criteria-page")
async def criteria_page(request: Request):
    return templates.TemplateResponse("criteria.html", {"request": request})

@app.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

app.include_router(auth_router.router)
app.include_router(criteria_router.router)
app.include_router(llm_router.router)
app.include_router(tasks_router.router)
app.include_router(geo_router.router)
