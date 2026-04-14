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
