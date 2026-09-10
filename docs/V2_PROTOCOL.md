# GEO Screener v2: Protocol extraction

This release adds protocol extraction after the existing screening workflow. Screening decisions and labels are not changed by protocol extraction.

## Preserved version and isolated data

- v1 baseline: `main` at `ccc34f6`, tag `v1-baseline-20260910`.
- v2 development branch: `codex/v2-protocol`.
- Existing `geo_search.db`, `data/geo_search.db` and `pdfs/` remain unchanged.
- The prepared v2 copy is `data/v2/geo_search.db`; PDFs, new documents and prompt copies are under `data/v2/`.
- `scripts/prepare_v2.py` uses SQLite's online backup API and checks integrity. It refuses to overwrite an existing destination.

Prepare a new copy from the database actually used by your v1 deployment:

```bash
python scripts/prepare_v2.py --source-db geo_search.db
# If v1 runs in Docker, use --source-db data/geo_search.db instead.
```

Start the independent Docker deployment:

```bash
docker compose -p geo-v2 -f docker/docker-compose.v2.yml up -d --build
```

The v2 site is at http://127.0.0.1:8002. It uses its own SQLite file, PDF directory, prompt copy and Redis volume. The existing Docker deployment does not need to stop. Existing account passwords and settings are carried over by the database copy. The v2 entrypoint does not create default accounts.

Local development (from repository root, with backend requirements installed):

```bash
python scripts/run_v2.py
```

The local launcher creates a private persistent signing key under `data/v2/.secret_key`. For Docker set `SECRET_KEY` in the environment. If a configured model should bypass a system proxy, list its hostname under `direct_api_hosts` in `data/v2/runtime.json`; TLS verification remains enabled. The local launcher also runs legacy annotation tasks inline to avoid dispatching into an existing v1 Celery worker, and sets `PROMPT_DIR` to its private prompt copy. Local inline mode is useful for debugging: after a process restart, an unfinished item can be retried after its 20-minute lease expires. Docker uses Celery/Redis. Broker delivery and worker claiming are idempotent; a stale delivery cannot replace a later run.

Rollback: stop the separate v2 service and return to the original deployment/database. Do not point v1 at the v2 database to roll back. A code-only checkout of the preserved baseline is also possible in a separate worktree.

## Workflow

1. Open an existing screening task. Select records across pages, or use “全部 Included 提取” for all included results, regardless of the displayed page.
2. A protocol job stores snapshots of the selected GSE records and known GSM identifiers. These snapshots remain available if the original screening task is deleted.
3. Upload main papers, supplements or referenced methods. PDF, UTF-8 TXT and MD are supported (30 MB per file, 300 PDF pages, 20 materials per item). Reference material must name the target paper's citation or adoption relationship.
4. Alternatively select “获取正文 PDF” to reuse an existing PDF or resolve the explicit GEO publication. Ambiguous multiple PMID associations require the user to provide the correct article. Automatic acquisition does not search dataset titles and accept an unverified first hit.
5. Select “开始提取”, or queue pending records from the job toolbar. The active owner-specific LLM configuration in Settings is used. Every document page is processed in bounded chunks; nothing is silently truncated to the first 8,000 characters. Responses are streamed, with an 8,192-token output limit and a 300-second deadline per chunk. Token-limit truncation is reported as a failure, never as a successful partial extraction.
6. Inspect the proposed events, protocol groups, missing fields and verbatim page evidence. Edit any field, add/remove an event, or add the specific supporting quote. Save creates a new immutable human revision. “保存并标记已复核” additionally requires all blocking validation errors to be resolved.
7. Export the current reviewed revisions as TSV. Draft export is separate and named as draft. Evidence JSON contains row numbers, protocol names, source page identifiers and provenance; issues JSON includes missing values, unresolved references and blockers.

A repeat extraction creates a new machine proposal and retains the active human revision. Use the version selector to view the proposal; saving it creates a new human revision. Optimistic concurrency prevents an old editing window from overwriting a newer active revision.

## Skill contract

Rules are adapted from `perturbation-extractor` and `protocol-chain-annotator`. Source skills remain unchanged. The server uses `backend/prompts/protocol/extract_v1.txt` and `backend/protocol_schema.py`, with a prompt hash, model, schema version and document hashes recorded in each machine revision.

The original skill defines **24 columns** (the earlier planning messages incorrectly said 25). The TSV preserves their exact order:

```
GSE_id GSM_id Article_title Start_cell_type Final_cell_type Stage_name Stage_order Pert_name Addition_context Pert_type pubchem_cid chembl_id dose_value dose_unit time_pert_start time_pert_end duration_pert time_unit time_collection Culture_medium Culture_system Batch_id Collection_methods Reference
```

In the exported file these columns are separated by tabs. Extra provenance does not alter the TSV contract.

Resolved skill inconsistencies:

- Missing/not-applicable values become `NA` (including legacy `N/A`).
- A basal-medium row has `Addition_context=basal medium`, with perturbation/dose identifiers `NA`.
- Time units are `days` or `hours`; duration is end minus start. Ambiguous inclusive endpoints are not automatically incremented.
- Only assign a GSM when its identity and treatment mapping are supported; unknown mappings remain `NA`.
- Constant medium supplements stay in `Culture_medium`; stock and working concentrations must be distinguished.
- Reference chains cannot be fabricated. Target-paper changes take precedence over a cited generic recipe. Conflicts and missing sources stay visible.
- PubChem/ChEMBL IDs remain `NA` unless the provided source supports them. This release does not invent identifiers from model memory.

## Scope and limitations

Implemented: selection and batch jobs, private source upload/viewing, PDF/text parsing, evidence-grounded extraction, explicit missing-source state, multi-protocol groups, known-GSM validation, human revisions, reviewed/draft exports, owner isolation, failed/stale-run retries and additive PDF-column migrations.

Not yet automated: OCR, spreadsheet/Word supplements, external citation-chain retrieval, chemical identifier lookup, semantic verification of every dose against its quote, and biological accuracy benchmarking. A quote being found on a page verifies provenance, not the scientific correctness of every extracted field. Supplementary tables should be checked against the original PDF. A paper with no usable searchable text cannot be processed until OCR/text is supplied.

The old screening/PDF calibration implementation is retained; the new workflow does not apply its “paper overrides GEO” rule or overwrite screening decisions.

## Verification

Targeted suite:

```bash
python -m pytest -c backend/pytest.ini \
  backend/tests/test_protocol_schema.py backend/tests/test_protocol_documents.py \
  backend/tests/test_protocols_router.py backend/tests/test_v2_launcher.py \
  backend/tests/test_task_dispatch.py backend/tests/test_geo_fetcher.py \
  backend/tests/test_pages.py backend/tests/test_database.py -q
```

Coverage includes selecting included records, duplicate materials, invalid PDFs, ownership checks, evidence and time checks, reviewed export, editing conflicts, protecting human revisions, repeated broker deliveries and stale-run recovery.

The repository's pre-existing full suite is not green: a baseline run at ccc34f6 gave 43 passed, 5 failed and 21 setup errors, including removed screening APIs and database-fixture isolation. The final v2 comparison had the same failures/errors and 64 passed. The targeted suite above passed all 38 tests. These historical test issues were not silently rewritten to claim a clean regression suite.

Detailed local validation and the real DeepSeek smoke result: [V2_VALIDATION.md](V2_VALIDATION.md).
