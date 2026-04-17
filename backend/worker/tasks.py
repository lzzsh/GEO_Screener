import asyncio
import json
import logging
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
from backend.worker.celery_app import celery_app
from backend.database import AsyncSessionLocal
from backend.models import ScreeningTask, ScreeningResult, LLMConfig, GeoLabel
from backend.worker.geo_fetcher import fetch_gse_detail, fetch_gsm_samples
from backend.worker.llm_client import LLMClient

logger = logging.getLogger(__name__)
MAX_PROMPT_GSM_SAMPLES = 25

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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

        cfg_result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id))
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
    import json as _json
    async with AsyncSessionLocal() as db:
        task = (await db.execute(select(ScreeningTask).where(ScreeningTask.id == task_id))).scalar_one_or_none()
        if not task or not task.label_schema:
            return
        dimensions = _json.loads(task.label_schema)
        cfg = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == task.owner_id))).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return
        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        results = (await db.execute(
            select(ScreeningResult)
            .options(selectinload(ScreeningResult.samples))
            .where(ScreeningResult.task_id == task_id)
        )).scalars().all()

        conclusion_to_decision = {"可用": "include", "不可用": "exclude", "待确认": "uncertain"}

        for sr in results:
            try:
                description = await _geo_context_for_result(sr)
                extracted = await llm.extract_labels(
                    dataset_id=sr.dataset_id, title=sr.title or "",
                    description=description, dimensions=dimensions,
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
