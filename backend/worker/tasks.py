import asyncio
import json
import logging
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
from backend.worker.celery_app import celery_app
from backend.database import AsyncSessionLocal
from backend.models import ScreeningTask, ScreeningResult, LLMConfig, GeoLabel, GsmLabel, GeoSample, AnnotationSchema
from backend.worker.geo_fetcher import fetch_gse_detail, fetch_gsm_samples
from backend.worker.llm_client import LLMClient
from backend.worker.pdf_fetcher import fetch_pdf

logger = logging.getLogger(__name__)
MAX_PROMPT_GSM_SAMPLES = 25

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _parse_label_schema(label_schema_json: str) -> dict:
    """Parse label schema with fallback for legacy format."""
    data = json.loads(label_schema_json)
    if isinstance(data, list):
        # Legacy format: list of strings → convert to new format
        gse_labels = [{"name": d, "type": "free_text", "description": d} for d in data]
        return {"gse": gse_labels, "gsm": []}
    return data  # New format: {"gse": [...], "gsm": [...]}


def _stored_samples_to_dicts(sr: ScreeningResult) -> list[dict]:
    return [
        {
            "gsm_id": sample.gsm_id,
            "title": sample.title or "",
            "organism": sample.organism or "",
            "biosample_id": sample.biosample_id or "",
        }
        for sample in sr.samples
    ]


def _format_sample_for_prompt(sample: dict) -> str:
    parts = [
        sample.get("gsm_id", ""),
        sample.get("title", ""),
        sample.get("organism", ""),
        sample.get("source_name", ""),
    ]
    line = " | ".join(part for part in parts if part)
    extras = []
    characteristics = sample.get("characteristics") or {}
    if isinstance(characteristics, dict):
        extras.extend(f"{key}={value}" for key, value in characteristics.items() if value)
    for key in ["library_strategy", "molecule", "growth_protocol", "treatment_protocol", "biosample_id"]:
        value = sample.get(key)
        if value:
            extras.append(f"{key}={value}")
    if extras:
        line = f"{line} ({'; '.join(extras)})" if line else "; ".join(extras)
    return line


def _build_geo_metadata_context(
    base_description: str,
    detail: dict | None,
    samples: list[dict],
    has_raw_data: bool | None = None,
) -> str:
    sections = [f"GSE Summary / Description: {base_description or ''}".strip()]
    if has_raw_data is not None:
        sections.append(f"GEO Raw Data Availability: {'yes' if has_raw_data else 'no'}")
    detail = detail or {}
    if detail.get("abstract"):
        sections.append(f"GSE Abstract: {detail['abstract']}")
    if detail.get("overall_design"):
        sections.append(f"GSE Overall Design: {detail['overall_design']}")
    relations = detail.get("series_relations") or []
    if relations:
        relation_text = "; ".join(
            " ".join(part for part in [rel.get("type", ""), rel.get("accession", "")] if part)
            for rel in relations
        )
        if relation_text:
            sections.append(f"Series Relations: {relation_text}")
    if samples:
        rendered = [_format_sample_for_prompt(sample) for sample in samples[:MAX_PROMPT_GSM_SAMPLES]]
        rendered = [line for line in rendered if line]
        if rendered:
            sections.append("GSM Samples:\n" + "\n".join(f"- {line}" for line in rendered))
        if len(samples) > MAX_PROMPT_GSM_SAMPLES:
            sections.append(f"GSM Samples Truncated: showing {MAX_PROMPT_GSM_SAMPLES} of {len(samples)}")
    return "\n\n".join(section for section in sections if section)


async def _geo_context_for_result(sr: ScreeningResult) -> str:
    if not (sr.dataset_id or "").upper().startswith("GSE"):
        return sr.description or ""
    detail = {}
    samples = []
    try:
        detail = await fetch_gse_detail(sr.dataset_id)
        if detail and detail.get("pmid") and not sr.pmid:
            sr.pmid = detail["pmid"]
    except Exception as exc:
        logger.warning("GSE detail fetch failed for %s: %s", sr.dataset_id, exc)
    try:
        samples = await fetch_gsm_samples(sr.dataset_id)
    except Exception as exc:
        logger.warning("GSM fetch failed for %s: %s", sr.dataset_id, exc)
    if not samples:
        samples = _stored_samples_to_dicts(sr)
    return _build_geo_metadata_context(sr.description or "", detail, samples, sr.has_raw_data)

@celery_app.task(bind=True, name="worker.tasks.run_screening")
def run_screening(self, task_id: int):
    _run(_run_screening_async(task_id))

async def _run_screening_async(task_id: int):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return

        task.status = "running"
        await db.commit()

        cfg_result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id, LLMConfig.is_active == True))
        cfg = cfg_result.scalar_one_or_none()
        if not cfg or not cfg.api_key:
            task.status = "error"
            await db.commit()
            return

        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature)

        res_result = await db.execute(
            select(ScreeningResult)
            .options(selectinload(ScreeningResult.samples))
            .where(ScreeningResult.task_id == task_id, ScreeningResult.status == "pending"))
        pending = res_result.scalars().all()

        for sr in pending:
            await _screen_one(db, task, sr, llm)

        task.status = "done"
        await db.commit()

async def _screen_one(db, task: ScreeningTask, sr: ScreeningResult, llm: LLMClient):
    try:
        description = await _geo_context_for_result(sr)
        result = await llm.screen_dataset(
            dataset_id=sr.dataset_id,
            title=sr.title or "",
            description=description,
            criteria_text=task.criteria_text,
        )
        sr.decision = result.get("decision")
        sr.confidence = result.get("confidence")
        sr.summary = result.get("summary")
        sr.rule_checks = json.dumps(result.get("rule_checks", {}))
        sr.status = "done"
    except json.JSONDecodeError:
        try:
            description = await _geo_context_for_result(sr)
            result = await llm.screen_dataset(
                dataset_id=sr.dataset_id, title=sr.title or "", description=description,
                criteria_text=task.criteria_text + "\n\nIMPORTANT: Return ONLY raw JSON, no markdown.",
            )
            sr.decision = result.get("decision")
            sr.confidence = result.get("confidence")
            sr.summary = result.get("summary")
            sr.rule_checks = json.dumps(result.get("rule_checks", {}))
            sr.status = "done"
        except Exception as e:
            sr.status = "error"
            sr.error_msg = str(e)
    except Exception as e:
        sr.status = "error"
        sr.error_msg = str(e)
        logger.warning("LLM error for %s: %s", sr.dataset_id, e)
    finally:
        task.processed += 1
        if sr.decision == "include":
            task.included_count += 1
        elif sr.decision == "exclude":
            task.excluded_count += 1
        elif sr.decision == "uncertain":
            task.uncertain_count += 1
        await db.commit()


@celery_app.task(bind=True, name="worker.tasks.run_annotation")
def run_annotation(self, task_id: int):
    _run(_run_annotation_async(task_id))


async def _run_annotation_async(task_id: int):
    async with AsyncSessionLocal() as db:
        task = (await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))).scalar_one_or_none()
        if not task or not task.label_schema:
            return
        schema = _parse_label_schema(task.label_schema)
        gse_labels = schema.get("gse", [])

        # Get schema name for prompt loading
        schema_name = "default"
        if task.annotation_schema_id:
            annotation_schema = (await db.execute(
                select(AnnotationSchema).where(AnnotationSchema.id == task.annotation_schema_id)
            )).scalar_one_or_none()
            if annotation_schema:
                schema_name = annotation_schema.name

        cfg = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id, LLMConfig.is_active == True))).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return
        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        results = (await db.execute(
            select(ScreeningResult)
            .options(selectinload(ScreeningResult.samples), selectinload(ScreeningResult.labels))
            .where(ScreeningResult.task_id == task_id)
        )).scalars().all()

        # Only process results that have no final_conclusion label yet (resume support)
        pending_results = [
            sr for sr in results
            if not any(l.key == "final_conclusion" for l in sr.labels)
        ]

        conclusion_to_decision = {"可用": "include", "不可用": "exclude", "待确认": "uncertain"}

        for sr in pending_results:
            try:
                description = await _geo_context_for_result(sr)
                extracted = await llm.extract_labels(
                    dataset_id=sr.dataset_id, title=sr.title or "",
                    description=description, gse_labels=gse_labels,
                    schema_name=schema_name,
                )
                existing_labels = (await db.execute(
                    select(GeoLabel).where(GeoLabel.result_id == sr.id)
                )).scalars().all()
                existing_by_key = {label.key: label for label in existing_labels}
                for key, value in extracted.items():
                    existing = existing_by_key.get(key)
                    if existing and existing.source == "human":
                        continue
                    if existing:
                        existing.value = str(value) if value is not None else None
                    else:
                        db.add(GeoLabel(result_id=sr.id, key=key,
                                        value=str(value) if value is not None else None, source="llm"))
                # Sync decision from final_conclusion
                final = extracted.get("final_conclusion")
                if final and final in conclusion_to_decision:
                    sr.decision = conclusion_to_decision[final]
                    sr.status = "done"
                await db.commit()
            except OperationalError as exc:
                await db.rollback()
                logger.warning("Annotation DB error for %s: %s", sr.dataset_id, exc)
            except Exception as exc:
                await db.rollback()
                logger.warning("Annotation LLM error for %s: %s", sr.dataset_id, exc)

        # Recalculate task counts from all results
        all_results = (await db.execute(
            select(ScreeningResult).where(ScreeningResult.task_id == task_id)
        )).scalars().all()
        task.included_count = sum(1 for r in all_results if r.decision == "include")
        task.excluded_count = sum(1 for r in all_results if r.decision == "exclude")
        task.uncertain_count = sum(1 for r in all_results if r.decision == "uncertain")
        task.processed = sum(1 for r in all_results if r.status == "done")
        await db.commit()


async def _run_single_result_annotation_async(result_id: int):
    """Re-annotate a single GSE result, overwriting existing llm labels."""
    async with AsyncSessionLocal() as db:
        sr = (await db.execute(
            select(ScreeningResult)
            .options(selectinload(ScreeningResult.samples), selectinload(ScreeningResult.labels))
            .where(ScreeningResult.id == result_id)
        )).scalar_one_or_none()
        if not sr:
            return
        task = (await db.execute(
            select(ScreeningTask).where(ScreeningTask.id == sr.task_id)
        )).scalar_one_or_none()
        if not task or not task.label_schema:
            return

        # Get schema name for prompt loading
        schema_name = "default"
        if task.annotation_schema_id:
            annotation_schema = (await db.execute(
                select(AnnotationSchema).where(AnnotationSchema.id == task.annotation_schema_id)
            )).scalar_one_or_none()
            if annotation_schema:
                schema_name = annotation_schema.name

        cfg = (await db.execute(
            select(LLMConfig).where(LLMConfig.owner_id == task.owner_id, LLMConfig.is_active == True)
        )).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return
        schema = _parse_label_schema(task.label_schema)
        gse_labels = schema.get("gse", [])
        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        conclusion_to_decision = {"可用": "include", "不可用": "exclude", "待确认": "uncertain"}
        try:
            description = await _geo_context_for_result(sr)
            extracted = await llm.extract_labels(
                dataset_id=sr.dataset_id, title=sr.title or "",
                description=description, gse_labels=gse_labels,
                schema_name=schema_name,
            )
            existing_by_key = {l.key: l for l in sr.labels}
            for key, value in extracted.items():
                existing = existing_by_key.get(key)
                if existing and existing.source == "human":
                    continue
                if existing:
                    existing.value = str(value) if value is not None else None
                else:
                    db.add(GeoLabel(result_id=sr.id, key=key,
                                    value=str(value) if value is not None else None, source="llm"))
            final = extracted.get("final_conclusion")
            if final and final in conclusion_to_decision:
                sr.decision = conclusion_to_decision[final]
                sr.status = "done"
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.warning("Single result annotation error for %s: %s", sr.dataset_id, exc)


async def _run_gsm_annotation_async(result_id: int):
    async with AsyncSessionLocal() as db:
        sr = (await db.execute(
            select(ScreeningResult)
            .options(selectinload(ScreeningResult.samples))
            .where(ScreeningResult.id == result_id)
        )).scalar_one_or_none()
        if not sr:
            return
        task = (await db.execute(
            select(ScreeningTask).where(ScreeningTask.id == sr.task_id)
        )).scalar_one_or_none()
        if not task:
            return
        cfg = (await db.execute(
            select(LLMConfig).where(LLMConfig.owner_id == task.owner_id, LLMConfig.is_active == True)
        )).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return
        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        gse_summary = sr.description or ""
        for sample in sr.samples:
            try:
                # Resume support: skip samples already annotated
                existing = (await db.execute(
                    select(GsmLabel).where(GsmLabel.sample_id == sample.id)
                )).scalars().all()
                existing_by_key = {l.key: l for l in existing}
                if "gsm_available" in existing_by_key:
                    continue
                extracted = await llm.annotate_gsm(
                    gsm_id=sample.gsm_id,
                    title=sample.title or "",
                    organism=sample.organism or "",
                    biosample_id=sample.biosample_id or "",
                    characteristics="",
                    gse_summary=gse_summary,
                )
                for key, value in extracted.items():
                    ex = existing_by_key.get(key)
                    if ex and ex.source == "human":
                        continue
                    if ex:
                        ex.value = str(value) if value is not None else None
                    else:
                        db.add(GsmLabel(sample_id=sample.id, key=key,
                                        value=str(value) if value is not None else None,
                                        source="llm"))
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("GSM annotation error for %s: %s", sample.gsm_id, exc)


async def _run_gsm_task_async(task_id: int):
    async with AsyncSessionLocal() as db:
        task = await db.get(
            ScreeningTask, task_id,
            options=[selectinload(ScreeningTask.results).selectinload(ScreeningResult.samples).selectinload(GeoSample.labels)]
        )
        if not task:
            logger.error("GSM task %s not found", task_id)
            return

        cfg = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id, LLMConfig.is_active == True))).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            logger.error("No LLM config for user %s", task.owner_id)
            task.status = "error"
            await db.commit()
            return

        schema = _parse_label_schema(task.label_schema) if task.label_schema else {}
        gsm_labels = schema.get("gsm", [])

        # Get schema name for prompt loading
        schema_name = "default"
        if task.annotation_schema_id:
            annotation_schema = (await db.execute(
                select(AnnotationSchema).where(AnnotationSchema.id == task.annotation_schema_id)
            )).scalar_one_or_none()
            if annotation_schema:
                schema_name = annotation_schema.name

        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        task.status = "running"
        await db.commit()

        try:
            for result in task.results:
                # Fetch samples — keep full metadata in memory for LLM
                fetched_meta: dict[str, dict] = {}
                # Query DB directly to avoid stale in-memory relationship state
                db_gsm_ids: set[str] = {r[0] for r in (await db.execute(
                    select(GeoSample.gsm_id).where(GeoSample.result_id == result.id)
                )).fetchall()}

                if not db_gsm_ids:
                    try:
                        fetched = await fetch_gsm_samples(result.dataset_id)
                        seen: set[str] = set()
                        for s in fetched:
                            fetched_meta[s["gsm_id"]] = s
                            if s["gsm_id"] not in seen:
                                seen.add(s["gsm_id"])
                                db.add(GeoSample(
                                    result_id=result.id,
                                    gsm_id=s.get("gsm_id", ""),
                                    title=s.get("title"),
                                    organism=s.get("organism"),
                                    biosample_id=s.get("biosample_id"),
                                ))
                        await db.commit()
                        await db.refresh(result, ["samples"])
                    except Exception as e:
                        logger.error("Failed to fetch samples for %s: %s", result.dataset_id, e)
                        continue
                else:
                    # Re-fetch to get full metadata (characteristics, protocols)
                    try:
                        fetched = await fetch_gsm_samples(result.dataset_id)
                        fetched_meta = {s["gsm_id"]: s for s in fetched}
                    except Exception:
                        pass

                gse_detail = None
                try:
                    gse_detail = await fetch_gse_detail(result.dataset_id)
                except Exception:
                    pass

                context = _build_geo_metadata_context(
                    result.description or "",
                    gse_detail,
                    [],
                    result.has_raw_data,
                )

                for sample in result.samples:
                    # Skip if already annotated (resume support)
                    existing_labels = (await db.execute(
                        select(GsmLabel).where(GsmLabel.sample_id == sample.id)
                    )).scalars().all()
                    existing_by_key = {lbl.key: lbl for lbl in existing_labels}
                    if "avail" in existing_by_key:
                        continue

                    meta = fetched_meta.get(sample.gsm_id, {})
                    chars = meta.get("characteristics") or {}
                    lines = []
                    for k, v in chars.items():
                        lines.append(f"Characteristics tag='{k}': {v}")
                    for field, label in (
                        ("source_name", "Source"),
                        ("molecule", "Molecule"),
                        ("library_strategy", "Library-Strategy"),
                        ("library_source", "Library-Source"),
                        ("data_processing", "Data-Processing"),
                        ("growth_protocol", "Growth-Protocol"),
                        ("treatment_protocol", "Treatment-Protocol"),
                    ):
                        val = meta.get(field, "")
                        if val:
                            lines.append(f"{label}: {val}")
                    supplementary_files = meta.get("supplementary_files") or []
                    for file_meta in supplementary_files[:10]:
                        url = file_meta.get("url", "")
                        file_type = file_meta.get("type", "")
                        if url:
                            lines.append(f"Supplementary-Data ({file_type}): {url}")
                    full_characteristics = "\n".join(lines)

                    try:
                        annotation = await llm.annotate_gsm(
                            gsm_id=sample.gsm_id,
                            title=sample.title or "",
                            organism=sample.organism or "",
                            biosample_id=sample.biosample_id or "",
                            characteristics=full_characteristics[:3000],
                            gse_summary=context[:2000],
                            gsm_labels=gsm_labels,
                            schema_name=schema_name,
                        )
                        if annotation:
                            for key, value in annotation.items():
                                label_value = str(value) if value is not None else None
                                existing = existing_by_key.get(key)
                                if existing and existing.source == "human":
                                    continue
                                if existing:
                                    existing.value = label_value
                                    existing.source = "llm"
                                else:
                                    db.add(GsmLabel(sample_id=sample.id, key=key,
                                                    value=label_value,
                                                    source="llm"))
                        await db.commit()
                    except Exception as e:
                        logger.error("Failed to annotate %s: %s", sample.gsm_id, e)
                        continue

                task.processed += 1
                await db.commit()

            task.status = "done"
            await db.commit()
        except Exception as e:
            logger.error("Error in _run_gsm_task_async for task %s: %s", task_id, e)
            task.status = "error"
            await db.commit()


async def _search_pmid_by_title(title: str) -> str | None:
    """Search PubMed for a PMID by paper title using E-utilities."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": f"{title}[Title]", "retmax": 1, "retmode": "json"},
            )
            r.raise_for_status()
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            return ids[0] if ids else None
    except Exception as e:
        logger.warning("PubMed title search failed: %s", e)
        return None


async def _fetch_one_paper(result_id: int):
    """Fetch PDF for a single ScreeningResult in its own DB session."""
    async with AsyncSessionLocal() as db:
        sr = await db.get(ScreeningResult, result_id)
        if not sr:
            return
        if not sr.pmid and sr.title:
            try:
                sr.pmid = await _search_pmid_by_title(sr.title)
                if sr.pmid:
                    await db.commit()
            except Exception as e:
                logger.warning("pmid search failed for %s: %s", sr.dataset_id, e)
        if not sr.pmid:
            return
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


async def _fetch_papers_async(task_id: int):
    async with AsyncSessionLocal() as db:
        res_result = await db.execute(
            select(ScreeningResult.id).where(
                ScreeningResult.task_id == task_id,
                ScreeningResult.decision.in_(["include", "uncertain"]),
                ScreeningResult.pdf_status == "none",
            )
        )
        result_ids = [row[0] for row in res_result.all()]

    # PubMed rate limit: 3 req/s without API key — use semaphore of 3 + small delay
    semaphore = asyncio.Semaphore(3)

    async def fetch_with_sem(rid):
        async with semaphore:
            await _fetch_one_paper(rid)
            await asyncio.sleep(0.4)  # ~2.5 req/s, safely under the 3/s limit

    await asyncio.gather(*[fetch_with_sem(rid) for rid in result_ids])


async def _run_paper_calibration_async(task_id: int):
    import pdfplumber

    async with AsyncSessionLocal() as db:
        task_result = await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))
        task = task_result.scalar_one_or_none()
        if not task:
            return

        cfg_result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id, LLMConfig.is_active == True))
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
