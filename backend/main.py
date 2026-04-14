from contextlib import asynccontextmanager
from fastapi import FastAPI
from backend.database import init_db
from backend.routers import auth as auth_router
from backend.routers import criteria as criteria_router
from backend.routers import llm as llm_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(auth_router.router)
app.include_router(criteria_router.router)
app.include_router(llm_router.router)
