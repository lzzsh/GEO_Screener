# Paper PDF Download & Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PDF download (PMC/Sci-Hub) and LLM-based re-screening calibration to the GSE screening workflow.

**Architecture:** Extend `ScreeningResult` with 6 new columns; add `pdf_fetcher.py` for download logic; add `calibrate_with_paper()` to `LLMClient`; add two async worker functions and two API endpoints; update the results table and action bar in the frontend.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, httpx, pdfplumber, Alpine.js

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/models.py` | Modify | Add 6 new columns to `ScreeningResult` |
| `backend/worker/geo_fetcher.py` | Modify | Extract `pmid` in `_parse_miniml()` |
| `backend/worker/pdf_fetcher.py` | Create | PMC + Sci-Hub PDF download logic |
| `backend/worker/llm_client.py` | Modify | Add `PAPER_CALIBRATION_PROMPT_TEMPLATE` + `calibrate_with_paper()` |
| `backend/worker/tasks.py` | Modify | Add `_fetch_papers_async()` + `_run_paper_calibration_async()` |
| `backend/routers/tasks.py` | Modify | Add 2 endpoints, update results response |
| `frontend/templates/tasks_detail.html` | Modify | 2 new buttons + 2 new table columns |

---

## Task 1: Add 6 columns to ScreeningResult

**Files:**
- Modify: `backend/models.py:46-67`

- [ ] **Step 1: Add columns after line 64 (`n_samples`)**

In `backend/models.py`, after line 64 (`n_samples: Mapped[int] = mapped_column(Integer, default=0)`), add:

```python
    pmid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_status: Mapped[str] = mapped_column(String(16), default="none")  # none|fetching|available|failed
    original_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Run SQLite migration**

```bash
cd /Users/lzz/Documents/GitHub/GEO_search
python - <<'EOF'
import sqlite3
conn = sqlite3.connect("geo_search.db")
cur = conn.cursor()
for stmt in [
    "ALTER TABLE screening_results ADD COLUMN pmid TEXT",
    "ALTER TABLE screening_results ADD COLUMN doi TEXT",
    "ALTER TABLE screening_results ADD COLUMN pdf_path TEXT",
    "ALTER TABLE screening_results ADD COLUMN pdf_status TEXT DEFAULT 'none'",
    "ALTER TABLE screening_results ADD COLUMN original_decision TEXT",
    "ALTER TABLE screening_results ADD COLUMN original_summary TEXT",
]:
    try:
        cur.execute(stmt)
    except sqlite3.OperationalError as e:
        print(f"Skip: {e}")
conn.commit()
conn.close()
print("Migration done")
EOF
```

Expected output: `Migration done` (columns already existing will print Skip messages, that's fine)

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat: add pdf/calibration columns to ScreeningResult"
```

---

## Task 2: Extract PMID in `_parse_miniml()`

**Files:**
- Modify: `backend/worker/geo_fetcher.py:236-248`

- [ ] **Step 1: Add PMID extraction inside the `for rel in series.findall(...)` loop**

The existing loop at lines 236-248 handles `BioProject` and `series` relation types. Add a `PubMed` branch:

```python
    pmid = None
    for rel in series.findall(f"{{{NS}}}Relation"):
        rel_type = rel.get("type") or ""
        target = rel.get("target", "")
        if rel_type == "BioProject":
            if "/bioproject/" in target:
                bioproject_id = target.split("/bioproject/")[-1]
            bioproject_link = target
        elif rel_type == "PubMed":
            pmid = target.split("/")[-1] if "/" in target else target
        elif "series" in rel_type.lower():
            series_relations.append({
                "type": rel_type,
                "accession": _relation_accession(target),
                "target": target,
            })
```

- [ ] **Step 2: Add `pmid` to the return dict**

Find the `return {` at the end of `_parse_miniml()` (around line 321) and add `"pmid": pmid`:

```python
    return {
        "gse_id": gse_id,
        "bioproject_id": bioproject_id,
        "bioproject_link": bioproject_link,
        "abstract": abstract,
        "overall_design": overall_design,
        "series_relations": series_relations,
        "contact": contact,
        "supplementary_files": supplementary_files,
        "pmid": pmid,
    }
```

- [ ] **Step 3: Store pmid on ScreeningResult in `_geo_context_for_result()`**

In `backend/worker/tasks.py`, the function `_geo_context_for_result()` (lines 85-100) calls `fetch_gse_detail()`. After getting `detail`, store `pmid` if present. Find the function and update it:

```python
async def _geo_context_for_result(sr: ScreeningResult) -> str:
    detail = await fetch_gse_detail(sr.dataset_id)
    if detail and detail.get("pmid") and not sr.pmid:
        sr.pmid = detail["pmid"]
    samples = _stored_samples_to_dicts(sr)
    return _build_geo_metadata_context(sr.description or "", detail, samples, sr.has_raw_data)
```

Note: The caller (`_screen_one`) already commits after updating `sr`, so `pmid` will be persisted.

- [ ] **Step 4: Commit**

```bash
git add backend/worker/geo_fetcher.py backend/worker/tasks.py
git commit -m "feat: extract and store pmid from MINiML XML"
```

---

## Task 3: Create `pdf_fetcher.py`

**Files:**
- Create: `backend/worker/pdf_fetcher.py`

- [ ] **Step 1: Create the file**

```python
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

    # Step 1: PMID → PMCID + DOI via NCBI ID converter
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

    # Step 2: PMC full-text PDF
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

    # Step 3: Sci-Hub fallback
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/worker/pdf_fetcher.py
git commit -m "feat: add pdf_fetcher with PMC and Sci-Hub download"
```

---

## Task 4: Add `calibrate_with_paper()` to `LLMClient`

**Files:**
- Modify: `backend/worker/llm_client.py`

- [ ] **Step 1: Add `PAPER_CALIBRATION_PROMPT_TEMPLATE` after `SCREENING_PROMPT_TEMPLATE` (after line 222)**

```python
PAPER_CALIBRATION_PROMPT_TEMPLATE = """\
You are a systematic review screener. Evaluate the following dataset against the criteria.
When the paper full-text conflicts with GEO metadata, the paper takes priority.

## Screening Criteria
{criteria_text}

## Dataset Information
ID: {dataset_id}
Title: {title}
Description: {description}

## 文章全文（节选）
{paper_text}

## Instructions
Return ONLY valid JSON with this exact structure:
{{
  "decision": "include" | "exclude" | "uncertain",
  "confidence": 0.0-1.0,
  "summary": "one sentence rationale",
  "rule_checks": {{"criterion_key": true|false}}
}}
"""
```

- [ ] **Step 2: Add `calibrate_with_paper()` method to `LLMClient` after `screen_dataset()` (after line 247)**

```python
    async def calibrate_with_paper(self, dataset_id: str, title: str, description: str,
                                    paper_text: str, criteria_text: str) -> dict:
        prompt = PAPER_CALIBRATION_PROMPT_TEMPLATE.format(
            criteria_text=criteria_text,
            dataset_id=dataset_id,
            title=title,
            description=description,
            paper_text=paper_text[:8000],
        )
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)
```

- [ ] **Step 3: Commit**

```bash
git add backend/worker/llm_client.py
git commit -m "feat: add paper calibration prompt and method to LLMClient"
```

---

## Task 5: Add worker functions `_fetch_papers_async` and `_run_paper_calibration_async`

**Files:**
- Modify: `backend/worker/tasks.py`

- [ ] **Step 1: Add import for `pdf_fetcher` at top of file**

After line 10 (`from backend.worker.llm_client import LLMClient`), add:

```python
from backend.worker.pdf_fetcher import fetch_pdf
```

- [ ] **Step 2: Add `_fetch_papers_async` function (append to end of file)**

```python
async def _fetch_papers_async(task_id: int):
    async with AsyncSessionLocal() as db:
        res_result = await db.execute(
            select(ScreeningResult).where(
                ScreeningResult.task_id == task_id,
                ScreeningResult.decision.in_(["include", "uncertain"]),
                ScreeningResult.pdf_status == "none",
            )
        )
        pending = res_result.scalars().all()

        for sr in pending:
            if not sr.pmid:
                continue
            sr.pdf_status = "fetching"
            await db.commit()
            try:
                pdf_path, doi = await fetch_pdf(sr.pmid, sr.dataset_id)
                if pdf_path:
                    sr.pdf_path = pdf_path
                    sr.pdf_status = "available"
                else:
                    sr.pdf_status = "failed"
                if doi and not sr.doi:
                    sr.doi = doi
            except Exception as e:
                logger.error("fetch_pdf error for %s: %s", sr.dataset_id, e)
                sr.pdf_status = "failed"
            await db.commit()
```

- [ ] **Step 3: Add `_run_paper_calibration_async` function (append to end of file)**

```python
async def _run_paper_calibration_async(task_id: int):
    import pdfplumber

    async with AsyncSessionLocal() as db:
        task_result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))
        task = task_result.scalar_one_or_none()
        if not task:
            return

        cfg_result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id))
        cfg = cfg_result.scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return

        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature)

        res_result = await db.execute(
            select(ScreeningResult).where(
                ScreeningResult.task_id == task_id,
                ScreeningResult.pdf_status == "available",
            )
        )
        results = res_result.scalars().all()

        for sr in results:
            try:
                paper_text = ""
                with pdfplumber.open(sr.pdf_path) as pdf:
                    for page in pdf.pages:
                        paper_text += page.extract_text() or ""
                        if len(paper_text) >= 8000:
                            break

                if not sr.original_decision:
                    sr.original_decision = sr.decision
                    sr.original_summary = sr.summary

                result = await llm.calibrate_with_paper(
                    dataset_id=sr.dataset_id,
                    title=sr.title or "",
                    description=sr.description or "",
                    paper_text=paper_text,
                    criteria_text=task.criteria_text,
                )
                sr.decision = result.get("decision")
                sr.confidence = result.get("confidence")
                sr.summary = result.get("summary")
                sr.rule_checks = json.dumps(result.get("rule_checks", {}), ensure_ascii=False)
            except Exception as e:
                logger.error("calibration error for %s: %s", sr.dataset_id, e)
            await db.commit()
```

- [ ] **Step 4: Commit**

```bash
git add backend/worker/tasks.py
git commit -m "feat: add _fetch_papers_async and _run_paper_calibration_async workers"
```

---

## Task 6: Add two API endpoints and update results response

**Files:**
- Modify: `backend/routers/tasks.py`

- [ ] **Step 1: Add `POST /tasks/{task_id}/fetch-papers` endpoint**

Append after the `run-gsm-annotation` endpoint (after line ~426):

```python
@router.post("/{task_id}/fetch-papers")
async def fetch_papers(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import asyncio as _asyncio
    task = await db.get(ScreeningTask, task_id)
    if not task or task.owner_id != user.id:
        raise HTTPException(status_code=404)
    from backend.worker.tasks import _fetch_papers_async
    _asyncio.create_task(_fetch_papers_async(task_id))
    return {"status": "running_inline"}
```

- [ ] **Step 2: Add `POST /tasks/{task_id}/run-paper-calibration` endpoint**

```python
@router.post("/{task_id}/run-paper-calibration")
async def run_paper_calibration(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import asyncio as _asyncio
    task = await db.get(ScreeningTask, task_id)
    if not task or task.owner_id != user.id:
        raise HTTPException(status_code=404)
    from backend.worker.tasks import _run_paper_calibration_async
    _asyncio.create_task(_run_paper_calibration_async(task_id))
    return {"status": "running_inline"}
```

- [ ] **Step 3: Update `GET /tasks/{task_id}/results` response to include new fields**

In `backend/routers/tasks.py` at lines 209-223, update the items dict to add `pmid`, `pdf_status`, `original_decision`:

```python
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [{"id": r.id, "dataset_id": r.dataset_id, "title": r.title,
                   "description": r.description, "keyword_matched": r.keyword_matched,
                   "decision": r.decision, "confidence": r.confidence,
                   "summary": r.summary, "rule_checks": r.rule_checks,
                   "status": r.status, "error_msg": r.error_msg,
                   "gse_type": r.gse_type, "pubdate": r.pubdate,
                   "update_date": r.update_date, "has_raw_data": r.has_raw_data,
                   "n_samples": r.n_samples,
                   "pmid": r.pmid, "pdf_status": r.pdf_status,
                   "original_decision": r.original_decision,
                   "labels": [{"key": label.key, "value": label.value, "source": label.source} for label in r.labels],
                   "samples": [{"id": s.id, "gsm_id": s.gsm_id, "title": s.title,
                                "organism": s.organism, "biosample_id": s.biosample_id,
                                "cell_count": s.cell_count} for s in r.samples]} for r in rows],
    }
```

- [ ] **Step 4: Commit**

```bash
git add backend/routers/tasks.py
git commit -m "feat: add fetch-papers and run-paper-calibration endpoints"
```

---

## Task 7: Frontend — action bar buttons + table columns

**Files:**
- Modify: `frontend/templates/tasks_detail.html`

- [ ] **Step 1: Add two state variables to `taskDetailPage()`**

In the `taskDetailPage(taskId)` function at line 248, add `fetchingPdfs: false` and `calibrating: false` to the returned object:

```javascript
function taskDetailPage(taskId) {
    return {
      taskId, task: {}, results: [], loading: true,
      page: 1, pageSize: 20, total: 0, jumpPageInput: 1, expanded: new Set(),
      decisionFilter: '', annotating: false, annotationError: '', gsmAnnotating: false,
      fetchingPdfs: false, calibrating: false,
      pollTimer: null, libs: [],
      expandedGsm: new Set(),
```

- [ ] **Step 2: Add `fetchPapers()` and `runPaperCalibration()` methods**

After the `runAllGsmAnnotation()` method (after line 378), add:

```javascript
      async fetchPapers() {
        this.fetchingPdfs = true;
        try {
          await fetch('/tasks/' + this.taskId + '/fetch-papers', {method: 'POST'});
          const pollPdf = setInterval(async () => { await this.loadResults(); }, 3000);
          setTimeout(() => clearInterval(pollPdf), 120000);
        } finally {
          this.fetchingPdfs = false;
        }
      },
      async runPaperCalibration() {
        this.calibrating = true;
        try {
          await fetch('/tasks/' + this.taskId + '/run-paper-calibration', {method: 'POST'});
          const pollCal = setInterval(async () => { await this.loadResults(); }, 3000);
          setTimeout(() => clearInterval(pollCal), 300000);
        } finally {
          this.calibrating = false;
        }
      },
```

- [ ] **Step 3: Add two buttons to the action bar**

In `tasks_detail.html` at line 68, after the "导出 CSV" link and before the "存入文献库" dropdown, add:

```html
      <button @click="fetchPapers()" :disabled="fetchingPdfs"
              class="text-sm bg-gray-100 hover:bg-gray-200 px-4 py-2 rounded-lg font-medium disabled:opacity-50"
              x-text="fetchingPdfs ? '下载中…' : '下载文章 PDF'"></button>
      <button @click="runPaperCalibration()" :disabled="calibrating"
              class="text-sm bg-blue-50 hover:bg-blue-100 text-blue-700 px-4 py-2 rounded-lg font-medium disabled:opacity-50"
              x-text="calibrating ? '校准中…' : '用文章重新校准'"></button>
```

- [ ] **Step 4: Add two new table header columns**

In `tasks_detail.html` at lines 93-103 (the `<thead>` row), add after the "原始数据" `<th>` (line 100) and before "决策" (line 101):

```html
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-16">PDF</th>
          <th class="text-left px-4 py-3 font-medium text-gray-600 w-24">原始决策</th>
```

- [ ] **Step 5: Add two new table data columns in the row template**

In `tasks_detail.html` at lines 119-127, after the "原始数据" `<td>` (lines 119-122) and before the "决策" `<td>` (lines 123-127), add:

```html
            <td class="px-4 py-3 text-center text-sm">
              <span x-show="!r.pdf_status || r.pdf_status === 'none'" class="text-gray-300">—</span>
              <span x-show="r.pdf_status === 'fetching'" class="text-blue-400">⟳</span>
              <a x-show="r.pdf_status === 'available'" :href="'/pdfs/' + r.dataset_id + '.pdf'" target="_blank" class="text-blue-600">📄</a>
              <span x-show="r.pdf_status === 'failed'" class="text-red-400">✗</span>
            </td>
            <td class="px-4 py-3">
              <span x-show="r.original_decision"
                    class="text-xs font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-500"
                    x-text="({include:'Included',exclude:'Excluded',uncertain:'Uncertain'})[r.original_decision] || r.original_decision"></span>
            </td>
```

- [ ] **Step 6: Update `colspan` on the expanded detail row**

The expanded row at line 131 has `colspan="9"`. With 2 new columns it becomes `colspan="11"`:

```html
          <td colspan="11" class="px-4 py-4">
```

- [ ] **Step 7: Commit**

```bash
git add frontend/templates/tasks_detail.html
git commit -m "feat: add PDF download and calibration buttons and columns to task detail"
```

---

## Task 8: Install `pdfplumber` dependency

**Files:**
- Modify: `requirements.txt` (or `pyproject.toml` — check which exists)

- [ ] **Step 1: Check which dependency file exists**

```bash
ls /Users/lzz/Documents/GitHub/GEO_search/requirements*.txt /Users/lzz/Documents/GitHub/GEO_search/pyproject.toml 2>/dev/null
```

- [ ] **Step 2: Add `pdfplumber` to the dependency file**

If `requirements.txt` exists, append:
```
pdfplumber
```

If `pyproject.toml` exists, add `"pdfplumber"` to the dependencies list.

- [ ] **Step 3: Install**

```bash
pip install pdfplumber
```

Expected: Successfully installed pdfplumber (and its deps: pdfminer.six, etc.)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt  # or pyproject.toml
git commit -m "chore: add pdfplumber dependency"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| 6 new columns on ScreeningResult | Task 1 |
| SQLite migration | Task 1 |
| Extract pmid from MINiML `<Relation type="PubMed">` | Task 2 |
| Store pmid on ScreeningResult | Task 2 |
| `pdf_fetcher.py` with PMC + Sci-Hub | Task 3 |
| `PAPER_CALIBRATION_PROMPT_TEMPLATE` | Task 4 |
| `calibrate_with_paper()` method | Task 4 |
| `_fetch_papers_async()` worker | Task 5 |
| `_run_paper_calibration_async()` worker | Task 5 |
| `POST /tasks/{id}/fetch-papers` endpoint | Task 6 |
| `POST /tasks/{id}/run-paper-calibration` endpoint | Task 6 |
| Results response includes pmid, pdf_status, original_decision | Task 6 |
| Two action bar buttons with loading states | Task 7 |
| PDF column in results table | Task 7 |
| 原始决策 column in results table | Task 7 |
| pdfplumber dependency | Task 8 |

**No placeholders found.**

**Type consistency:** `fetch_pdf(pmid, gse_id)` defined in Task 3, called in Task 5. `calibrate_with_paper(dataset_id, title, description, paper_text, criteria_text)` defined in Task 4, called in Task 5. All consistent.
