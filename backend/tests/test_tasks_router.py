import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


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
    geo_candidates = [
        {"id": "GSE001", "title": "Paper one", "summary": "human liver cohort"},
        {"id": "GSE002", "title": "Paper two", "summary": "mouse control cohort"},
    ]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.worker.tasks.run_screening.delay") as delay_mock:
        r = await auth_client.post("/tasks", params={
            "name": "Test Task",
            "criteria_text": "Must mention human samples",
            "source": "geo",
            "search_query": "liver fibrosis",
        })
    assert r.status_code == 201
    assert r.json()["total"] == 2
    assert r.json()["candidate_count"] == 2
    delay_mock.assert_called_once()


@pytest.mark.asyncio
async def test_list_and_get_task(auth_client):
    geo_candidates = [{"id": "GSE003", "title": "Candidate three", "summary": "human blood data"}]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await auth_client.post("/tasks", params={
            "name": "List Test",
            "criteria_text": "criteria",
            "source": "geo",
            "search_query": "blood biomarker",
        })
    task_id = r.json()["id"]
    r2 = await auth_client.get("/tasks")
    assert any(t["id"] == task_id for t in r2.json())
    r3 = await auth_client.get(f"/tasks/{task_id}")
    assert r3.json()["id"] == task_id
    assert r3.json()["candidate_count"] == 1
    assert r3.json()["included_count"] == 0
    assert r3.json()["excluded_count"] == 0
    assert r3.json()["uncertain_count"] == 0


@pytest.mark.asyncio
async def test_filter_task_results_by_decision(auth_client):
    geo_candidates = [
        {"id": "GSE010", "title": "Candidate one", "summary": "human cohort"},
        {"id": "GSE011", "title": "Candidate two", "summary": "mouse cohort"},
    ]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.worker.tasks.run_screening.delay"):
        created = await auth_client.post("/tasks", params={
            "name": "Filter Test",
            "criteria_text": "must be human",
            "source": "geo",
            "search_query": "immune cohort",
        })
    task_id = created.json()["id"]

    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningResult
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            __import__("sqlalchemy").select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalars().all()
        rows[0].decision = "include"
        rows[0].status = "done"
        rows[0].rule_checks = json.dumps({"human": True})
        rows[1].decision = "exclude"
        rows[1].status = "done"
        rows[1].rule_checks = json.dumps({"human": False})
        await db.commit()

    filtered = await auth_client.get(f"/tasks/{task_id}/results", params={"decision": "include"})
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["items"][0]["dataset_id"] == "GSE010"
