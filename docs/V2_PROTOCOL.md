# GEO Screener v2: Protocol extraction

This release adds protocol extraction after the existing screening workflow. Screening decisions and labels are not changed by protocol extraction.

## Preserved version and isolated data

- Preserved starting v1 snapshot: `ccc34f6`, tag `v1-baseline-20260910`. The current `main` ref independently advanced to `dfd24ae` during development; v2 remains based on the preserved starting snapshot.
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
3. Upload main papers, supplements or referenced methods. PDF, UTF-8 TXT/MD/CSV/TSV, DOCX, XLSX and ZIP supplements are supported (30 MB per file, 300 PDF pages, 20 manually uploaded materials per item). Word paragraphs/tables/notes, Excel worksheets (including Strict OOXML) and searchable ZIP members retain their source identity. Reference material must name the target paper's citation or adoption relationship.
4. Alternatively select “获取 Methods 与补充材料” to reuse an existing PDF or resolve the explicit GEO publication and collect its official PMC Methods and declared supplements. Ambiguous multiple PMID associations require the user to provide the correct article. Automatic acquisition does not search dataset titles and accept an unverified first hit.
5. Select “开始提取”, or queue pending records from the job toolbar. The active owner-specific LLM configuration in Settings is used. Methods from the same article XML preserve reading order; the original PDF remains available. All included supplementary sections are processed in overlapping chunks. The coverage manifest records every section and explicitly identifies gene/statistical result tables excluded after scanning for recipe clues. Responses are streamed without an application `max_tokens` or `max_completion_tokens` ceiling or a fixed whole-call deadline. Service-side truncation triggers bounded splitting of only the affected block; an unresolved truncation is a failure, never a successful partial result. Network stall timeouts remain in place.
6. Inspect the proposed events, protocol groups, missing fields and verbatim page evidence. Edit any field, add/remove an event, or add the specific supporting quote. Save creates a new immutable human revision. “保存并标记已复核” additionally requires all blocking validation errors to be resolved.
7. Export the current reviewed revisions as TSV. Draft export is separate and named as draft. Evidence JSON contains row numbers, protocol names, source page identifiers and provenance; issues JSON includes missing values, unresolved references and blockers.

A repeat extraction creates a new machine proposal and retains the active human revision. Use the version selector to view the proposal; saving it creates a new human revision. Optimistic concurrency prevents an old editing window from overwriting a newer active revision.

## Skill contract

The actual `perturbation-extractor` and `protocol-chain-annotator` skill snapshots are bundled in `backend/prompts/protocol/skills/` and included in every extraction system prompt. Source skill files remain unchanged. The server combines these with `backend/prompts/protocol/extract_v1.txt` and `backend/protocol_schema.py`, with the combined prompt hash, individual skill hashes, model, schema version, document hashes and material coverage recorded in each machine revision. The application JSON contract resolves conflicting TSV-only examples from the skills.

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

Implemented: selection and batch jobs, private source upload/viewing, PDF/text parsing, evidence-grounded extraction, explicit missing-source state, independent GSM trajectories, strict target-GSM validation, human revisions, reviewed/draft exports, owner isolation, failed/stale-run retries and additive PDF-column migrations.

Not yet automated: OCR, external citation-chain retrieval, chemical identifier lookup, semantic verification of every dose against its quote, and biological accuracy benchmarking. A quote being found on a page verifies provenance, not the scientific correctness of every extracted field. Supplementary tables should be checked against the original PDF. A paper with no usable searchable text cannot be processed until OCR/text is supplied.

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

At the initial v2 validation, the repository's pre-existing full suite was not green: a baseline run at ccc34f6 gave 43 passed, 5 failed and 21 setup errors, including removed screening APIs and database-fixture isolation. The final v2 comparison had the same failures/errors and 64 passed. The targeted suite above passed all 38 tests. These historical test issues were not silently rewritten to claim a clean regression suite.

Detailed local validation and the real DeepSeek smoke result: [V2_VALIDATION.md](V2_VALIDATION.md).

Subsequent legacy workflow repairs brought the full backend suite to **107 passed**. See [legacy debugging results and remaining limits](LEGACY_DEBUGGING.md).


## GSM 作为提取与复核单位

新任务默认 `extraction_unit=gsm`：所选 GSE 展开为各个 GSM，每个样本独立生成一套适用 protocol。`ProtocolItem` 保存共享文献材料，`ProtocolSample` 保存目标样本快照、状态和当前修订，`ProtocolRevision.sample_id` 绑定独立版本。迁移只新增表/字段；旧任务保留 `article`，旧人工版本不改动。

输入包括目标 GSM 的完整 GEO Characteristics、Growth-Protocol、Treatment-Protocol，以及共用 Methods、补充材料和明确采用的引用来源。模型必须区分起始对照、不同剂量、分支和采样时间；不能将论文所有配方复制给每个样本。新任务中 GSM_id=NA、其他 GSM 或多个备选 protocol 名称会阻止标记已复核。

工作台按 GSM 展示、单独重跑和复核；共享材料在任一关联样本提取期间禁止上传。批量提取保留已有结果，重新提取保留人工版本。已复核导出只选择各 GSM 当前已复核版本，TSV 仍为 24 列，证据和问题 JSON 另含 sample_id / gsm_id。

一个 GSM 没有可用分化流程或映射不明确时，保留 `no_protocol` / `needs_sources`，不为凑齐一套配方而填入猜测。原始细胞、对照样本也可能没有 Day 0 以后的分化事件。


## Default prompt deployment

A fresh or empty PROMPT_DIR falls back to the versioned `backend/prompts/default` files for annotation, and to the bundled Protocol contract for extraction. Both skill documents are bundled. The immutable `protocol/gsm_contract.txt` is always appended, so private prompts from older releases cannot silently remove the target-sample contract. Docker v2 keeps private overrides at `/data/prompts` and does not bind over the bundled prompt directory. Custom non-empty prompts retain priority; no API credentials are shipped.
