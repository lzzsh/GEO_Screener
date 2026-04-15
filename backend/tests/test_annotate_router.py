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

    r2 = await auth_client.put(f"/annotate/results/{result_id}/labels", json={
        "key": "起始细胞类型", "value": "ESC"
    })
    assert r2.json()["value"] == "ESC"
    assert r2.json()["source"] == "human"
