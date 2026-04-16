import asyncio
import re
import httpx
import xml.etree.ElementTree as ET

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_RETRIES = 3
ESUMMARY_BATCH_SIZE = 100
ACCESSION_RE = re.compile(r"^(GSE|GSM|GDS)\d+$", re.IGNORECASE)
BIOSAMPLE_RE = re.compile(r"^SAM[A-Z0-9]+\d+$", re.IGNORECASE)


async def search_geo(query: str, retmax: int = 20) -> list[dict]:
    """Search GEO datasets. Returns enriched list with GSE metadata."""
    ids = await _esearch("gds", _normalize_geo_query(query), retmax, retstart=0)
    if not ids:
        return []
    return await _efetch_gse_summaries(ids)


async def search_geo_page(query: str, retmax: int = 10000, page: int = 1, page_size: int = 100) -> dict:
    normalized_query = _normalize_geo_query(query)
    offset = max(0, (page - 1) * page_size)
    ids, total = await _esearch_with_count("gds", normalized_query, retmax=min(page_size, retmax), retstart=offset)
    capped_total = min(total, retmax)
    if offset >= capped_total:
        ids = []
    items = await _efetch_gse_summaries(ids) if ids else []
    return {
        "query": query,
        "retmax": retmax,
        "total": capped_total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


async def fetch_gsm_samples(gse_accession: str, retmax: int = 1000) -> list[dict]:
    """Fetch all GSM samples for a given GSE accession."""
    query = f"{gse_accession}[Accession] AND gsm[EntryType]"
    ids = await _esearch("gds", query, retmax, retstart=0)
    if not ids:
        return []
    return await _efetch_gsm_summaries(ids)


def _normalize_geo_query(query: str) -> str:
    cleaned = query.strip()
    if not cleaned:
        return cleaned

    tokens = [token for token in re.split(r"[\s,]+", cleaned) if token]
    if tokens and all(ACCESSION_RE.fullmatch(token) for token in tokens):
        return " OR ".join(f'"{token.upper()}"[Accession]' for token in tokens)
    if tokens and all(BIOSAMPLE_RE.fullmatch(token) for token in tokens):
        return " OR ".join(f'"{token.upper()}"' for token in tokens)
    return cleaned


async def _esearch(db: str, query: str, retmax: int, retstart: int = 0) -> list[str]:
    ids, _ = await _esearch_with_count(db, query, retmax, retstart=retstart)
    return ids


async def _esearch_with_count(db: str, query: str, retmax: int, retstart: int = 0) -> tuple[list[str], int]:
    url = f"{NCBI_BASE}/esearch.fcgi"
    params = {"db": db, "term": query, "retmax": retmax, "retstart": retstart, "retmode": "json"}
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                payload = r.json()["esearchresult"]
                return payload["idlist"], int(payload.get("count", 0))
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return [], 0


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


def _parse_miniml(xml_text: str, gse_id: str) -> dict:
    """Parse MINiML XML and extract GSE detail fields."""
    NS = "http://www.ncbi.nlm.nih.gov/geo/info/MINiML"
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"gse_id": gse_id}

    series = root.find(f"{{{NS}}}Series")
    if series is None:
        return {"gse_id": gse_id}

    # BioProject ID
    bioproject_id = ""
    bioproject_link = ""
    for rel in series.findall(f"{{{NS}}}Relation"):
        if rel.get("type") == "BioProject":
            target = rel.get("target", "")
            if "/bioproject/" in target:
                bioproject_id = target.split("/bioproject/")[-1]
            bioproject_link = target

    # Abstract and Overall Design
    abstract_el = series.find(f"{{{NS}}}Summary")
    abstract = abstract_el.text.strip() if abstract_el is not None and abstract_el.text else ""

    od_el = series.find(f"{{{NS}}}Overall-Design")
    overall_design = od_el.text.strip() if od_el is not None and od_el.text else ""

    # Supplementary files
    suppl_files = []
    for suppl in series.findall(f"{{{NS}}}Supplementary-Data"):
        url = suppl.text.strip() if suppl.text else ""
        if url:
            name = url.split("/")[-1]
            suppl_files.append({"name": name, "url": url})

    # Contact info
    contact_ref = series.find(f"{{{NS}}}Contact-Ref")
    contact = {}
    if contact_ref is not None:
        ref_id = contact_ref.get("ref", "")
        for contrib in root.findall(f"{{{NS}}}Contributor"):
            if contrib.get("iid") == ref_id:
                person = contrib.find(f"{{{NS}}}Person")
                first = last = ""
                if person is not None:
                    first_el = person.find(f"{{{NS}}}First")
                    last_el = person.find(f"{{{NS}}}Last")
                    first = first_el.text.strip() if first_el is not None and first_el.text else ""
                    last = last_el.text.strip() if last_el is not None and last_el.text else ""

                email_el = contrib.find(f"{{{NS}}}Email")
                email = email_el.text.strip() if email_el is not None and email_el.text else ""

                dept_el = contrib.find(f"{{{NS}}}Department")
                department = dept_el.text.strip() if dept_el is not None and dept_el.text else ""

                org = contrib.find(f"{{{NS}}}Organization")
                address = city = state = zip_code = country = ""
                if org is not None:
                    addr_el = org.find(f"{{{NS}}}Address")
                    city_el = org.find(f"{{{NS}}}City")
                    state_el = org.find(f"{{{NS}}}State")
                    zip_el = org.find(f"{{{NS}}}Zip-Code")
                    country_el = org.find(f"{{{NS}}}Country")
                    address = addr_el.text.strip() if addr_el is not None and addr_el.text else ""
                    city = city_el.text.strip() if city_el is not None and city_el.text else ""
                    state = state_el.text.strip() if state_el is not None and state_el.text else ""
                    zip_code = zip_el.text.strip() if zip_el is not None and zip_el.text else ""
                    country = country_el.text.strip() if country_el is not None and country_el.text else ""

                contact = {
                    "name": f"{first} {last}".strip(),
                    "email": email,
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "country": country,
                    "department": department,
                }
                break

    return {
        "gse_id": gse_id,
        "bioproject_id": bioproject_id,
        "bioproject_link": bioproject_link,
        "abstract": abstract,
        "overall_design": overall_design,
        "contact": contact,
        "supplementary_files": suppl_files,
    }


async def fetch_gse_detail(gse_id: str) -> dict:
    """Fetch full GSE detail via eFetch MINiML format."""
    ids = await _esearch("gds", f'"{gse_id}"[Accession] AND gse[EntryType]', retmax=1)
    if not ids:
        return {"gse_id": gse_id}

    url = f"{NCBI_BASE}/efetch.fcgi"
    params = {"db": "gds", "id": ids[0], "rettype": "miniml", "retmode": "xml"}

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return _parse_miniml(r.text, gse_id)
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return {"gse_id": gse_id}
