import asyncio
import httpx
from typing import Optional

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_RETRIES = 3

async def search_geo(query: str, retmax: int = 20) -> list[dict]:
    """Search GEO datasets via NCBI eutils. Returns list of {id, title, summary}."""
    ids = await _esearch(query, retmax)
    if not ids:
        return []
    return await _efetch_summaries(ids)

async def _esearch(query: str, retmax: int) -> list[str]:
    url = f"{NCBI_BASE}/esearch.fcgi"
    params = {"db": "gds", "term": query, "retmax": retmax, "retmode": "json"}
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return r.json()["esearchresult"]["idlist"]
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return []

async def _efetch_summaries(ids: list[str]) -> list[dict]:
    url = f"{NCBI_BASE}/esummary.fcgi"
    params = {"db": "gds", "id": ",".join(ids), "retmode": "json"}
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
                results = []
                for uid in ids:
                    doc = data.get("result", {}).get(uid, {})
                    results.append({
                        "id": doc.get("accession", uid),
                        "title": doc.get("title", ""),
                        "summary": doc.get("summary", ""),
                        "organism": doc.get("taxon", ""),
                        "n_samples": doc.get("n_samples", 0),
                    })
                return results
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return []
