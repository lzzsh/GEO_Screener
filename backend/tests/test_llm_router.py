import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

@pytest.fixture
async def auth_client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/register", json={"username": "llmuser", "email": "llm@test.com", "password": "pw"})
        r = await client.post("/auth/login", json={"username": "llmuser", "password": "pw"})
        client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield client

@pytest.mark.asyncio
async def test_get_and_update_config(auth_client):
    r = await auth_client.get("/llm/config")
    assert r.status_code == 200
    r2 = await auth_client.put("/llm/config", json={"provider": "glm", "model": "glm-4", "api_key": "sk-test"})
    assert r2.json()["provider"] == "glm"
    assert r2.json()["api_key"] == "***"
