import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_root_redirects_to_tasks_list():
    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/")

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/tasks-list"


@pytest.mark.asyncio
async def test_page_routes_return_html():
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ["/login", "/tasks-list", "/tasks/new", "/tasks/1/detail", "/criteria-page", "/settings"]:
            response = await client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
