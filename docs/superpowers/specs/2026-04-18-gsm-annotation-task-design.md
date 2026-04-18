# GSM Annotation Task Design

Date: 2026-04-18

## Overview

Add a new independent task type `gsm_annotation` that is created from a completed GSE screening task. It takes only the include/uncertain GSE results, fetches their GSM samples, and runs detailed per-sample LLM annotation using a rich label schema.

## Data Model

### `ScreeningTask` — two new columns

| Column | Type | Default | Notes |
|---|---|---|---|
| `task_type` | String(32) | `"screening"` | `"screening"` or `"gsm_annotation"` |
| `parent_task_id` | Integer (FK, nullable) | NULL | Points to source GSE task; only set for `gsm_annotation` tasks |

Migration: Alembic `ALTER TABLE` with defaults — no existing data affected.

### Existing tables reused as-is

- `ScreeningResult` — one row per GSE in the GSM task (copied from parent, decision preserved)
- `GeoSample` — one row per GSM sample
- `GsmLabel` — stores all new schema fields per sample (key/value pairs)

## Backend API

### New endpoints in `tasks.py`

```
POST /tasks/{task_id}/create-gsm-task
```
- Reads include/uncertain results from parent task
- Creates new ScreeningTask (task_type=gsm_annotation, parent_task_id=task_id)
- Copies ScreeningResult rows (dataset_id, title, decision, n_samples, gse_type, etc.)
- Returns `{"id": new_task_id, "name": ...}`

```
POST /tasks/{task_id}/run-gsm-annotation
```
- Triggers `_run_gsm_task_async(task_id)` via `asyncio.create_task`
- Returns immediately with `{"status": "running_inline"}`

### Fix in existing endpoint

`GET /tasks/{task_id}/results` — add `"id": s.id` to each sample dict (currently missing, breaks `gsmLabelEditor`).

### Existing endpoints unchanged

- `GET /annotate/samples/{sample_id}/labels`
- `POST /tasks/{task_id}/results/{result_id}/fetch-samples`

### New worker function in `worker/tasks.py`

`_run_gsm_task_async(task_id)`:
1. Load all ScreeningResults for the task
2. For each result: call fetch-samples logic if no samples yet
3. For each sample: skip if `gsm_available` label already exists (resume support)
4. Call `llm.annotate_gsm(...)` with GSM metadata + GSE context
5. Store all returned fields as `GsmLabel` rows (key=field name, value=str)
6. Update task `processed` count and commit per sample

## LLM Prompt — `annotate_gsm` replacement

Input context: GSM metadata (gsm_id, title, organism, biosample_id, characteristics) + GSE background (description + detail from `fetch_gse_detail`).

Output JSON schema:

```json
{
  "response": "reasoning text citing evidence",
  "obj": {
    "avail": true,           "avail_conf": 90,
    "start_cell": "iPSC",   "start_cell_conf": 95,
    "raw_data": "Yes",       "raw_data_conf": 85,
    "target_cell": "...",    "target_cell_conf": 90,
    "culture_sys": "2D",     "culture_sys_conf": 95,
    "diff_path": "...",      "diff_path_conf": 80,
    "time_pts": ["D0","D5"], "time_pts_conf": 95,
    "modality": ["scRNA-seq"],"seq_conf": 100,
    "perturb": [...],        "perturb_conf": 85,
    "platform": "10x",       "platform_conf": 95,
    "cell_line": "H9",       "cell_line_conf": 95,
    "sex": "Female",         "sex_conf": 80,
    "age": "Unknown",        "age_conf": 0,
    "reprog": "Episomal",    "reprog_conf": 70,
    "passage": "P35",        "passage_conf": 90,
    "matrix": "Matrigel",    "matrix_conf": 85,
    "medium": "RPMI1640+B27","medium_conf": 90,
    "density": "1.5e5/cm2",  "density_conf": 80,
    "o2_lvl": "21% O2",      "o2_conf": 75
  }
}
```

Storage: `response` stored as key `"response"`, each `obj` field stored as its own `GsmLabel` row.

## Frontend

### Task list page

- Add `task_type` badge: blue "GSE筛选" for `screening`, teal "GSM注释" for `gsm_annotation`
- GSM tasks show "来源: {parent task name}" subtitle

### GSE task detail page (`tasks_detail.html`)

- Add "创建 GSM 注释任务" button in the top action bar
- On click: `POST /tasks/{id}/create-gsm-task`, then redirect to new task detail page

### GSM task detail page (new `gsm_task_detail.html`)

**Stats row:** Total GSEs | Total GSMs | Annotated GSMs | avail=true count

**"Run GSM Annotation" button:** triggers annotation, polls every 3s (same pattern as GSE annotation fix)

**Main table (one row per GSE):**
Accession | Title | Samples | 原决策 | 已注释GSM数 | 展开

**Expanded GSM sub-table (one row per sample):**
GSM ID | avail | start_cell | target_cell | culture_sys | modality | platform | raw_data | 详情

**"详情" expansion:** shows diff_path, perturb (formatted), cell_line, sex, age, reprog, passage, matrix, medium, density, o2_lvl, response (reasoning text), all conf scores

## Field Definitions

| Key | Description | Example |
|---|---|---|
| avail | Meets all inclusion criteria | true/false |
| start_cell | Starting stem cell type | "iPSC" / "ESC" |
| raw_data | Raw sequencing data available | "Yes" / "No" / "Unspecified" |
| target_cell | Differentiation endpoint | "Cardiomyocyte" |
| culture_sys | Culture geometry | "2D" / "3D" / "2D/3D Mixed" / "Unknown" |
| diff_path | Differentiation method/protocol | "Gastruloid-based cardiac" |
| modality | Single-cell data types (array) | ["scRNA-seq", "scATAC-seq"] |
| perturb | Perturbation objects array | [{type, method, dosage, start/end/duration}] |
| platform | Sequencing platform | "10x Genomics" |
| cell_line | Cell line name | "H9 (WA09)" |
| sex | Donor sex | "Female" |
| age | Donor age | "Unknown" |
| reprog | Reprogramming method | "Episomal" |
| passage | Passage number | "P35" |
| matrix | Extracellular matrix | "Matrigel (1:100)" |
| medium | Culture medium | "RPMI1640 + B27" |
| density | Seeding density | "1.5e5 cells/cm2" |
| o2_lvl | Oxygen level | "21% O2" |
| response | LLM reasoning text | full sentence |
