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
