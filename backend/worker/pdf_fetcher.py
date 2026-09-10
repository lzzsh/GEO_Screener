import hashlib
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs
import os
import re
import httpx

logger = logging.getLogger(__name__)
PDF_DIR = os.getenv("PDF_DIR", "pdfs")


PMC_CLOUD = "https://pmc-oa-opendata.s3.amazonaws.com"


async def pmc_article_versions(client, pmcid, pmid):
    """Return matching article versions, preferring the published article."""
    if not re.fullmatch(r"PMC\d+", pmcid):
        return []
    response = await client.get(PMC_CLOUD + "/", params={
        "list-type": "2", "prefix": f"metadata/{pmcid}.",
    })
    response.raise_for_status()
    listing = ET.fromstring(response.content)
    keys = [el.text for el in listing.findall("{*}Contents/{*}Key")
            if el.text and re.fullmatch(rf"metadata/{pmcid}\.\d+\.json", el.text)]
    candidates = []
    for key in keys:
        response = await client.get(f"{PMC_CLOUD}/{key}")
        response.raise_for_status()
        metadata = response.json()
        if str(metadata.get("pmid")) != str(pmid):
            continue
        candidates.append(metadata)
    # A higher deposit version alone does not imply a preferred article version.
    return sorted(candidates, key=lambda metadata: metadata.get("is_manuscript") in (True, "yes", "true"))


def pmc_asset_url(url):
    if url.startswith("s3://pmc-oa-opendata/"):
        url = PMC_CLOUD + "/" + url.removeprefix("s3://pmc-oa-opendata/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "pmc-oa-opendata.s3.amazonaws.com":
        raise ValueError('不是受支持的 PMC 来源地址')
    return url


async def fetch_pmc_asset(client, url):
    url = pmc_asset_url(url)
    response = await client.get(url)
    response.raise_for_status()
    digest = parse_qs(urlparse(url).query).get("md5", [None])[0]
    if digest and hashlib.md5(response.content).hexdigest() != digest:
        raise ValueError('PMC 来源文件校验失败')
    return response.content


async def _fetch_pmc_cloud_pdf(client, pmcid, pmid, out_path):
    """Resolve the published PDF through PMC's current, public article metadata."""
    for metadata in await pmc_article_versions(client, pmcid, pmid):
        if not metadata.get('pdf_url'):
            continue
        try:
            content = await fetch_pmc_asset(client, metadata['pdf_url'])
        except (httpx.HTTPError, ValueError):
            continue
        if not content.startswith(b'%PDF-'):
            continue
        with open(out_path, "wb") as file:
            file.write(content)
        return True
    return False


async def fetch_pdf(pmid: str, gse_id: str, output_dir: str | None = None) -> tuple[str | None, str | None]:
    """Returns (pdf_path, doi) or (None, None) on failure."""
    if not re.fullmatch(r"GSE\d+", gse_id) or not str(pmid).isdigit():
        return None, None
    directory = output_dir or PDF_DIR
    os.makedirs(directory, exist_ok=True)
    out_path = os.path.join(directory, f"{gse_id}.pdf")

    doi = None
    pmcid = None

    # PMID → PMCID + DOI via NCBI ID converter
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(
                "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                params={"ids": pmid, "format": "json"},
            )
            r.raise_for_status()
            data = r.json()
            records = data.get("records", [])
            if records:
                pmcid = records[0].get("pmcid")
                doi = records[0].get("doi")
    except Exception as e:
        logger.warning("NCBI idconv failed for pmid=%s: %s", pmid, e)

    # PMC moved article datasets to its public cloud service in August 2026.
    if pmcid:
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                if await _fetch_pmc_cloud_pdf(client, pmcid, pmid, out_path):
                    return out_path, doi
        except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
            logger.warning("PMC cloud PDF retrieval failed for %s (%s)", pmcid, type(exc).__name__)

    # PMC full-text PDF
    if pmcid:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(
                    f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if r.status_code == 200 and b"%PDF" in r.content[:8]:
                    with open(out_path, "wb") as f:
                        f.write(r.content)
                    return out_path, doi
        except Exception as e:
            logger.warning("PMC PDF download failed for pmcid=%s: %s", pmcid, e)

    # bioRxiv/medRxiv fallback (for preprints with 10.1101 or 10.1101/medrxiv DOIs)
    if doi and doi.startswith("10.1101"):
        try:
            server = "medrxiv" if "medrxiv" in doi else "biorxiv"
            pdf_url = f"https://www.{server}.org/content/{doi}.full.pdf"
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and b"%PDF" in r.content[:8]:
                    with open(out_path, "wb") as f:
                        f.write(r.content)
                    return out_path, doi
        except Exception as e:
            logger.warning("bioRxiv PDF download failed for doi=%s: %s", doi, e)

    # Sci-Hub fallback
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(
                f"https://sci-hub.se/{pmid}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                from html.parser import HTMLParser

                class _PDFLinkParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.pdf_url = None

                    def handle_starttag(self, tag, attrs):
                        if tag in ("iframe", "embed") and not self.pdf_url:
                            attrs_dict = dict(attrs)
                            src = attrs_dict.get("src", "")
                            if src and ".pdf" in src:
                                self.pdf_url = src if src.startswith("http") else "https:" + src

                parser = _PDFLinkParser()
                parser.feed(r.text)
                if parser.pdf_url:
                    pdf_r = await client.get(parser.pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                    if pdf_r.status_code == 200 and b"%PDF" in pdf_r.content[:8]:
                        with open(out_path, "wb") as f:
                            f.write(pdf_r.content)
                        return out_path, doi
    except Exception as e:
        logger.warning("Sci-Hub fallback failed for pmid=%s: %s", pmid, e)

    return None, doi
