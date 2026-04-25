# GEO Screener

A web application for searching, screening, and annotating GEO (Gene Expression Omnibus) datasets. It combines automated GEO metadata retrieval with LLM-based screening and sample-level annotation, designed to accelerate systematic dataset curation.

## Quick Start (Docker)

**Prerequisites:** Docker and Docker Compose.

```bash
git clone https://github.com/lzzsh/GEO_Screener.git
cd GEO_Screener

cp docker/.env.example docker/.env
# Edit docker/.env — set SECRET_KEY and your LLM API key

mkdir -p data pdfs
docker compose -f docker/docker-compose.yml up -d
```

Open [http://localhost:8000](http://localhost:8000), register an account, and configure your LLM provider under **Settings**.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Random string for JWT signing |
| `DATABASE_URL` | No | Defaults to `sqlite:////data/geo_search.db` |
| `REDIS_URL` | No | Defaults to `redis://redis:6379/0` |

LLM credentials are configured through the UI (Settings page), not via environment variables. They are stored in the local database and never committed to git.

---

## Annotation Schemas

An annotation schema defines what fields the LLM extracts from each GSE dataset and each GSM sample. You can create multiple schemas for different research questions and switch between them at any time.

### Creating a schema

1. Go to **Criteria** (top navigation).
2. In the left panel under **Annotation Schemas**, click **+ New Schema**.
3. Give it a name and optionally a description.
4. Define **GSE labels** — fields extracted at the dataset level (e.g. sequencing modality, cell type, differentiation endpoint).
5. Define **GSM labels** — fields extracted at the individual sample level (e.g. passage number, treatment condition).
6. Each label has a name, type (`enum` or `free_text`), and optional allowed values for enum fields.
7. Click **Save**.

> **Note:** If you want to run GSM-level annotation, the schema must have at least one GSM label defined. Tasks will fail with a clear error if GSM labels are missing.

### Setting the active schema

The active schema is automatically applied to all new screening and annotation tasks you create.

1. In the **Annotation Schemas** panel, find the schema you want to use.
2. Click **Set active** next to it.
3. A **✓ Active** badge appears on the selected schema.

To revert to the built-in default schema, click **Set active** on the **Default** entry at the top of the list.

### Customizing prompts

Each schema can have its own LLM prompt templates. Prompts are loaded from:

```
backend/prompts/<schema-name>/label_prompt.txt        # GSE annotation
backend/prompts/<schema-name>/gsm_label_prompt.txt    # GSM annotation
```

If a schema-specific prompt file is missing, the system falls back to `backend/prompts/default/`. You can copy and edit the default prompts as a starting point.

The `{gse_label_spec}` / `{gsm_label_spec}` placeholders in the prompt templates are automatically filled with the label definitions from your schema.

---

## Workflow

1. **Search** — query GEO by keyword or accession on the Search page.
2. **Screen** — create a screening task with inclusion/exclusion criteria. The LLM evaluates each dataset and returns include / exclude / uncertain decisions.
3. **Annotate GSE** — run LLM annotation on included datasets to extract structured metadata fields defined by your active schema.
4. **Annotate GSM** — create a GSM annotation task to annotate individual samples within each dataset.
5. **Review** — manually override decisions and labels inline. Changes to `final_conclusion` labels sync task statistics immediately.
6. **Export** — download results as CSV from the task detail page.

---

## Settings

Go to **Settings** to configure your LLM provider. Supported providers include OpenAI, DeepSeek, and any OpenAI-compatible endpoint. Your API key is stored only in the local database (`data/geo_search.db`) and is never exposed in the source code or git history.
