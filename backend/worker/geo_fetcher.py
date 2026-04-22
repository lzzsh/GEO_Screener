import asyncio
import re
import httpx
import xml.etree.ElementTree as ET

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_RETRIES = 3
ESUMMARY_BATCH_SIZE = 100
ACCESSION_RE = re.compile(r"^(GSE|GSM|GDS)\d+$", re.IGNORECASE)
BIOSAMPLE_RE = re.compile(r"^SAM[A-Z0-9]+\d+$", re.IGNORECASE)
GSE_RE = re.compile(r"GSE\d+", re.IGNORECASE)


def _text(el: ET.Element | None) -> str:
    return el.text.strip() if el is not None and el.text else ""


def _find_text(parent: ET.Element, ns: str, tag: str) -> str:
    return _text(parent.find(f"{{{ns}}}{tag}"))


def _relation_accession(target: str) -> str:
    match = GSE_RE.search(target or "")
    return match.group(0).upper() if match else ""


def _first_value(doc: dict, *keys: str):
    for key in keys:
        value = doc.get(key)
        if value not in (None, ""):
            return value
    return ""


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
    """Fetch all GSM samples for a given GSE accession via MINiML XML."""
    url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    params = {"acc": gse_accession, "targ": "gsm", "form": "xml", "view": "quick"}
    NS = "http://www.ncbi.nlm.nih.gov/geo/info/MINiML"

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                root = ET.fromstring(r.text)
                results = []
                for sample in root.findall(f"{{{NS}}}Sample"):
                    acc_el = sample.find(f"{{{NS}}}Accession")
                    gsm_id = acc_el.text.strip() if acc_el is not None and acc_el.text else ""
                    title_el = sample.find(f"{{{NS}}}Title")
                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    org_el = sample.find(f".//{{{NS}}}Organism")
                    organism = org_el.text.strip() if org_el is not None and org_el.text else ""
                    source_el = sample.find(f".//{{{NS}}}Source")
                    source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
                    molecule_el = sample.find(f".//{{{NS}}}Molecule")
                    molecule = molecule_el.text.strip() if molecule_el is not None and molecule_el.text else ""
                    library_strategy = _find_text(sample, NS, "Library-Strategy")
                    growth_protocol = _find_text(sample, NS, "Growth-Protocol")
                    treatment_protocol = _find_text(sample, NS, "Treatment-Protocol")
                    characteristics = {}
                    for char_el in sample.findall(f".//{{{NS}}}Characteristics"):
                        value = char_el.text.strip() if char_el.text else ""
                        if not value:
                            continue
                        key = char_el.get("tag") or "characteristic"
                        if key in characteristics:
                            characteristics[key] = f"{characteristics[key]}; {value}"
                        else:
                            characteristics[key] = value
                    biosample_id = ""
                    for rel in sample.findall(f"{{{NS}}}Relation"):
                        if rel.get("type") == "BioSample":
                            target = rel.get("target", "")
                            if "/biosample/" in target:
                                biosample_id = target.split("/biosample/")[-1]
                    results.append({
                        "gsm_id": gsm_id,
                        "title": title,
                        "organism": organism,
                        "biosample_id": biosample_id,
                        "source_name": source_name,
                        "characteristics": characteristics,
                        "molecule": molecule,
                        "library_strategy": library_strategy,
                        "growth_protocol": growth_protocol,
                        "treatment_protocol": treatment_protocol,
                    })
                return results
            except (httpx.HTTPStatusError, httpx.TimeoutException, ET.ParseError):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return []


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
                            "pubdate": _first_value(doc, "pdat", "pubdate", "PDAT"),
                            "update_date": _first_value(doc, "update_date", "updatedate", "updateDate", "UpdateDate"),
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
                            "organism": doc.get("taxon", ""),
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
    pmid = None
    series_relations = []
    for rel in series.findall(f"{{{NS}}}Relation"):
        rel_type = rel.get("type") or ""
        target = rel.get("target", "")
        if rel_type == "BioProject":
            if "/bioproject/" in target:
                bioproject_id = target.split("/bioproject/")[-1]
            bioproject_link = target
        elif "series" in rel_type.lower():
            series_relations.append({
                "type": rel_type,
                "accession": _relation_accession(target),
                "target": target,
            })
        elif rel_type == "PubMed":
            pmid = target.split("/")[-1] if "/" in target else target

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

    # Contact info — Contact-Ref points to the contributor iid
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

                org_el = contrib.find(f"{{{NS}}}Organization")
                organization = org_el.text.strip() if org_el is not None and org_el.text else ""

                # Address is a sub-element with Line, City, Postal-Code, Country, State
                addr_el = contrib.find(f"{{{NS}}}Address")
                line = city = state = zip_code = country = ""
                if addr_el is not None:
                    line_el = addr_el.find(f"{{{NS}}}Line")
                    city_el = addr_el.find(f"{{{NS}}}City")
                    state_el = addr_el.find(f"{{{NS}}}State")
                    zip_el = addr_el.find(f"{{{NS}}}Postal-Code") or addr_el.find(f"{{{NS}}}Zip-Code")
                    country_el = addr_el.find(f"{{{NS}}}Country")
                    line = line_el.text.strip() if line_el is not None and line_el.text else ""
                    city = city_el.text.strip() if city_el is not None and city_el.text else ""
                    state = state_el.text.strip() if state_el is not None and state_el.text else ""
                    zip_code = zip_el.text.strip() if zip_el is not None and zip_el.text else ""
                    country = country_el.text.strip() if country_el is not None and country_el.text else ""
                elif org_el is not None:
                    city = _find_text(org_el, NS, "City")
                    zip_code = _find_text(org_el, NS, "Postal-Code") or _find_text(org_el, NS, "Zip-Code")
                    country = _find_text(org_el, NS, "Country")

                contact = {
                    "name": f"{first} {last}".strip(),
                    "email": email,
                    "organization": organization,
                    "department": department,
                    "address": line,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "country": country,
                }
                break

    return {
        "gse_id": gse_id,
        "pmid": pmid,
        "bioproject_id": bioproject_id,
        "bioproject_link": bioproject_link,
        "abstract": abstract,
        "overall_design": overall_design,
        "series_relations": series_relations,
        "contact": contact,
        "supplementary_files": suppl_files,
    }


async def fetch_gsm_detail(gsm_id: str) -> dict:
    """Fetch full GSM detail via GEO MINiML XML endpoint."""
    url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    params = {"acc": gsm_id, "targ": "self", "form": "xml", "view": "quick"}
    NS = "http://www.ncbi.nlm.nih.gov/geo/info/MINiML"

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                root = ET.fromstring(r.text)
                sample = root.find(f"{{{NS}}}Sample")
                if sample is None:
                    return {"gsm_id": gsm_id}

                title = _find_text(sample, NS, "Title")
                sample_type = _find_text(sample, NS, "Type")

                status_el = sample.find(f"{{{NS}}}Status")
                submission_date = last_update_date = release_date = ""
                if status_el is not None:
                    submission_date = _find_text(status_el, NS, "Submission-Date")
                    last_update_date = _find_text(status_el, NS, "Last-Update-Date")
                    release_date = _find_text(status_el, NS, "Release-Date")

                channel = sample.find(f"{{{NS}}}Channel")
                organism = source_name = molecule = growth_protocol = treatment_protocol = extraction_protocol = ""
                characteristics: dict = {}
                if channel is not None:
                    org_el = channel.find(f"{{{NS}}}Organism")
                    organism = org_el.text.strip() if org_el is not None and org_el.text else ""
                    source_el = channel.find(f"{{{NS}}}Source")
                    source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
                    molecule_el = channel.find(f"{{{NS}}}Molecule")
                    molecule = molecule_el.text.strip() if molecule_el is not None and molecule_el.text else ""
                    growth_protocol = _find_text(channel, NS, "Growth-Protocol")
                    treatment_protocol = _find_text(channel, NS, "Treatment-Protocol")
                    extraction_protocol = _find_text(channel, NS, "Extract-Protocol")
                    for char_el in channel.findall(f"{{{NS}}}Characteristics"):
                        value = char_el.text.strip() if char_el.text else ""
                        if not value:
                            continue
                        key = char_el.get("tag") or "characteristic"
                        characteristics[key] = f"{characteristics[key]}; {value}" if key in characteristics else value

                library_strategy = _find_text(sample, NS, "Library-Strategy")
                library_source = _find_text(sample, NS, "Library-Source")
                library_selection = _find_text(sample, NS, "Library-Selection")
                instrument_model = _find_text(sample, NS, "Instrument-Model")
                description = _find_text(sample, NS, "Description")
                data_processing = _find_text(sample, NS, "Data-Processing")

                # Supplementary files
                suppl_files = []
                for sd in sample.findall(f"{{{NS}}}Supplementary-Data"):
                    url_text = sd.text.strip() if sd.text else ""
                    if url_text:
                        suppl_files.append({"url": url_text, "type": sd.get("type", "")})

                biosample_id = sra_id = sra_link = ""
                for rel in sample.findall(f"{{{NS}}}Relation"):
                    rel_type = rel.get("type", "")
                    target = rel.get("target", "")
                    if rel_type == "BioSample" and "/biosample/" in target:
                        biosample_id = target.split("/biosample/")[-1]
                    elif rel_type == "SRA":
                        sra_link = target
                        # extract SRX id from URL like https://www.ncbi.nlm.nih.gov/sra?term=SRX...
                        if "term=" in target:
                            sra_id = target.split("term=")[-1]

                # Platform
                platform_id = platform_title = ""
                platform_el = root.find(f"{{{NS}}}Platform")
                if platform_el is not None:
                    acc_el = platform_el.find(f"{{{NS}}}Accession")
                    platform_id = acc_el.text.strip() if acc_el is not None and acc_el.text else ""
                    platform_title = _find_text(platform_el, NS, "Title")

                # Contact from top-level Contributor
                contact: dict = {}
                contrib_ref = sample.find(f"{{{NS}}}Contact-Ref")
                contrib_iid = contrib_ref.get("iid") if contrib_ref is not None else None
                for contrib in root.findall(f"{{{NS}}}Contributor"):
                    if contrib_iid and contrib.get("iid") != contrib_iid:
                        continue
                    person = contrib.find(f"{{{NS}}}Person")
                    first = _find_text(person, NS, "First") if person is not None else ""
                    last = _find_text(person, NS, "Last") if person is not None else ""
                    email = _find_text(contrib, NS, "Email")
                    org_el = contrib.find(f"{{{NS}}}Organization")
                    org_name = dept = line = city = state = zip_code = country = ""
                    if org_el is not None:
                        org_name = _find_text(org_el, NS, "Name")
                        dept = _find_text(org_el, NS, "Department")
                        addr_el = org_el.find(f"{{{NS}}}Address")
                        if addr_el is not None:
                            line = _find_text(addr_el, NS, "Line")
                            city = _find_text(addr_el, NS, "City")
                            state = _find_text(addr_el, NS, "State")
                            zip_code = _find_text(addr_el, NS, "Zip-Code") or _find_text(addr_el, NS, "Postal-Code")
                            country = _find_text(addr_el, NS, "Country")
                    contact = {
                        "name": f"{first} {last}".strip(),
                        "email": email,
                        "organization": org_name,
                        "department": dept,
                        "address": line,
                        "city": city,
                        "state": state,
                        "zip": zip_code,
                        "country": country,
                    }
                    break

                # Parent series
                parent_gse = parent_gse_title = ""
                series = root.find(f"{{{NS}}}Series")
                if series is not None:
                    acc_el = series.find(f"{{{NS}}}Accession")
                    parent_gse = acc_el.text.strip() if acc_el is not None and acc_el.text else ""
                    parent_gse_title = _find_text(series, NS, "Title")

                return {
                    "gsm_id": gsm_id,
                    "title": title,
                    "sample_type": sample_type,
                    "organism": organism,
                    "source_name": source_name,
                    "characteristics": characteristics,
                    "molecule": molecule,
                    "extraction_protocol": extraction_protocol,
                    "growth_protocol": growth_protocol,
                    "treatment_protocol": treatment_protocol,
                    "library_strategy": library_strategy,
                    "library_source": library_source,
                    "library_selection": library_selection,
                    "instrument_model": instrument_model,
                    "description": description,
                    "data_processing": data_processing,
                    "supplementary_files": suppl_files,
                    "biosample_id": biosample_id,
                    "sra_id": sra_id,
                    "sra_link": sra_link,
                    "platform_id": platform_id,
                    "platform_title": platform_title,
                    "contact": contact,
                    "parent_gse": parent_gse,
                    "parent_gse_title": parent_gse_title,
                    "submission_date": submission_date,
                    "last_update_date": last_update_date,
                    "release_date": release_date,
                }
            except (httpx.HTTPStatusError, httpx.TimeoutException, ET.ParseError):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return {"gsm_id": gsm_id}


async def fetch_gse_detail(gse_id: str) -> dict:
    """Fetch full GSE detail via GEO MINiML XML endpoint."""
    url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    params = {"acc": gse_id, "targ": "self", "form": "xml", "view": "quick"}

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
