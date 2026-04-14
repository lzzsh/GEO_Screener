import csv
import io
from typing import Optional

# Expected columns from general.csv format (flexible — uses first matching alias)
COLUMN_ALIASES = {
    "id":          ["GSE", "gse", "accession", "id", "dataset_id"],
    "title":       ["title", "Title", "study_title"],
    "description": ["summary", "Summary", "description", "abstract"],
}

def _find_col(headers: list[str], aliases: list[str]) -> Optional[str]:
    for alias in aliases:
        if alias in headers:
            return alias
    return None

def parse_csv(content: bytes) -> list[dict]:
    """Parse CSV bytes into list of {id, title, description} dicts."""
    text = content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []

    id_col = _find_col(headers, COLUMN_ALIASES["id"])
    title_col = _find_col(headers, COLUMN_ALIASES["title"])
    desc_col = _find_col(headers, COLUMN_ALIASES["description"])

    if not id_col:
        raise ValueError(f"CSV missing ID column. Found columns: {headers}")

    results = []
    for row in reader:
        dataset_id = row.get(id_col, "").strip()
        if not dataset_id:
            continue
        results.append({
            "id": dataset_id,
            "title": row.get(title_col, "").strip() if title_col else "",
            "description": row.get(desc_col, "").strip() if desc_col else "",
        })
    return results
