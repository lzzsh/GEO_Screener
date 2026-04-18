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
        # Resolve actual user id
        from backend.database import AsyncSessionLocal
        from backend.models import User
        import sqlalchemy
        async with AsyncSessionLocal() as db:
            user = (await db.execute(
                sqlalchemy.select(User).where(User.username == "annuser")
            )).scalar_one()
            client._ann_user_id = user.id
        yield client


@pytest.mark.asyncio
async def test_get_labels_empty(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="ann_task", source="geo", criteria_text="", owner_id=auth_client._ann_user_id,
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
        task = ScreeningTask(name="ann_task2", source="geo", criteria_text="", owner_id=auth_client._ann_user_id,
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
        task = ScreeningTask(name="ann_task3", source="geo", criteria_text="find iPSC", owner_id=auth_client._ann_user_id)
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
            owner_id=auth_client._ann_user_id,
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
async def test_trigger_single_result_annotation_runs_inline(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult

    async with AsyncSessionLocal() as db:
        task = ScreeningTask(
            name="single_result_task",
            source="geo",
            criteria_text="find iPSC",
            owner_id=auth_client._ann_user_id,
            label_schema='["起始细胞类型"]',
        )
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_SINGLE")
        db.add(sr)
        await db.commit()
        result_id = sr.id

    with patch("backend.routers.annotate.dispatch_or_run_inline", return_value="running_inline") as dispatch_mock:
        r = await auth_client.post(f"/annotate/results/{result_id}/run")

    assert r.status_code == 200
    assert r.json() == {"status": "running_inline"}
    dispatch_mock.assert_called_once()
    assert dispatch_mock.call_args.kwargs["delay_call"] is None


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
            owner_id=auth_client._ann_user_id,
            label_schema='["起始细胞类型","分化体系"]',
        )
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE777", title="Test", description="desc", has_raw_data=True)
        db.add(sr)
        await db.flush()
        db.add(GeoSample(result_id=sr.id, gsm_id="GSMOLD", title="stored sample", organism="Homo sapiens"))
        db.add(LLMConfig(owner_id=auth_client._ann_user_id, provider="deepseek", api_key="sk-test", model="deepseek-chat"))
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
        task = ScreeningTask(name="gsm_model_task", source="geo", criteria_text="", owner_id=auth_client._ann_user_id)
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


@pytest.mark.asyncio
async def test_run_gsm_annotation_async_persists_labels(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, GsmLabel, LLMConfig
    from backend.worker.tasks import _run_gsm_annotation_async
    from unittest.mock import AsyncMock, MagicMock, patch
    import sqlalchemy

    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="gsm_ann_task", source="geo", criteria_text="", owner_id=auth_client._ann_user_id)
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_ANN1",
                             description="iPSC differentiation study")
        db.add(sr)
        await db.flush()
        sample = GeoSample(result_id=sr.id, gsm_id="GSM_ANN1",
                           title="Day 10 iPSC", organism="Homo sapiens", biosample_id="SAMN001")
        db.add(sample)
        existing_cfg = (await db.execute(
            __import__("sqlalchemy").select(LLMConfig).where(LLMConfig.owner_id == auth_client._ann_user_id)
        )).scalar_one_or_none()
        if not existing_cfg:
            db.add(LLMConfig(owner_id=auth_client._ann_user_id, provider="deepseek", api_key="sk-test2", model="deepseek-chat"))
        await db.commit()
        result_id = sr.id
        sample_id = sample.id

    mock_llm = MagicMock()
    mock_llm.annotate_gsm = AsyncMock(return_value={
        "细胞来源": "iPSC",
        "分化终点": "神经细胞",
        "分化时间点": "D10",
        "是否有原始数据": "是",
        "gsm_available": "可用",
    })
    with patch("backend.worker.tasks.LLMClient", return_value=mock_llm):
        await _run_gsm_annotation_async(result_id)

    async with AsyncSessionLocal() as db:
        labels = (await db.execute(
            sqlalchemy.select(GsmLabel).where(GsmLabel.sample_id == sample_id).order_by(GsmLabel.key)
        )).scalars().all()

    label_map = {l.key: l.value for l in labels}
    assert label_map["细胞来源"] == "iPSC"
    assert label_map["gsm_available"] == "可用"
    assert all(l.source == "llm" for l in labels)


@pytest.mark.asyncio
async def test_gsm_label_api_get_put_and_trigger(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, LLMConfig
    from unittest.mock import patch

    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="gsm_api_task", source="geo", criteria_text="", owner_id=auth_client._ann_user_id)
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_API1")
        db.add(sr)
        await db.flush()
        sample = GeoSample(result_id=sr.id, gsm_id="GSM_API1", title="API sample")
        db.add(sample)
        from sqlalchemy import select as sa_select
        existing_cfg = (await db.execute(sa_select(LLMConfig).where(LLMConfig.owner_id == auth_client._ann_user_id))).scalar_one_or_none()
        if not existing_cfg:
            db.add(LLMConfig(owner_id=auth_client._ann_user_id, provider="deepseek", api_key="sk-api", model="deepseek-chat"))
        await db.commit()
        result_id = sr.id
        sample_id = sample.id

    # GET labels — empty
    r = await auth_client.get(f"/annotate/samples/{sample_id}/labels")
    assert r.status_code == 200
    assert r.json() == []

    # PUT label — human
    r = await auth_client.put(f"/annotate/samples/{sample_id}/labels",
                               json={"key": "细胞来源", "value": "iPSC"})
    assert r.status_code == 200
    assert r.json()["source"] == "human"
    assert r.json()["value"] == "iPSC"

    # GET labels — now has one
    r = await auth_client.get(f"/annotate/samples/{sample_id}/labels")
    assert len(r.json()) == 1

    # POST trigger
    with patch("backend.routers.annotate.dispatch_or_run_inline", return_value="queued") as m:
        r = await auth_client.post(f"/annotate/results/{result_id}/gsm-labels/run")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    m.assert_called_once()
