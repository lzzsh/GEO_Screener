# Design: Frontend Redesign + GEO Data Enrichment

Date: 2026-04-16

## Overview

Two independent improvements:
1. Enrich GEO data by fetching missing fields from NCBI MINiML format on demand
2. Redesign frontend layout and information architecture to match reference design

---

## Part 1: GEO Data Enrichment

### Problem

Current `geo_fetcher.py` only uses NCBI esummary API, which lacks:
- BioProject ID (PRJNA number)
- BioProject/FTP link
- Abstract (paper summary, distinct from GEO summary)
- Overall design
- Contact info (name, email, address, city, state, zip, country, department)
- Supplementary data files (name + URL)
- GSM cell count (best-effort from MINiML Channel nodes)

### Approach: On-demand eFetch

Fetch missing fields only when user opens a detail modal. No impact on search speed.

### New Backend Endpoint

`GET /geo/gse/{gse_id}/detail`

Calls NCBI eFetch with `db=gds&rettype=miniml&retmode=xml` for the GSE accession.
Parses MINiML XML and returns:

```json
{
  "gse_id": "GSE305128",
  "bioproject_id": "PRJNA1304480",
  "bioproject_link": "ftp://ftp.ncbi.nlm.nih.gov/geo/series/...",
  "abstract": "...",
  "overall_design": "...",
  "contact": {
    "name": "Jens Magnusson",
    "email": "jens.magnusson@ki.se",
    "address": "Alfred Nobels Allé 8",
    "city": "Stockholm",
    "state": "",
    "zip": "14152",
    "country": "Sweden",
    "department": ""
  },
  "supplementary_files": [
    {
      "name": "GSE305128_RAW.tar",
      "url": "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE305nnn/GSE305128/suppl/GSE305128_RAW.tar"
    }
  ]
}
```

### GSM Cell Count

The existing `/geo/gse/{id}/samples` endpoint returns GSM list. Extend `_efetch_gsm_summaries` to attempt parsing `cell_count` from esummary `taxon` or characteristic fields. If unavailable, return `null`.

### Files to Change

- `backend/worker/geo_fetcher.py` — add `fetch_gse_detail(gse_id)` function using eFetch MINiML
- `backend/routers/geo.py` — add `GET /geo/gse/{gse_id}/detail` route
- `backend/tests/test_geo_fetcher.py` — add tests for new function

---

## Part 2: Frontend Redesign

### Layout

Replace top navigation with a fixed left sidebar (160px wide).

Sidebar nav items:
- 数据表
- 论文列表 (Search)
- 标签管理
- 配置管理
- 任务管理
- 评估管理
- 样本&混样表

Main content area fills remaining width.

### Search Page (论文列表)

**Top filter bar:**
- Accession 查询 input (with dropdown type selector)
- 请选择标签 dropdown
- 请选择搜索类型 dropdown
- 筛选用户 dropdown
- 过滤标签 dropdown

**Action bar (right-aligned):** 导出 | 查询 | 重置

**Table columns:**
| Column | Notes |
|--------|-------|
| Accession | GSE ID + BioProject ID (small, gray) |
| 标题 | Truncated with tooltip |
| Sample count | |
| 搜索标签 | Truncated |
| 实验类型 | Truncated |
| 论文更新日期 | |
| 最后更新日期 | |
| 原始数据是否可用 | Green checkmark icon |
| 标签 | |
| 状态 | Colored dot + text (新增/已标注 etc.) |
| 操作 | 标注 link |

**Pagination:** Bottom bar — "第 X-Y 条/总共 Z 条" + page numbers + 每页条数 selector

### Detail Modal (论文详情)

Full-screen or large modal triggered by clicking a row. Sections:

**Header:** 论文标题 (full text)

**Section 1 — 数据信息**
- 原始数据ID: PRJNA...
- 原始数据链接: ftp://...

**Section 2 — 其他信息**
- 论文摘要: full abstract text
- 整体设计: overall design text

**Section 3 — 联系人信息** (two-column grid)
- Left: 联系人姓名, 联系人地址, 联系人州, 联系人国家
- Right: 联系人邮箱, 联系人城市, 联系人邮编, 联系人部门

**Section 4 — Supplementary data files**
Table: 文件名称 | 下载地址

**Pagination** at bottom of modal for navigating between entries.

### Task Detail GSM Panel

Existing GSM sample table columns updated to:
| Column | Notes |
|--------|-------|
| 样本名称 | GSM ID, blue link |
| 标题 | Full title |
| 生物体 | Organism |
| 生物样本关系ID | BioSample ID, blue link |
| cellCount | Integer or — |
| 标签 | Label icon |
| 操作 | 标记 + edit icon |

### Files to Change

- `frontend/templates/base.html` — replace top nav with left sidebar
- `frontend/templates/search.html` — new filter bar, table columns, detail modal with 4 sections
- `frontend/templates/tasks_detail.html` — update GSM panel columns
- `frontend/templates/library_detail.html` — update detail modal to match new 4-section layout

---

## Out of Scope

- Post-processing field for GSM (not needed per user)
- Mobile responsive redesign
- Any new backend models or DB schema changes
