import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
async def auth_client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/register", json={"username": "annuser", "email": "ann@test.com", "password": "pw"})
        r = await client.post("/auth/login", json={"username": "annuser", "password": "pw"})
        client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield client


@pytest.mark.asyncio
async def test_get_labels_empty(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="ann_task", source="geo", criteria_text="", owner_id=1,
                             label_schema='["起始细胞类型"]')
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE999")
        db.add(sr)
        await db.commit()
        result_id = sr.id

    r = await auth_client.get(f"/annotate/results/{result_id}/labels")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_upsert_label_human(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="ann_task2", source="geo", criteria_text="", owner_id=1,
                             label_schema='["起始细胞类型"]')
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE998")
        db.add(sr)
        await db.commit()
        result_id = sr.id

    r = await auth_client.put(f"/annotate/results/{result_id}/labels", json={
        "key": "起始细胞类型", "value": "iPSC"
    })
    assert r.status_code == 200
    assert r.json()["source"] == "human"
    assert r.json()["value"] == "iPSC"

    r2 = await auth_client.put(f"/annotate/results/{result_id}/labels", json={
        "key": "起始细胞类型", "value": "ESC"
    })
    assert r2.json()["value"] == "ESC"
    assert r2.json()["source"] == "human"


@pytest.mark.asyncio
async def test_trigger_annotation_backfills_default_label_schema(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="ann_task3", source="geo", criteria_text="find iPSC", owner_id=1)
        db.add(task)
        await db.commit()
        task_id = task.id

    with patch("backend.worker.tasks.run_annotation.delay") as delay_mock:
        r = await auth_client.post(f"/annotate/tasks/{task_id}/run")

    assert r.status_code == 200
    assert r.json() == {"status": "queued"}
    delay_mock.assert_called_once_with(task_id)

    async with AsyncSessionLocal() as db:
        saved = await db.get(ScreeningTask, task_id)
        assert json.loads(saved.label_schema) == ["数据模态", "分化起点", "扰动类型", "分化体系", "分化终点", "数据平台", "是否提供原始测序数据"]


@pytest.mark.asyncio
async def test_trigger_annotation_returns_inline_status_when_dispatch_falls_back(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(
            name="ann_task4",
            source="geo",
            criteria_text="find iPSC",
            owner_id=1,
            label_schema='["起始细胞类型"]',
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    with patch("backend.routers.annotate.dispatch_or_run_inline", return_value="running_inline") as dispatch_mock:
        r = await auth_client.post(f"/annotate/tasks/{task_id}/run")

    assert r.status_code == 200
    assert r.json() == {"status": "running_inline"}
    dispatch_mock.assert_called_once()


@pytest.mark.asyncio
async def test_run_annotation_async_persists_labels_and_keeps_human_edits(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, LLMConfig, GeoLabel, GeoSample
    from backend.worker.tasks import _run_annotation_async

    async with AsyncSessionLocal() as db:
        task = ScreeningTask(
            name="ann_task5",
            source="geo",
            criteria_text="find iPSC",
            owner_id=1,
            label_schema='["起始细胞类型","分化体系"]',
        )
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE777", title="Test", description="desc", has_raw_data=True)
        db.add(sr)
        await db.flush()
        db.add(GeoSample(result_id=sr.id, gsm_id="GSMOLD", title="stored sample", organism="Homo sapiens"))
        db.add(LLMConfig(owner_id=1, provider="deepseek", api_key="sk-test", model="deepseek-chat"))
        db.add(GeoLabel(result_id=sr.id, key="起始细胞类型", value="human curated", source="human"))
        await db.commit()
        task_id = task.id
        result_id = sr.id

    mock_llm = MagicMock()
    mock_llm.extract_labels = AsyncMock(return_value={"起始细胞类型": "llm value", "分化体系": "3D organoid"})
    detail = {
        "abstract": "Detailed abstract",
        "overall_design": "Overall design says in vitro directed differentiation",
        "series_relations": [{"type": "SubSeries of", "accession": "GSESUPER", "target": "https://example.test/GSESUPER"}],
    }
    gsm_samples = [{
        "gsm_id": "GSMNEW",
        "title": "Day 10 sample",
        "organism": "Homo sapiens",
        "biosample_id": "SAMN001",
        "source_name": "human iPSC-derived cardiomyocytes",
        "characteristics": {"cell type": "iPSC-derived cardiomyocyte"},
        "library_strategy": "RNA-Seq",
        "growth_protocol": "in vitro differentiation",
    }]
    with patch("backend.worker.tasks.LLMClient", return_value=mock_llm), \
         patch("backend.worker.tasks.fetch_gse_detail", new=AsyncMock(return_value=detail)), \
         patch("backend.worker.tasks.fetch_gsm_samples", new=AsyncMock(return_value=gsm_samples)):
        await _run_annotation_async(task_id)

    description = mock_llm.extract_labels.await_args.kwargs["description"]
    assert "GEO Raw Data Availability: yes" in description
    assert "GSE Overall Design: Overall design says in vitro directed differentiation" in description
    assert "Series Relations: SubSeries of GSESUPER" in description
    assert "GSMNEW | Day 10 sample | Homo sapiens | human iPSC-derived cardiomyocytes" in description
    assert "cell type=iPSC-derived cardiomyocyte" in description

    async with AsyncSessionLocal() as db:
        labels = (await db.execute(
            __import__("sqlalchemy").select(GeoLabel).where(GeoLabel.result_id == result_id).order_by(GeoLabel.key)
        )).scalars().all()

    assert [(label.key, label.value, label.source) for label in labels] == [
        ("分化体系", "3D organoid", "llm"),
        ("起始细胞类型", "human curated", "human"),
    ]


@pytest.mark.asyncio
async def test_gsm_label_model_persists(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, GsmLabel
    import sqlalchemy
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="gsm_model_task", source="geo", criteria_text="", owner_id=1)
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_GSMTEST")
        db.add(sr)
        await db.flush()
        sample = GeoSample(result_id=sr.id, gsm_id="GSM_TEST1", title="Test sample")
        db.add(sample)
        await db.flush()
        db.add(GsmLabel(sample_id=sample.id, key="细胞来源", value="iPSC", source="llm"))
        await db.commit()
        sample_id = sample.id

    async with AsyncSessionLocal() as db:
        labels = (await db.execute(
            sqlalchemy.select(GsmLabel).where(GsmLabel.sample_id == sample_id)
        )).scalars().all()
    assert len(labels) == 1
    assert labels[0].key == "细胞来源"
    assert labels[0].value == "iPSC"
    assert labels[0].source == "llm"
