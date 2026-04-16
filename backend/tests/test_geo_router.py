import pytest
import httpx
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
    payload = {
        "query": "liver fibrosis",
        "retmax": 10000,
        "total": 105,
        "page": 2,
        "page_size": 25,
        "items": candidates[25:50],
    }
    with patch("backend.routers.geo.search_geo_page", new=AsyncMock(return_value=payload)):
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
    payload = {
        "query": complex_query,
        "retmax": 10000,
        "total": 2,
        "page": 1,
        "page_size": 1,
        "items": candidates[:1],
    }

    with patch("backend.routers.geo.search_geo_page", new=AsyncMock(return_value=payload)) as mock_fetch:
        response = await auth_client.post(
            "/geo/search",
            json={"q": complex_query, "retmax": 10000, "page": 1, "page_size": 1},
        )

    assert response.status_code == 200
    mock_fetch.assert_awaited_once_with(complex_query, retmax=10000, page=1, page_size=1)
    payload = response.json()
    assert payload["query"] == complex_query
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "GSE00001"


@pytest.mark.asyncio
async def test_geo_search_returns_json_error_when_ncbi_rate_limits(auth_client):
    request = httpx.Request("GET", "https://eutils.ncbi.nlm.nih.gov/example")
    response = httpx.Response(status_code=429, request=request)
    err = httpx.HTTPStatusError("rate limited", request=request, response=response)

    with patch("backend.routers.geo.search_geo_page", new=AsyncMock(side_effect=err)):
        response = await auth_client.post(
            "/geo/search",
            json={"q": "iPSC", "retmax": 10000, "page": 1, "page_size": 50},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "NCBI rate limit reached. Please retry in a moment."


@pytest.mark.asyncio
async def test_gse_detail_returns_parsed_miniml_data(auth_client):
    detail_data = {
        "gse_id": "GSE305128",
        "bioproject_id": "PRJNA123456",
        "bioproject_link": "https://www.ncbi.nlm.nih.gov/bioproject/PRJNA123456",
        "abstract": "Test abstract",
        "overall_design": "Test design",
        "contact": {
            "name": "John Doe",
            "email": "john@example.com",
            "address": "123 Main St",
            "city": "Boston",
            "state": "MA",
            "zip": "02101",
            "country": "USA",
            "department": "Biology",
        },
        "supplementary_files": [
            {"name": "file1.txt", "url": "https://example.com/file1.txt"}
        ],
    }
    with patch("backend.routers.geo.fetch_gse_detail", new=AsyncMock(return_value=detail_data)):
        response = await auth_client.get("/geo/gse/GSE305128/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["gse_id"] == "GSE305128"
    assert payload["bioproject_id"] == "PRJNA123456"
    assert payload["abstract"] == "Test abstract"
    assert payload["contact"]["name"] == "John Doe"
    assert len(payload["supplementary_files"]) == 1
