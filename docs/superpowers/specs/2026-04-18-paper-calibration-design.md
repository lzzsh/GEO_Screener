# Paper PDF Download & Calibration Design

Date: 2026-04-18

## Overview

Add paper PDF download and LLM-based re-screening calibration to the existing GSE screening workflow. PDFs are fetched via PMC (fallback: Sci-Hub), text extracted and fed to LLM to update screening decisions. Original decisions are preserved for comparison.

## Approach

Extend `ScreeningResult` directly (no new task type). Two new async operations triggered from the GSE task detail page:
1. **Fetch PDFs** — download papers for include/uncertain GSEs
2. **Run calibration** — re-run LLM screening with paper full-text as additional context

---

## Data Model

### `ScreeningResult` — six new columns

| Column | Type | Default | Notes |
|---|---|---|---|
| `pmid` | String(32), nullable | NULL | PubMed ID from MINiML `<Relation type="PubMed">` |
| `doi` | String(256), nullable | NULL | DOI from PMC metadata |
| `pdf_path` | String(512), nullable | NULL | Local path to downloaded PDF |
| `pdf_status` | String(16) | `"none"` | `none / fetching / available / failed` |
| `original_decision` | String(16), nullable | NULL | Snapshot of decision before first calibration |
| `original_summary` | Text, nullable | NULL | Snapshot of summary before first calibration |

Migration: SQLite `ALTER TABLE` with defaults — no existing data affected.

---

## PDF Fetch Flow

### PMID Extraction

`fetch_gse_detail()` in `geo_fetcher.py` already parses MINiML XML. Extend `_parse_miniml()` to extract `<Relation type="PubMed" target="...">` and return `pmid`.

Store `pmid` on `ScreeningResult` when the GSE detail is fetched (during annotation or on-demand).

### New file: `backend/worker/pdf_fetcher.py`

```python
async def fetch_pdf(pmid: str, gse_id: str, output_dir: str = "pdfs") -> tuple[str | None, str | None]:
    """
    Returns (pdf_path, doi) or (None, None) on failure.
    Strategy: PMC first, Sci-Hub fallback.
    """
    # Step 1: PMID → PMCID via NCBI ID converter
    # GET https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json
    # Extract pmcid and doi from response

    # Step 2: PMC full-text PDF
    # GET https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/
    # Save to pdfs/{gse_id}.pdf

    # Step 3: Sci-Hub fallback (if no PMCID or PMC download fails)
    # GET https://sci-hub.se/{pmid}
    # Parse HTML for PDF iframe/embed src, download PDF

    # Return (path, doi) or (None, None)
```

PDF storage: `pdfs/` directory at project root, filename `{gse_id}.pdf`.

### New worker function: `_fetch_papers_async(task_id)`

```
For each ScreeningResult where decision in [include, uncertain] and pdf_status == "none":
    1. If pmid is None: skip (no paper linked)
    2. Set pdf_status = "fetching", commit
    3. Call fetch_pdf(pmid, gse_id)
    4. On success: set pdf_path, doi, pdf_status = "available", commit
    5. On failure: set pdf_status = "failed", commit
```

---

## Paper Calibration Flow

### New file: `backend/worker/llm_client.py` — new prompt template

`PAPER_CALIBRATION_PROMPT_TEMPLATE`:
- Same structure as `SCREENING_PROMPT_TEMPLATE`
- Adds `## 文章全文（节选）` section after GEO metadata
- Instruction: paper content takes priority over GEO metadata on conflicts
- Paper text truncated to first 8000 characters to stay within token limits

### New worker function: `_run_paper_calibration_async(task_id)`

```
For each ScreeningResult where pdf_status == "available":
    1. Extract text from PDF using pdfplumber (first 8000 chars)
    2. If original_decision is None:
       snapshot: original_decision = decision, original_summary = summary
    3. Call llm.calibrate_with_paper(dataset_id, title, description, paper_text, criteria_text)
    4. Update: decision, confidence, summary, rule_checks
    5. Commit per result
```

---

## API Endpoints

Both in `backend/routers/tasks.py`:

```
POST /tasks/{task_id}/fetch-papers
```
- Validates task ownership
- Fires `_fetch_papers_async(task_id)` via `asyncio.create_task`
- Returns `{"status": "running_inline"}`

```
POST /tasks/{task_id}/run-paper-calibration
```
- Validates task ownership
- Fires `_run_paper_calibration_async(task_id)` via `asyncio.create_task`
- Returns `{"status": "running_inline"}`

Existing `GET /tasks/{task_id}/results` endpoint: add `pmid`, `pdf_status`, `original_decision` to each result dict.

---

## Frontend

### `tasks_detail.html` — action bar

Add two buttons after "Run GSE Annotation":

```html
[Run GSE Annotation]  [下载文章 PDF]  [用文章重新校准]
```

- "下载文章 PDF": calls `POST /tasks/{id}/fetch-papers`, polls every 3s, button shows "下载中…" while running
- "用文章重新校准": calls `POST /tasks/{id}/run-paper-calibration`, reuses existing running/poll pattern

### Results table — two new columns

| Column | Position | Content |
|---|---|---|
| PDF | After "原始数据" | Icon: `—` (none) / `⟳` (fetching) / `📄` (available, links to download) / `✗` (failed) |
| 原始决策 | After "决策" | Shows `original_decision` badge in gray if set, empty otherwise |

The existing "决策" column updates after calibration; "原始决策" shows the pre-calibration value.

---

## File Structure

**New files:**
- `backend/worker/pdf_fetcher.py` — PDF download logic

**Modified files:**
- `backend/models.py` — 6 new columns on ScreeningResult
- `backend/worker/geo_fetcher.py` — extract pmid in `_parse_miniml()`
- `backend/worker/llm_client.py` — `PAPER_CALIBRATION_PROMPT_TEMPLATE` + `calibrate_with_paper()` method
- `backend/worker/tasks.py` — `_fetch_papers_async()` + `_run_paper_calibration_async()`
- `backend/routers/tasks.py` — 2 new endpoints, update results response
- `frontend/templates/tasks_detail.html` — 2 new buttons + 2 new table columns

**Dependencies to add:**
- `pdfplumber` — PDF text extraction
- `httpx` — already present (used for GEO API calls)
