import json
import pytest
import httpx
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
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=[])), \
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

    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask
    async with AsyncSessionLocal() as db:
        task = await db.get(ScreeningTask, r.json()["id"])
        assert json.loads(task.label_schema) == ["数据模态", "分化起点", "扰动类型", "分化体系", "分化终点", "数据平台", "是否提供原始测序数据"]


@pytest.mark.asyncio
async def test_list_and_get_task(auth_client):
    geo_candidates = [{"id": "GSE003", "title": "Candidate three", "summary": "human blood data"}]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=[])), \
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
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=[])), \
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


@pytest.mark.asyncio
async def test_create_geo_task_persists_gsm_samples(auth_client):
    geo_candidates = [
        {"id": "GSE001", "title": "Study one", "summary": "iPSC study",
         "gse_type": "Expression profiling by high throughput sequencing",
         "pubdate": "2026/01/01", "update_date": "2026/04/14",
         "has_raw_data": True, "n_samples": 2, "organism": "Homo sapiens"},
    ]
    gsm_samples = [
        {"gsm_id": "GSM001", "title": "Sample 1", "organism": "Homo sapiens", "biosample_id": "SAMN001"},
        {"gsm_id": "GSM002", "title": "Sample 2", "organism": "Homo sapiens", "biosample_id": "SAMN002"},
    ]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=gsm_samples)), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await auth_client.post("/tasks", params={
            "name": "GSM Test",
            "criteria_text": "human iPSC",
            "source": "geo",
            "search_query": "iPSC liver",
            "label_schema": '["起始细胞类型","分化体系"]',
        })
    assert r.status_code == 201
    task_id = r.json()["id"]

    results_r = await auth_client.get(f"/tasks/{task_id}/results")
    items = results_r.json()["items"]
    assert len(items) == 1
    assert items[0]["gse_type"] == "Expression profiling by high throughput sequencing"
    assert items[0]["has_raw_data"] is True
    # GSM samples are no longer fetched at task creation time (fetched on-demand during annotation)
    assert items[0]["n_samples"] == 2


@pytest.mark.asyncio
async def test_task_results_include_labels(auth_client):
    geo_candidates = [{"id": "GSE777", "title": "Study one", "summary": "iPSC study"}]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=[])), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await auth_client.post("/tasks", params={
            "name": "Labels Test",
            "criteria_text": "human iPSC",
            "source": "geo",
            "search_query": "iPSC liver",
        })
    task_id = r.json()["id"]

    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningResult, GeoLabel
    async with AsyncSessionLocal() as db:
        result = (await db.execute(
            __import__("sqlalchemy").select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalar_one()
        db.add(GeoLabel(result_id=result.id, key="起始细胞类型", value="iPSC", source="llm"))
        await db.commit()

    results_r = await auth_client.get(f"/tasks/{task_id}/results")
    items = results_r.json()["items"]
    assert items[0]["labels"] == [{"key": "起始细胞类型", "value": "iPSC", "source": "llm"}]


@pytest.mark.asyncio
async def test_delete_task_removes_owned_task_and_related_rows(auth_client):
    geo_candidates = [{"id": "GSE778", "title": "Study delete", "summary": "iPSC study"}]
    gsm_samples = [
        {"gsm_id": "GSM778", "title": "Sample delete", "organism": "Homo sapiens", "biosample_id": "SAMN778"},
    ]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=gsm_samples)), \
         patch("backend.worker.tasks.run_screening.delay"):
        created = await auth_client.post("/tasks", params={
            "name": "Delete Test",
            "criteria_text": "human iPSC",
            "source": "geo",
            "search_query": "iPSC delete",
        })
    task_id = created.json()["id"]

    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningResult, GeoLabel, GeoSample
    async with AsyncSessionLocal() as db:
        result = (await db.execute(
            __import__("sqlalchemy").select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalar_one()
        result_id = result.id
        db.add(GeoLabel(result_id=result_id, key="数据模态", value="scRNA-seq", source="llm"))
        await db.commit()

    deleted = await auth_client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted"}

    assert (await auth_client.get(f"/tasks/{task_id}")).status_code == 404
    listed = await auth_client.get("/tasks")
    assert all(task["id"] != task_id for task in listed.json())

    async with AsyncSessionLocal() as db:
        remaining_results = (await db.execute(
            __import__("sqlalchemy").select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalars().all()
        remaining_samples = (await db.execute(
            __import__("sqlalchemy").select(GeoSample).where(GeoSample.result_id == result_id)
        )).scalars().all()
        remaining_labels = (await db.execute(
            __import__("sqlalchemy").select(GeoLabel).where(GeoLabel.result_id == result_id)
        )).scalars().all()
    assert remaining_results == []
    assert remaining_samples == []
    assert remaining_labels == []


@pytest.mark.asyncio
async def test_create_geo_task_survives_gsm_fetch_failure(auth_client):
    geo_candidates = [
        {"id": "GSE900", "title": "Paper one", "summary": "human liver cohort"},
    ]
    request = httpx.Request("GET", "https://eutils.ncbi.nlm.nih.gov/example")
    response = httpx.Response(status_code=429, request=request)
    fetch_error = httpx.HTTPStatusError("rate limited", request=request, response=response)

    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(side_effect=fetch_error)), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await auth_client.post("/tasks", params={
            "name": "Graceful Task",
            "criteria_text": "criteria",
            "source": "geo",
            "search_query": "liver fibrosis",
        })

    assert r.status_code == 201
    assert r.json()["candidate_count"] == 1


@pytest.mark.asyncio
async def test_create_geo_task_returns_success_when_dispatch_falls_back(auth_client):
    geo_candidates = [{"id": "GSE901", "title": "Paper one", "summary": "human liver cohort"}]

    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=[])), \
         patch("backend.routers.tasks.dispatch_or_run_inline", return_value="running_inline") as dispatch_mock:
        r = await auth_client.post("/tasks", params={
            "name": "Inline Screening Task",
            "criteria_text": "criteria",
            "source": "geo",
            "search_query": "liver fibrosis",
        })

    assert r.status_code == 201
    assert r.json()["candidate_count"] == 1
    dispatch_mock.assert_called_once()


@pytest.mark.asyncio
async def test_export_available_csv(auth_client):
    geo_candidates = [
        {"id": "GSE100", "title": "Study include", "summary": "human iPSC data"},
        {"id": "GSE101", "title": "Study exclude", "summary": "mouse only"},
        {"id": "GSE102", "title": "Study uncertain", "summary": "unclear origin"},
    ]
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.routers.tasks.fetch_gsm_samples", new=AsyncMock(return_value=[])), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await auth_client.post("/tasks", params={
            "name": "Export Test",
            "criteria_text": "human iPSC",
            "source": "geo",
            "search_query": "iPSC",
        })
    task_id = r.json()["id"]

    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningResult
    import sqlalchemy
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            sqlalchemy.select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalars().all()
        rows[0].decision = "include"
        rows[0].summary = "human iPSC data"
        rows[0].status = "done"
        rows[1].decision = "exclude"
        rows[1].summary = "mouse only"
        rows[1].status = "done"
        rows[2].decision = "uncertain"
        rows[2].summary = "unclear origin"
        rows[2].status = "done"
        await db.commit()

    export_r = await auth_client.get(f"/tasks/{task_id}/export")
    assert export_r.status_code == 200
    assert "text/csv" in export_r.headers["content-type"]

    import csv, io
    reader = csv.DictReader(io.StringIO(export_r.text.lstrip('\ufeff')))
    rows_out = list(reader)
    assert len(rows_out) == 3

    by_gse = {row["gse_id"]: row for row in rows_out}
    assert by_gse["GSE100"]["available"] == "true"
    assert by_gse["GSE100"]["reason"] == "human iPSC data"
    assert by_gse["GSE101"]["available"] == "false"
    assert by_gse["GSE101"]["reason"] == "mouse only"
    assert by_gse["GSE102"]["available"] == "unknown"
    assert by_gse["GSE102"]["reason"] == "unclear origin"
