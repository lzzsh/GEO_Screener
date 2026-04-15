"""
End-to-end smoke test: register → login → create criteria → create GEO task →
poll until done (mocked LLM) → fetch results → export CSV.
"""
import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock


def _mock_llm_response():
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = json.dumps({
        "decision": "include", "confidence": 0.9,
        "summary": "Meets all criteria", "rule_checks": {"human": True}
    })
    return mock_resp


@pytest.fixture
async def client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_full_workflow(client):
    # 1. Register
    r = await client.post("/auth/register", json={"username": "smokeuser", "email": "smoke@test.com", "password": "pw123"})
    assert r.status_code == 201

    # 2. Login
    r = await client.post("/auth/login", json={"username": "smokeuser", "password": "pw123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    # 3. Create criteria
    r = await client.post("/criteria", json={"name": "Human RCT", "criteria_text": "Must be human RCT"})
    assert r.status_code == 201
    criteria_id = r.json()["id"]

    # 4. Get criteria
    r = await client.get(f"/criteria/{criteria_id}")
    assert r.json()["name"] == "Human RCT"

    # 5. Update LLM config
    r = await client.put("/llm/config", json={"provider": "deepseek", "api_key": "sk-fake", "model": "deepseek-chat"})
    assert r.status_code == 200

    geo_candidates = [
        {"id": "GSE001", "title": "Study one", "summary": "Human RCT in liver tissue"},
        {"id": "GSE002", "title": "Study two", "summary": "Mouse exploratory study"},
        {"id": "GSE003", "title": "Study three", "summary": "Human validation cohort"},
    ]

    # 6. Create GEO task (mock Celery dispatch)
    with patch("backend.routers.tasks.search_geo", new=AsyncMock(return_value=geo_candidates)), \
         patch("backend.worker.tasks.run_screening.delay"):
        r = await client.post("/tasks", params={
            "name": "Smoke Test Task",
            "criteria_text": "Must be human RCT",
            "source": "geo",
            "search_query": "human RCT liver",
        })
    assert r.status_code == 201
    task_id = r.json()["id"]
    assert r.json()["total"] == 3
    assert r.json()["candidate_count"] == 3

    # 7. Simulate worker running (call internal async function directly)
    mock_resp = _mock_llm_response()
    with patch("openai.resources.chat.completions.AsyncCompletions.create", new=AsyncMock(return_value=mock_resp)):
        from backend.worker.tasks import _run_screening_async
        await _run_screening_async(task_id)

    # 8. Poll task — should be done
    r = await client.get(f"/tasks/{task_id}")
    assert r.json()["status"] == "done"
    assert r.json()["processed"] == 3
    assert r.json()["candidate_count"] == 3
    assert r.json()["included_count"] == 3

    # 9. Fetch results
    r = await client.get(f"/tasks/{task_id}/results")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3
    assert all(i["decision"] == "include" for i in items)
    assert all(i["keyword_matched"] is True for i in items)

    # 10. Export CSV
    r = await client.get(f"/tasks/{task_id}/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().split("\n")
    assert len(lines) == 4  # header + 3 rows

    # 11. Logout
    r = await client.post("/auth/logout")
    assert r.status_code == 200
