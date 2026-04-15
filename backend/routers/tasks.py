import csv
import io
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from backend.database import get_db
from backend.models import ScreeningTask, ScreeningResult, User
from backend.auth import get_current_user
from backend.worker.csv_parser import parse_csv
from backend.worker.geo_fetcher import search_geo

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
async def create_task(
    name: str,
    source: str,
    criteria_text: str = "",
    file: Optional[UploadFile] = File(default=None),
    search_query: Optional[str] = Query(default=None),
    geo_ids: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if source == "geo" and not search_query and not geo_ids:
        raise HTTPException(status_code=400, detail="search_query is required for GEO tasks")

    task = ScreeningTask(
        name=name,
        source=source,
        search_query=search_query,
        criteria_text=criteria_text,
        owner_id=user.id,
    )
    db.add(task)
    await db.flush()

    datasets: list[dict] = []
    if source == "csv" and file:
        content = await file.read()
        datasets = parse_csv(content)
    elif source == "geo" and search_query:
        datasets = await search_geo(search_query, retmax=20)
    elif source == "geo" and geo_ids:
        for gid in geo_ids.split(","):
            gid = gid.strip()
            if gid:
                datasets.append({"id": gid, "title": "", "description": ""})

    task.total = len(datasets)
    task.candidate_count = len(datasets)
    for d in datasets:
        sr = ScreeningResult(
            task_id=task.id,
            dataset_id=d["id"],
            title=d.get("title", ""),
            description=d.get("description") or d.get("summary", ""),
            keyword_matched=True,
        )
        db.add(sr)

    if source == "geo" and not criteria_text.strip():
        task.status = "done"

    await db.commit()
    await db.refresh(task)

    if source != "geo" or criteria_text.strip():
        from backend.worker.tasks import run_screening
        run_screening.delay(task.id)

    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "total": task.total,
        "candidate_count": task.candidate_count,
    }


@router.get("")
async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.owner_id == user.id).order_by(ScreeningTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [{"id": t.id, "name": t.name, "status": t.status, "total": t.total,
             "candidate_count": t.candidate_count, "processed": t.processed,
             "included_count": t.included_count, "excluded_count": t.excluded_count,
             "uncertain_count": t.uncertain_count, "search_query": t.search_query,
             "created_at": t.created_at} for t in tasks]


@router.get("/{task_id}")
async def get_task(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": task.id, "name": task.name, "status": task.status,
            "total": task.total, "candidate_count": task.candidate_count,
            "processed": task.processed, "included_count": task.included_count,
            "excluded_count": task.excluded_count, "uncertain_count": task.uncertain_count,
            "search_query": task.search_query, "created_at": task.created_at}


@router.get("/{task_id}/results")
async def get_results(
    task_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    decision: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Not found")
    offset = (page - 1) * page_size
    base_query = select(ScreeningResult).where(ScreeningResult.task_id == task_id)
    count_query = select(func.count()).select_from(ScreeningResult).where(ScreeningResult.task_id == task_id)
    if decision:
        base_query = base_query.where(ScreeningResult.decision == decision)
        count_query = count_query.where(ScreeningResult.decision == decision)
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    rows_result = await db.execute(base_query.offset(offset).limit(page_size))
    rows = rows_result.scalars().all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [{"id": r.id, "dataset_id": r.dataset_id, "title": r.title,
                   "description": r.description, "keyword_matched": r.keyword_matched,
                   "decision": r.decision, "confidence": r.confidence,
                   "summary": r.summary, "rule_checks": r.rule_checks,
                   "status": r.status, "error_msg": r.error_msg} for r in rows],
    }


@router.get("/{task_id}/export")
async def export_results(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task_result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    rows_result = await db.execute(select(ScreeningResult).where(ScreeningResult.task_id == task_id))
    rows = rows_result.scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["dataset_id", "title", "description", "keyword_matched", "decision", "confidence", "summary", "rule_checks", "status"])
    for r in rows:
        writer.writerow([r.dataset_id, r.title, r.description, r.keyword_matched, r.decision, r.confidence, r.summary, r.rule_checks, r.status])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=task_{task_id}_results.csv"})
