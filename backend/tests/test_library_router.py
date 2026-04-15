import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def auth_client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/auth/register", json={"username": "libtest", "email": "libtest@test.com", "password": "pw"})
        r = await client.post("/auth/login", json={"username": "libtest", "password": "pw"})
        client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield client


@pytest.mark.asyncio
async def test_create_and_list_library(auth_client):
    r = await auth_client.post("/library", json={"name": "iPSC 2026", "search_query": "iPSC AND human"})
    assert r.status_code == 201
    lib_id = r.json()["id"]
    assert r.json()["name"] == "iPSC 2026"

    r2 = await auth_client.get("/library")
    assert any(l["id"] == lib_id for l in r2.json())


@pytest.mark.asyncio
async def test_save_entries_from_search(auth_client):
    r = await auth_client.post("/library", json={"name": "Test Lib"})
    lib_id = r.json()["id"]

    entries = [
        {"gse_id": "GSE001", "title": "Study 1", "organism": "Homo sapiens",
         "n_samples": 3, "gse_type": "Expression profiling", "has_raw_data": True,
         "summary": "iPSC study", "pubdate": "2026/01/01", "update_date": "2026/04/14"},
        {"gse_id": "GSE002", "title": "Study 2", "organism": "Homo sapiens",
         "n_samples": 5, "gse_type": "Expression profiling", "has_raw_data": False,
         "summary": "ESC study", "pubdate": "2026/02/01", "update_date": "2026/04/14"},
    ]
    r2 = await auth_client.post(f"/library/{lib_id}/entries", json={"entries": entries, "source": "search"})
    assert r2.status_code == 201
    assert r2.json()["added"] == 2

    r3 = await auth_client.get(f"/library/{lib_id}/entries")
    assert r3.status_code == 200
    assert len(r3.json()["items"]) == 2


@pytest.mark.asyncio
async def test_update_entry_status(auth_client):
    r = await auth_client.post("/library", json={"name": "Status Lib"})
    lib_id = r.json()["id"]
    entries = [{"gse_id": "GSE010", "title": "T", "organism": "Homo sapiens",
                "n_samples": 1, "gse_type": "", "has_raw_data": False, "summary": "", "pubdate": "", "update_date": ""}]
    await auth_client.post(f"/library/{lib_id}/entries", json={"entries": entries, "source": "search"})

    r2 = await auth_client.get(f"/library/{lib_id}/entries")
    entry_id = r2.json()["items"][0]["id"]

    r3 = await auth_client.patch(f"/library/{lib_id}/entries/{entry_id}", json={"status": "confirmed"})
    assert r3.status_code == 200
    assert r3.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_upsert_entry_label(auth_client):
    r = await auth_client.post("/library", json={"name": "Label Lib"})
    lib_id = r.json()["id"]
    entries = [{"gse_id": "GSE020", "title": "T", "organism": "Homo sapiens",
                "n_samples": 1, "gse_type": "", "has_raw_data": False, "summary": "", "pubdate": "", "update_date": ""}]
    await auth_client.post(f"/library/{lib_id}/entries", json={"entries": entries, "source": "search"})
    r2 = await auth_client.get(f"/library/{lib_id}/entries")
    entry_id = r2.json()["items"][0]["id"]

    r3 = await auth_client.put(f"/library/entries/{entry_id}/labels",
                                json={"key": "起始细胞类型", "value": "iPSC"})
    assert r3.status_code == 200
    assert r3.json()["value"] == "iPSC"
    assert r3.json()["source"] == "human"
