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
    assert response.headers["location"] == "/search"


@pytest.mark.asyncio
async def test_page_routes_return_html():
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ["/login", "/search", "/tasks-list", "/tasks/new", "/tasks/1/detail", "/criteria-page", "/settings"]:
            response = await client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_library_pages_return_html():
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/library", headers={"accept": "text/html"})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

        detail_response = await client.get("/library/1")
        assert detail_response.status_code == 200
        assert "text/html" in detail_response.headers["content-type"]


@pytest.mark.asyncio
async def test_gsm_detail_counts_only_avail_labels(monkeypatch):
    import backend.main as main_module
    from backend.database import AsyncSessionLocal
    from backend.main import app
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, GsmLabel, User

    async with AsyncSessionLocal() as db:
        user = User(username="gsm_page_user", email="gsm_page@test.com", hashed_password="h")
        db.add(user)
        await db.flush()

        task = ScreeningTask(
            name="gsm page task",
            source="geo",
            criteria_text="",
            owner_id=user.id,
            task_type="gsm_annotation",
            total=1,
        )
        db.add(task)
        await db.flush()

        result = ScreeningResult(task_id=task.id, dataset_id="GSEPAGE", title="Page test", n_samples=2)
        db.add(result)
        await db.flush()

        sample_with_avail = GeoSample(result_id=result.id, gsm_id="GSMAVAIL", title="Done")
        sample_partial = GeoSample(result_id=result.id, gsm_id="GSMPARTIAL", title="Partial")
        db.add_all([sample_with_avail, sample_partial])
        await db.flush()

        db.add(GsmLabel(sample_id=sample_with_avail.id, key="avail", value="true", source="llm"))
        db.add(GsmLabel(sample_id=sample_partial.id, key="response", value="partial only", source="llm"))
        await db.commit()
        task_id = task.id

    async def fake_resolve_current_user(**_kwargs):
        return user

    monkeypatch.setattr(main_module, "resolve_current_user", fake_resolve_current_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/tasks/{task_id}/detail")

    assert response.status_code == 200
    assert '<p class="text-2xl font-semibold text-green-700">1</p>' in response.text
    assert '<td class="px-4 py-3 text-xs text-center">1</td>' in response.text


@pytest.mark.asyncio
async def test_search_and_task_detail_include_library_actions():
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        search_response = await client.get("/search")
        assert "文献库" in search_response.text
        assert "存入文献库" in search_response.text
        assert "支持关键词、GSE/GSM accession、BioSample ID" in search_response.text
        assert "跳至页码" in search_response.text
        assert "清空搜索" in search_response.text
        assert 'rows="5"' in search_response.text
        assert "min-h-[128px]" in search_response.text
        assert "table-fixed" in search_response.text
        assert "width:38%" in search_response.text
        assert "break-words" in search_response.text
        assert "Submission date" in search_response.text
        assert "item.pubdate || '—'" in search_response.text
        assert "sortBy('pubdate')" in search_response.text
        assert "sortedAllItems" in search_response.text
        assert "sortIndicator" in search_response.text
        assert "text-sm uppercase tracking-wide" in search_response.text
        assert "text-sm font-medium text-gray-900" in search_response.text
        assert "text-sm text-gray-500" in search_response.text
        assert "px-4 py-3 text-left text-sm font-medium text-gray-600\">操作" in search_response.text
        assert "retmax: 1000" in search_response.text
        assert "visiblePaginationItems" in search_response.text
        assert "第 <span x-text=\"page\"></span> 页，共 <span x-text=\"totalPages\"></span> 页" in search_response.text

        task_response = await client.get("/tasks/1/detail")
        assert "存入文献库" in task_response.text
        assert "visiblePaginationItems" in task_response.text
        assert "第 <span x-text=\"page\"></span> 页，共 <span x-text=\"totalPages\"></span> 页" in task_response.text
        assert "跳至页码" in task_response.text
        assert "<template x-for=\"r in results\" :key=\"r.id\">\n          <tbody>" not in task_response.text
        assert "annotationError" in task_response.text
        assert "无标题数据集" in task_response.text
        assert "已标注 " in task_response.text

        library_response = await client.get("/library/1")
        assert "visiblePaginationItems" in library_response.text
        assert "第 <span x-text=\"page\"></span> 页，共 <span x-text=\"totalPages\"></span> 页" in library_response.text
        assert "跳至页码" in library_response.text
