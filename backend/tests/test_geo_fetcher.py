import pytest
from unittest.mock import AsyncMock, patch
from backend.worker.geo_fetcher import search_geo

@pytest.mark.asyncio
async def test_search_geo_returns_list():
    mock_search = AsyncMock(return_value=["200012345"])
    mock_fetch = AsyncMock(return_value=[{"id": "GSE12345", "title": "Test", "summary": "A study", "organism": "Homo sapiens", "n_samples": 10}])
    with patch("backend.worker.geo_fetcher._esearch", mock_search), \
         patch("backend.worker.geo_fetcher._efetch_summaries", mock_fetch):
        results = await search_geo("cancer RNA-seq")
    assert len(results) == 1
    assert results[0]["id"] == "GSE12345"

@pytest.mark.asyncio
async def test_search_geo_empty_query():
    mock_search = AsyncMock(return_value=[])
    with patch("backend.worker.geo_fetcher._esearch", mock_search):
        results = await search_geo("xyznonexistent12345")
    assert results == []
