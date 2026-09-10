# v2 UI refresh

Starting point: `31103aa`, pushed to `origin/codex/v2-protocol` before UI changes.
The user selected a light research workspace with blue emphasis, clear tables and evidence panels.

Scope:

- Shared navigation: current-page indication, consistent typography, keyboard focus and mobile navigation.
- Model settings: actual active connection, separate pending selection, provider cards, accessible configuration dialog, retained custom endpoints and explicit request errors.
- Protocol jobs: understandable empty state, compact progress, readable status badges.
- Protocol workspace: source list, extraction content and evidence with distinct headings; grouped field editing and clear primary actions; responsive layout.
- Screening detail: a distinct selected-literature action strip linked to Protocol extraction.
- Chinese / English: shared catalog for server-rendered copy and browser interactions; persistent language cookie; navigation switch on desktop and mobile. Preserve literature text, user-defined schemas, protocol values and all 24 TSV columns. Warn before discarding unsaved settings or protocol revisions during language changes.

Validation: provider endpoint persistence regression; settings-state and failure recovery checks; template render checks; browser inspection of desktop and narrow layouts using isolated synthetic data. Preserve original screening and export contracts. Do not run paid model calls for visual verification.

## Validation results (2026-09-10)

- Backend targeted suite: **42 passed** across UI language rendering, model configuration, OrcaRouter request compatibility, pages, protocol documents/schema/review/export, GEO routes, v2 launcher and task dispatch. Existing deprecation warnings and mocked streaming cleanup warnings remain; this is not a claim that the legacy full suite passes.
- Frontend state tests: **7 passed** (`node --test frontend/tests/ui.test.cjs`), covering language preference/cancellation, preserving research content, pending provider selection, key clearing, network failures, failed connection responses and preserving edited protocol drafts during refresh.
- Browser: English settings and provider dialog; English protocol review and four field groups; Chinese switching; desktop and 390px layout. Protocol page has no horizontal document overflow at 390px. PDF evidence defaults to page text, with an optional PDF preview and original-file link.
- Endpoint regression: updating DeepSeek credentials or the active model retains an existing Pi API URL when no replacement URL is supplied.

UI checks used an isolated synthetic database. No paid extraction or model requests were made for this UI refresh.

## Bilingual user guide

`/guide` is linked from the shared navigation. It covers model/rule setup, GEO screening, GSM annotation and libraries, source selection and PDF material limits, extraction states and retry, evidence review and revisions, field conventions, exports, a fictional timing example, the 24-column reference and troubleshooting. Instructions distinguish automatic quote/format checks from scientific verification and document the current OCR and citation-retrieval limits.

Guide validation: **9 passed** with `python -m pytest backend/tests/test_ui_i18n.py backend/tests/test_pages.py -q --disable-warnings`; both languages render, including the complete guide. Chinese desktop layout was inspected in the browser on port 8002.
