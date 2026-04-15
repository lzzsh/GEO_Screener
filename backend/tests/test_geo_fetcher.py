import pytest
from unittest.mock import AsyncMock, patch

from backend.worker.geo_fetcher import _efetch_summaries, search_geo

@pytest.mark.asyncio
async def test_search_geo_returns_list():
    mock_search = AsyncMock(return_value=["200012345"])
    mock_fetch = AsyncMock(return_value=[{"id": "GSE12345", "title": "Test", "summary": "A study", "organism": "Homo sapiens", "n_samples": 10}])
    with patch("backend.worker.geo_fetcher._esearch", mock_search), \
         patch("backend.worker.geo_fetcher._efetch_summaries", mock_fetch):
        results = await search_geo("cancer RNA-seq")
    assert len(results) == 1
    assert results[0]["id"] == "GSE12345"
    mock_search.assert_awaited_once_with("cancer RNA-seq", 20)

@pytest.mark.asyncio
async def test_search_geo_empty_query():
    mock_search = AsyncMock(return_value=[])
    with patch("backend.worker.geo_fetcher._esearch", mock_search):
        results = await search_geo("xyznonexistent12345")
    assert results == []


@pytest.mark.asyncio
async def test_search_geo_accepts_large_retmax():
    mock_search = AsyncMock(return_value=["1"])
    mock_fetch = AsyncMock(return_value=[{"id": "GSE1", "title": "Test", "summary": "A study"}])
    with patch("backend.worker.geo_fetcher._esearch", mock_search), \
         patch("backend.worker.geo_fetcher._efetch_summaries", mock_fetch):
        await search_geo("liver cancer", retmax=10000)
    mock_search.assert_awaited_once_with("liver cancer", 10000)


@pytest.mark.asyncio
async def test_efetch_summaries_batches_large_id_lists():
    ids = [str(i) for i in range(250)]
    seen_batches = []

    class FakeResponse:
        def __init__(self, batch_ids):
            self._batch_ids = batch_ids

        def raise_for_status(self):
            return None

        def json(self):
            result = {uid: {"accession": f"GSE{uid}", "title": f"Title {uid}", "summary": f"Summary {uid}"} for uid in self._batch_ids}
            return {"result": result}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            batch_ids = params["id"].split(",")
            seen_batches.append(batch_ids)
            return FakeResponse(batch_ids)

    with patch("backend.worker.geo_fetcher.httpx.AsyncClient", return_value=FakeClient()):
        results = await _efetch_summaries(ids)

    assert len(seen_batches) == 3
    assert [len(batch) for batch in seen_batches] == [100, 100, 50]
    assert [result["id"] for result in results] == [f"GSE{uid}" for uid in ids]
