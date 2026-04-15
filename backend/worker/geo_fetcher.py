import asyncio
import httpx

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_RETRIES = 3
ESUMMARY_BATCH_SIZE = 100


async def search_geo(query: str, retmax: int = 20) -> list[dict]:
    """Search GEO datasets. Returns enriched list with GSE metadata."""
    ids = await _esearch("gds", query, retmax)
    if not ids:
        return []
    return await _efetch_gse_summaries(ids)


async def fetch_gsm_samples(gse_accession: str, retmax: int = 1000) -> list[dict]:
    """Fetch all GSM samples for a given GSE accession."""
    query = f"{gse_accession}[Accession] AND gsm[EntryType]"
    ids = await _esearch("gds", query, retmax)
    if not ids:
        return []
    return await _efetch_gsm_summaries(ids)


async def _esearch(db: str, query: str, retmax: int) -> list[str]:
    url = f"{NCBI_BASE}/esearch.fcgi"
    params = {"db": db, "term": query, "retmax": retmax, "retmode": "json"}
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return r.json()["esearchresult"]["idlist"]
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return []


async def _efetch_gse_summaries(ids: list[str]) -> list[dict]:
    url = f"{NCBI_BASE}/esummary.fcgi"
    async with httpx.AsyncClient(timeout=30) as client:
        results = []
        for start in range(0, len(ids), ESUMMARY_BATCH_SIZE):
            batch_ids = ids[start:start + ESUMMARY_BATCH_SIZE]
            params = {"db": "gds", "id": ",".join(batch_ids), "retmode": "json"}
            for attempt in range(MAX_RETRIES):
                try:
                    r = await client.get(url, params=params)
                    r.raise_for_status()
                    data = r.json()
                    for uid in batch_ids:
                        doc = data.get("result", {}).get(uid, {})
                        results.append({
                            "id": doc.get("accession", uid),
                            "title": doc.get("title", ""),
                            "summary": doc.get("summary", ""),
                            "organism": doc.get("taxon", ""),
                            "n_samples": doc.get("n_samples", 0),
                            "gse_type": doc.get("gdstype", ""),
                            "pubdate": doc.get("pdat", ""),
                            "update_date": doc.get("update_date", ""),
                            "has_raw_data": bool(doc.get("ftplink", "")),
                        })
                    break
                except (httpx.HTTPStatusError, httpx.TimeoutException):
                    if attempt == MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)
        return results


async def _efetch_gsm_summaries(ids: list[str]) -> list[dict]:
    url = f"{NCBI_BASE}/esummary.fcgi"
    async with httpx.AsyncClient(timeout=30) as client:
        results = []
        for start in range(0, len(ids), ESUMMARY_BATCH_SIZE):
            batch_ids = ids[start:start + ESUMMARY_BATCH_SIZE]
            params = {"db": "gds", "id": ",".join(batch_ids), "retmode": "json"}
            for attempt in range(MAX_RETRIES):
                try:
                    r = await client.get(url, params=params)
                    r.raise_for_status()
                    data = r.json()
                    for uid in batch_ids:
                        doc = data.get("result", {}).get(uid, {})
                        results.append({
                            "gsm_id": doc.get("accession", uid),
                            "title": doc.get("title", ""),
                            "organism": doc.get("organism", ""),
                            "biosample_id": doc.get("biosample", ""),
                        })
                    break
                except (httpx.HTTPStatusError, httpx.TimeoutException):
                    if attempt == MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)
        return results
