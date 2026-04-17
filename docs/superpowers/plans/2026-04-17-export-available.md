# Export Available CSV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the task export endpoint to output a simplified CSV with `gse_id`, `title`, `available` (true/false/unknown), and `reason` columns.

**Architecture:** The existing `GET /tasks/{task_id}/export` endpoint in `backend/routers/tasks.py` is modified to map `decision` values (`include`→`true`, `exclude`→`false`, `uncertain`→`unknown`) and use `summary` as the reason. No new files needed.

**Tech Stack:** FastAPI, SQLAlchemy, Python csv module

---

### Task 1: Modify export endpoint (already done)

**Files:**
- Modify: `backend/routers/tasks.py:233-238`

- [x] **Step 1: Replace CSV columns in export_results**

The endpoint at line 223 now outputs:

```python
decision_map = {"include": "true", "exclude": "false", "uncertain": "unknown"}
output = io.StringIO()
writer = csv.writer(output)
writer.writerow(["gse_id", "title", "available", "reason"])
for r in rows:
    available = decision_map.get(r.decision, "unknown")
    writer.writerow([r.dataset_id, r.title, available, r.summary or ""])
```

- [x] **Step 2: Verify change is in place**

Run: `grep -n "available" backend/routers/tasks.py`
Expected: lines showing `available` column header and `decision_map`

---

### Task 2: Add test for export format

**Files:**
- Modify: `backend/tests/test_tasks_router.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_tasks_router.py`:

```python
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
    reader = csv.DictReader(io.StringIO(export_r.text))
    rows_out = list(reader)
    assert len(rows_out) == 3

    by_gse = {row["gse_id"]: row for row in rows_out}
    assert by_gse["GSE100"]["available"] == "true"
    assert by_gse["GSE100"]["reason"] == "human iPSC data"
    assert by_gse["GSE101"]["available"] == "false"
    assert by_gse["GSE101"]["reason"] == "mouse only"
    assert by_gse["GSE102"]["available"] == "unknown"
    assert by_gse["GSE102"]["reason"] == "unclear origin"
```

- [ ] **Step 2: Run test to verify it fails first**

Run: `pytest backend/tests/test_tasks_router.py::test_export_available_csv -v`
Expected: FAIL (test not yet in file)

- [ ] **Step 3: Run test after adding it**

Run: `pytest backend/tests/test_tasks_router.py::test_export_available_csv -v`
Expected: PASS

- [ ] **Step 4: Run full test suite to check for regressions**

Run: `pytest backend/tests/test_tasks_router.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/tasks.py backend/tests/test_tasks_router.py
git commit -m "feat: export task results as available/reason CSV"
```
