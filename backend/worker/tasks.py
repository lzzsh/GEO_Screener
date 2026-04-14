import asyncio
import json
import logging
from sqlalchemy import select
from backend.worker.celery_app import celery_app
from backend.database import AsyncSessionLocal
from backend.models import ScreeningTask, ScreeningResult, LLMConfig
from backend.worker.llm_client import LLMClient

logger = logging.getLogger(__name__)

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

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
            select(ScreeningResult).where(ScreeningResult.task_id == task_id, ScreeningResult.status == "pending"))
        pending = res_result.scalars().all()

        for sr in pending:
            await _screen_one(db, task, sr, llm)

        task.status = "done"
        await db.commit()

async def _screen_one(db, task: ScreeningTask, sr: ScreeningResult, llm: LLMClient):
    try:
        result = await llm.screen_dataset(
            dataset_id=sr.dataset_id,
            title=sr.title or "",
            description="",
            criteria_text=task.criteria_text,
        )
        sr.decision = result.get("decision")
        sr.confidence = result.get("confidence")
        sr.summary = result.get("summary")
        sr.rule_checks = json.dumps(result.get("rule_checks", {}))
        sr.status = "done"
    except json.JSONDecodeError:
        try:
            result = await llm.screen_dataset(
                dataset_id=sr.dataset_id, title=sr.title or "", description="",
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
        await db.commit()
