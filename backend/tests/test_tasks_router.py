import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch


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
