import logging
import os
import httpx

logger = logging.getLogger(__name__)
PDF_DIR = "pdfs"


async def fetch_pdf(pmid: str, gse_id: str) -> tuple[str | None, str | None]:
    """Returns (pdf_path, doi) or (None, None) on failure."""
    os.makedirs(PDF_DIR, exist_ok=True)
    out_path = os.path.join(PDF_DIR, f"{gse_id}.pdf")

    doi = None
    pmcid = None

    # PMID → PMCID + DOI via NCBI ID converter
    try:
        async with httpx.AsyncClient(timeout=15) as client:
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
