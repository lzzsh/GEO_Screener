import pytest
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_register_and_login():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/auth/register", json={"username": "bob", "email": "bob@test.com", "password": "secret"})
        assert r.status_code == 201
        r2 = await client.post("/auth/login", json={"username": "bob", "password": "secret"})
        assert r2.status_code == 200
        assert "access_token" in r2.json()

@pytest.mark.asyncio
async def test_login_wrong_password():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/register", json={"username": "carol", "email": "carol@test.com", "password": "right"})
        r = await client.post("/auth/login", json={"username": "carol", "password": "wrong"})
        assert r.status_code == 401
