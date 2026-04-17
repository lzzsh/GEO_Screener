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
            "updatedate": "2026/04/14",
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
    xml = '''<?xml version="1.0"?>
<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML">
  <Sample iid="GSM9162575">
    <Accession>GSM9162575</Accession>
    <Title>Experiment 23-001</Title>
    <Channel>
      <Organism>Homo sapiens</Organism>
    </Channel>
    <Relation type="BioSample" target="https://www.ncbi.nlm.nih.gov/biosample/SAMN50564034"/>
  </Sample>
  <Sample iid="GSM9162576">
    <Accession>GSM9162576</Accession>
    <Title>Experiment 23-006</Title>
    <Channel>
      <Organism>Homo sapiens</Organism>
    </Channel>
    <Relation type="BioSample" target="https://www.ncbi.nlm.nih.gov/biosample/SAMN50564033"/>
  </Sample>
</MINiML>'''

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.text = xml
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


@pytest.mark.asyncio
async def test_search_geo_normalizes_accession_queries():
    from backend.worker.geo_fetcher import search_geo

    with patch("backend.worker.geo_fetcher._esearch", new=AsyncMock(return_value=["200305128"])) as mock_esearch, \
         patch("backend.worker.geo_fetcher._efetch_gse_summaries", new=AsyncMock(return_value=[])):
        await search_geo("GSE305128", retmax=10)

    mock_esearch.assert_awaited_once_with("gds", '"GSE305128"[Accession]', 10, retstart=0)


@pytest.mark.asyncio
async def test_search_geo_normalizes_biosample_queries():
    from backend.worker.geo_fetcher import search_geo

    with patch("backend.worker.geo_fetcher._esearch", new=AsyncMock(return_value=["9162575"])) as mock_esearch, \
         patch("backend.worker.geo_fetcher._efetch_gse_summaries", new=AsyncMock(return_value=[])):
        await search_geo("SAMN50564034", retmax=10)

    mock_esearch.assert_awaited_once_with("gds", '"SAMN50564034"', 10, retstart=0)


@pytest.mark.asyncio
async def test_parse_miniml_extracts_all_fields():
    from backend.worker.geo_fetcher import _parse_miniml

    xml = '''<?xml version="1.0"?>
<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML">
  <Contributor iid="contrib1">
    <Person><First>Jens</First><Last>Magnusson</Last></Person>
    <Email>jens@test.com</Email>
    <Department>Biosciences</Department>
    <Organization>
      <Address>Alfred Nobels Allé 8</Address>
      <City>Stockholm</City>
      <Zip-Code>14152</Zip-Code>
      <Country>Sweden</Country>
    </Organization>
  </Contributor>
  <Series iid="GSE305128">
    <Summary>Test abstract</Summary>
    <Overall-Design>Test design</Overall-Design>
    <Contact-Ref ref="contrib1"/>
    <Supplementary-Data type="TAR">ftp://test.com/file.tar</Supplementary-Data>
    <Relation type="BioProject" target="https://www.ncbi.nlm.nih.gov/bioproject/PRJNA1304480"/>
    <Relation type="SuperSeries of" target="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE111"/>
    <Relation type="SubSeries of" target="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222"/>
  </Series>
</MINiML>'''

    result = _parse_miniml(xml, "GSE305128")
    assert result["gse_id"] == "GSE305128"
    assert result["bioproject_id"] == "PRJNA1304480"
    assert result["abstract"] == "Test abstract"
    assert result["overall_design"] == "Test design"
    assert result["contact"]["name"] == "Jens Magnusson"
    assert result["contact"]["email"] == "jens@test.com"
    assert result["contact"]["city"] == "Stockholm"
    assert len(result["supplementary_files"]) == 1
    assert result["supplementary_files"][0]["name"] == "file.tar"
    assert result["series_relations"] == [
        {"type": "SuperSeries of", "accession": "GSE111", "target": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE111"},
        {"type": "SubSeries of", "accession": "GSE222", "target": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222"},
    ]


@pytest.mark.asyncio
async def test_fetch_gsm_samples_extracts_sample_characteristics():
    from backend.worker.geo_fetcher import fetch_gsm_samples

    xml = '''<?xml version="1.0"?>
<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML">
  <Sample iid="GSM001">
    <Accession>GSM001</Accession>
    <Title>Day 10 cardiomyocyte sample</Title>
    <Channel>
      <Source>human iPSC-derived cardiomyocytes</Source>
      <Organism>Homo sapiens</Organism>
      <Characteristics tag="cell type">iPSC-derived cardiomyocyte</Characteristics>
      <Characteristics tag="time point">day 10</Characteristics>
      <Molecule>polyA RNA</Molecule>
    </Channel>
    <Library-Strategy>RNA-Seq</Library-Strategy>
    <Growth-Protocol>in vitro directed differentiation</Growth-Protocol>
    <Relation type="BioSample" target="https://www.ncbi.nlm.nih.gov/biosample/SAMN001"/>
  </Sample>
</MINiML>'''

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.text = xml
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        samples = await fetch_gsm_samples("GSE001")

    assert samples == [{
        "gsm_id": "GSM001",
        "title": "Day 10 cardiomyocyte sample",
        "organism": "Homo sapiens",
        "biosample_id": "SAMN001",
        "source_name": "human iPSC-derived cardiomyocytes",
        "characteristics": {"cell type": "iPSC-derived cardiomyocyte", "time point": "day 10"},
        "molecule": "polyA RNA",
        "library_strategy": "RNA-Seq",
        "growth_protocol": "in vitro directed differentiation",
        "treatment_protocol": "",
    }]


@pytest.mark.asyncio
async def test_fetch_gse_detail_calls_efetch():
    from backend.worker.geo_fetcher import fetch_gse_detail

    mock_xml = '''<?xml version="1.0"?>
<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML">
  <Contributor iid="c1"><Person><First>Test</First></Person></Contributor>
  <Series iid="GSE123"><Summary>Test</Summary><Contact-Ref ref="c1"/></Series>
</MINiML>'''

    async def mock_get(url, params=None, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.text = mock_xml
        return m

    with patch("backend.worker.geo_fetcher._esearch", new=AsyncMock(return_value=["123"])), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_gse_detail("GSE123")

    assert result["gse_id"] == "GSE123"
    assert "contact" in result
