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
