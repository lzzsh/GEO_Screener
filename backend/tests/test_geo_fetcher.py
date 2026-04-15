import pytest
from unittest.mock import AsyncMock, patch, MagicMock

MOCK_ESEARCH = {"esearchresult": {"idlist": ["200305128"]}}

MOCK_ESUMMARY = {
    "result": {
        "200305128": {
            "accession": "GSE305128",
            "title": "PreciCE study",
            "summary": "iPSC differentiation study",
            "taxon": "Homo sapiens",
            "n_samples": 3,
            "gse": "GSE305128",
            "entrytype": "GSE",
            "gdstype": "Expression profiling by high throughput sequencing",
            "pdat": "2026/04/01",
            "update_date": "2026/04/14",
            "ftplink": "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE305nnn/GSE305128/",
        }
    }
}

MOCK_GSM_ESEARCH = {"esearchresult": {"idlist": ["9162575", "9162576"]}}

MOCK_GSM_ESUMMARY = {
    "result": {
        "9162575": {
            "accession": "GSM9162575",
            "title": "Experiment 23-001",
            "organism": "Homo sapiens",
            "biosample": "SAMN50564034",
        },
        "9162576": {
            "accession": "GSM9162576",
            "title": "Experiment 23-006",
            "organism": "Homo sapiens",
            "biosample": "SAMN50564033",
        },
    }
}


@pytest.mark.asyncio
async def test_search_geo_returns_enriched_fields():
    from backend.worker.geo_fetcher import search_geo

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        if "esearch" in url:
            m.json.return_value = MOCK_ESEARCH
        else:
            m.json.return_value = MOCK_ESUMMARY
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        results = await search_geo("iPSC", retmax=10)

    assert len(results) == 1
    r = results[0]
    assert r["id"] == "GSE305128"
    assert r["gse_type"] == "Expression profiling by high throughput sequencing"
    assert r["pubdate"] == "2026/04/01"
    assert r["update_date"] == "2026/04/14"
    assert r["has_raw_data"] is True
    assert r["n_samples"] == 3


@pytest.mark.asyncio
async def test_fetch_gsm_samples():
    from backend.worker.geo_fetcher import fetch_gsm_samples

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        if "esearch" in url:
            m.json.return_value = MOCK_GSM_ESEARCH
        else:
            m.json.return_value = MOCK_GSM_ESUMMARY
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        samples = await fetch_gsm_samples("GSE305128")

    assert len(samples) == 2
    assert samples[0]["gsm_id"] == "GSM9162575"
    assert samples[0]["organism"] == "Homo sapiens"
    assert samples[0]["biosample_id"] == "SAMN50564034"
