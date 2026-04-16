from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.label_schema import default_label_schema_json
from backend.models import ScreeningResult, GeoLabel, ScreeningTask, User
from backend.task_dispatch import dispatch_or_run_inline
from backend.auth import get_current_user

router = APIRouter(prefix="/annotate", tags=["annotate"])


class LabelUpsert(BaseModel):
    key: str
    value: str | None = None


@router.get("/results/{result_id}/labels")
async def get_labels(result_id: int, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(GeoLabel).where(GeoLabel.result_id == result_id)
    )).scalars().all()
    return [{"id": r.id, "key": r.key, "value": r.value, "source": r.source} for r in rows]


@router.put("/results/{result_id}/labels")
async def upsert_label(result_id: int, body: LabelUpsert,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    existing = (await db.execute(
        select(GeoLabel).where(GeoLabel.result_id == result_id, GeoLabel.key == body.key)
    )).scalar_one_or_none()
    if existing:
        existing.value = body.value
        existing.source = "human"
        await db.commit()
        await db.refresh(existing)
        return {"id": existing.id, "key": existing.key, "value": existing.value, "source": existing.source}
    label = GeoLabel(result_id=result_id, key=body.key, value=body.value, source="human")
    db.add(label)
    await db.commit()
    await db.refresh(label)
    return {"id": label.id, "key": label.key, "value": label.value, "source": label.source}


@router.post("/tasks/{task_id}/run")
async def trigger_annotation(task_id: int, db: AsyncSession = Depends(get_db),
                              user: User = Depends(get_current_user)):
    task = (await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    if not task.label_schema:
        task.label_schema = default_label_schema_json()
        await db.commit()
    from backend.worker.tasks import run_annotation, _run_annotation_async
    status = dispatch_or_run_inline(
        delay_call=lambda: run_annotation.delay(task_id),
        inline_coro_factory=lambda: _run_annotation_async(task_id),
    )
    return {"status": status}
