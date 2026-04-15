import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def auth_client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/register", json={"username": "geouser", "email": "geo@test.com", "password": "pw"})
        login = await client.post("/auth/login", json={"username": "geouser", "password": "pw"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client


@pytest.mark.asyncio
async def test_geo_search_returns_paginated_metadata(auth_client):
    candidates = [
        {"id": f"GSE{i:05d}", "title": f"Study {i}", "summary": f"Summary {i}"}
        for i in range(1, 106)
    ]
    with patch("backend.routers.geo.fetch_geo_candidates", new=AsyncMock(return_value=candidates)):
        response = await auth_client.get("/geo/search", params={"q": "liver fibrosis", "retmax": 10000, "page": 2, "page_size": 25})

    assert response.status_code == 200
    payload = response.json()
    assert payload["retmax"] == 10000
    assert payload["total"] == 105
    assert payload["page"] == 2
    assert payload["page_size"] == 25
    assert len(payload["items"]) == 25
    assert payload["items"][0]["id"] == "GSE00026"


@pytest.mark.asyncio
async def test_geo_search_accepts_post_body_for_complex_queries(auth_client):
    candidates = [
        {"id": "GSE00001", "title": "Study 1", "summary": "Summary 1"},
        {"id": "GSE00002", "title": "Study 2", "summary": "Summary 2"},
    ]
    complex_query = '(iPSC OR "induced pluripotent stem cell" OR ESC OR "embryonic stem cell" OR PSC) AND (differentiation OR organoid)'

    with patch("backend.routers.geo.fetch_geo_candidates", new=AsyncMock(return_value=candidates)) as mock_fetch:
        response = await auth_client.post(
            "/geo/search",
            json={"q": complex_query, "retmax": 10000, "page": 1, "page_size": 1},
        )

    assert response.status_code == 200
    mock_fetch.assert_awaited_once_with(complex_query, retmax=10000)
    payload = response.json()
    assert payload["query"] == complex_query
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "GSE00001"
