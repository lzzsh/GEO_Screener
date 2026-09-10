# Legacy workflow debugging — 2026-09-10

Starting revision: `f7e87d2` on `codex/v2-protocol`. Changes apply to the current v2 checkout; the preserved v1 snapshot and existing research records were not rewritten.

## Confirmed defects and fixes

| Area | Reproduced problem | Fix |
| --- | --- | --- |
| Natural-language screening | Task creation still accepted criteria, but `run_screening` and `screen_dataset` had been removed; tasks remained pending. | Restore criteria-based screening, dispatch after commit, validate model response structure and record per-result failures. Blank-criteria/empty tasks save candidates without model calls. |
| CSV upload | The new-task page sent multipart fields, while the API required query parameters; invalid CSV raised a server exception. | Accept the existing form and query clients; return a clear validation response for invalid input without retaining a task. |
| GSE/GSM labels | Several label-read/edit and single-record dispatch routes ignored the owning task. | Require ownership before reading, writing or dispatching. |
| Task deletion | Sample labels and GSM child references caused foreign-key failures. | Delete labels belonging to deleted samples and detach child tasks; preserve child task data and library snapshots. |
| Manual decisions | Single-record annotation retained the human label but replaced its matching decision with the model result. | Prefer the human conclusion and recalculate task decision counts. |
| GSM legacy worker | The worker omitted the now-required `gsm_labels` argument; loose mocks concealed the failure. | Pass the configured/default schema and prompt name, recognize the current `avail` completion marker, and test with the real method signature. |
| Library | Duplicate GSE IDs in one submission were inserted twice; label endpoints lacked ownership checks. | Deduplicate within the batch, authorize label operations and validate linked task ownership. |
| Article retrieval | Missing publication IDs fell back to the first title-search hit; failures were not retried or clearly reported. | Use explicit GEO publication associations, reject ambiguous associations, retry failed records and display PDF errors in task results. |
| PDF access | A static mount exposed downloaded PDFs without checking login or ownership. | Serve existing PDF URLs through authenticated ownership checks and restrict paths to the configured PDF directory. |
| Test isolation | A WAL startup test reloaded the global database module, replacing its engine and declarative base for later tests. | Run that startup check in a separate process; keep router tests bound to their original in-memory database. Active-provider fixtures now explicitly activate their model. |

The restored screening prompt uses the supplied task criteria and dataset metadata. It does not reintroduce the removed screening-prompt editor. No-criteria tasks retain the existing candidate-storage behavior.

## Verification

Before fixes: **70 passed, 5 failed, 23 errors**. After fixes:

```text
python -m pytest -c backend/pytest.ini backend/tests -q --disable-warnings
107 passed, 305 warnings in 17.87s

node --test frontend/tests/ui.test.cjs
8 passed

git diff --check
clean
```

The nine new legacy regression cases initially failed against the old behavior and now pass. Existing end-to-end screening tests exercise registration, login, criteria, model configuration, task creation, the worker, result counts and CSV export. LLM responses and download outcomes were mocked: no paid model calls or publisher-availability claims are part of this regression run.

The warning count includes existing datetime deprecations and mocked stream cleanup warnings. OCR, external citation-chain retrieval and biological correctness evaluation remain outside this change. Existing historical task states are preserved; this run did not automatically restart old research jobs or re-label saved data.

## Local use

The supported local v2 service is `http://127.0.0.1:8002`. Port 8005 belonged to an isolated temporary UI test service and is not the production entry point. Use the current workspace launcher (`python scripts/run_v2.py`) to load backend changes.
