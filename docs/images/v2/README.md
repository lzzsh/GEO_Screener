# v2 screenshot provenance

Captured from the actual GEO Screener v2 browser interface on 2026-09-10. `screening.png` is the user-supplied original PNG (4480 × 2370), copied byte-for-byte. The remaining images use Playwright headless Chrome at deviceScaleFactor=2: 1440 × 1000 CSS pixels for demo pages, 2240 × 1185 for the expanded real screening examples. All assets are lossless PNGs. No upscaling, generation or compositing was used. [capture.json](capture.json) records dimensions, source categories and SHA256 checksums.

The main screening screenshot shows the real ten-publication validation task at an intermediate stage, including protocol failures. Its Completed badge refers to screening/annotation. The two expanded screening examples are real saved records viewed with the user's authorization, without changing their annotations or decisions. They illustrate saved model judgments, not an independent assessment of screening accuracy.

`gsm-protocol.png` shows real GSM8502816 with an independent reviewed revision and Methods evidence, captured at 3840 × 2400. `methods-supplements.png` preserves a real article-level baseline with a DOCX supplement; it is a historical draft, not the final GSM result. Both come from the isolated validation service. The remaining pages use an isolated demo service with no API keys. GSE1/GSM1 and the protocol methods document are synthetic UI fixtures, not real study evidence or experimental recommendations. The search image shows query entry before submission; model defaults and schema labels are application configuration.

| Image | Route | Language / view |
|---|---|---|
| [search.png](search.png) | `/search` | English; prepared query |
| [screening.png](screening.png) | `/tasks/1/detail` | English; user-selected real validation screenshot, expanded reasons and GSM samples |
| [screening-include.png](screening-include.png) | `/tasks/21/detail` | Chinese; GSE263372, saved inclusion reasons |
| [screening-exclude.png](screening-exclude.png) | `/tasks/21/detail` | Chinese; GSE244778, saved exclusion reasons |
| [rules.png](rules.png) | `/criteria-page` | English; read-only default schema, original research labels |
| [models.png](models.png) | `/settings` | English; OrcaRouter first and recommended, no configured keys |
| [gsm-protocol.png](gsm-protocol.png) | `/protocols/3` | English; real GSM8502816, reviewed with explicit NA timings |
| [methods-supplements.png](methods-supplements.png) | `/protocols/2` | English; real article-level baseline, DOCX supplement and coverage |
| [protocol-review.png](protocol-review.png) | `/protocols/2` | English; human revision and event table |
| [protocol-exports.png](protocol-exports.png) | `/protocols/2` | English; source evidence and export menu |
| [guide-en.png](guide-en.png) | `/guide` | English guide |
| [guide-zh.png](guide-zh.png) | `/guide` | Chinese guide |

The demo IDs/routes document the capture session; they are not public links or records expected in a fresh installation. The normal local v2 entry point remains `http://127.0.0.1:8002`.
