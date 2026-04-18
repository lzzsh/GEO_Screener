import csv
import io
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, func, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
from backend.database import get_db
from backend.label_schema import default_label_schema_json
from backend.models import ScreeningTask, ScreeningResult, User, GeoSample, GeoLabel, GsmLabel, LibraryEntry
from backend.task_dispatch import dispatch_or_run_inline
from backend.auth import get_current_user
from backend.worker.csv_parser import parse_csv
from backend.worker.geo_fetcher import search_geo, fetch_gsm_samples

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
async def create_task(
    name: str,
    source: str,
    criteria_text: str = "",
    file: Optional[UploadFile] = File(default=None),
    search_query: Optional[str] = Query(default=None),
    geo_ids: Optional[str] = Query(default=None),
    label_schema: Optional[str] = Query(default=None),
    retmax: int = Query(default=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if source == "geo" and not search_query and not geo_ids:
        raise HTTPException(status_code=400, detail="search_query is required for GEO tasks")
    if source == "geo" and not label_schema:
        label_schema = default_label_schema_json()

    try:
        task = ScreeningTask(
            name=name,
            source=source,
            search_query=search_query,
            criteria_text=criteria_text,
            owner_id=user.id,
            label_schema=label_schema,
        )
        db.add(task)
        await db.flush()

        datasets: list[dict] = []
        if source == "csv" and file:
            content = await file.read()
            datasets = parse_csv(content)
        elif source == "geo" and search_query:
            datasets = await search_geo(search_query, retmax=retmax)
        elif source == "geo" and geo_ids:
            gid_list = [gid.strip() for gid in geo_ids.split(",") if gid.strip()]
            if gid_list:
                try:
                    datasets = await search_geo(",".join(gid_list), retmax=len(gid_list))
                except Exception:
                    datasets = [{"id": gid, "title": "", "description": ""} for gid in gid_list]

        task.total = len(datasets)
        task.candidate_count = len(datasets)
        for d in datasets:
            sr = ScreeningResult(
                task_id=task.id,
                dataset_id=d["id"],
                title=d.get("title", ""),
                description=d.get("description") or d.get("summary", ""),
                keyword_matched=True,
                gse_type=d.get("gse_type", ""),
                pubdate=d.get("pubdate", ""),
                update_date=d.get("update_date", ""),
                has_raw_data=d.get("has_raw_data", False),
                n_samples=d.get("n_samples", 0),
            )
            db.add(sr)
            await db.flush()

        if source == "geo" and not criteria_text.strip():
            task.status = "done"

        await db.commit()
        await db.refresh(task)
    except OperationalError as exc:
        await db.rollback()
        if "database is locked" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Database is busy. Please retry in a moment.")
        raise

    if source != "geo" or criteria_text.strip():
        from backend.worker.tasks import run_screening, _run_screening_async
        dispatch_or_run_inline(
            delay_call=lambda: run_screening.delay(task.id),
            inline_coro_factory=lambda: _run_screening_async(task.id),
        )

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

    # Collect parent task ids and fetch their names
    parent_ids = {t.parent_task_id for t in tasks if t.parent_task_id}
    parent_names: dict[int, str] = {}
    if parent_ids:
        parent_result = await db.execute(
            select(ScreeningTask.id, ScreeningTask.name).where(ScreeningTask.id.in_(parent_ids))
        )
        parent_names = {row.id: row.name for row in parent_result}

    return [{"id": t.id, "name": t.name, "status": t.status, "total": t.total,
             "candidate_count": t.candidate_count, "processed": t.processed,
             "included_count": t.included_count, "excluded_count": t.excluded_count,
             "uncertain_count": t.uncertain_count, "search_query": t.search_query,
             "created_at": t.created_at, "task_type": t.task_type,
             "parent_task_name": parent_names.get(t.parent_task_id) if t.parent_task_id else None}
            for t in tasks]


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
            "search_query": task.search_query, "created_at": task.created_at,
            "task_type": task.task_type}


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")

    result_ids = (await db.execute(
        select(ScreeningResult.id).where(ScreeningResult.task_id == task_id)
    )).scalars().all()
    try:
        if result_ids:
            await db.execute(delete(GeoLabel).where(GeoLabel.result_id.in_(result_ids)))
            await db.execute(delete(GeoSample).where(GeoSample.result_id.in_(result_ids)))
            await db.execute(delete(ScreeningResult).where(ScreeningResult.id.in_(result_ids)))
        await db.execute(update(LibraryEntry).where(LibraryEntry.task_id == task_id).values(task_id=None))
        await db.delete(task)
        await db.commit()
    except OperationalError as exc:
        await db.rollback()
        if "database is locked" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Database is busy. Please retry in a moment.")
        raise
    return {"status": "deleted"}


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
    rows_result = await db.execute(
        base_query.options(
            selectinload(ScreeningResult.samples),
            selectinload(ScreeningResult.labels),
        ).offset(offset).limit(page_size)
    )
    rows = rows_result.scalars().all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [{"id": r.id, "dataset_id": r.dataset_id, "title": r.title,
                   "description": r.description, "keyword_matched": r.keyword_matched,
                   "decision": r.decision, "confidence": r.confidence,
                   "summary": r.summary, "rule_checks": r.rule_checks,
                   "status": r.status, "error_msg": r.error_msg,
                   "gse_type": r.gse_type, "pubdate": r.pubdate,
                   "update_date": r.update_date, "has_raw_data": r.has_raw_data,
                   "n_samples": r.n_samples,
                   "labels": [{"key": label.key, "value": label.value, "source": label.source} for label in r.labels],
                   "samples": [{"id": s.id, "gsm_id": s.gsm_id, "title": s.title,
                                "organism": s.organism, "biosample_id": s.biosample_id,
                                "cell_count": s.cell_count} for s in r.samples]} for r in rows],
    }


@router.get("/{task_id}/export")
async def export_results(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task_result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    rows_result = await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.task_id == task_id)
        .options(selectinload(ScreeningResult.labels))
    )
    rows = rows_result.scalars().all()
    conclusion_map = {"可用": "true", "不可用": "false", "待确认": "unknown"}
    decision_map = {"include": "true", "exclude": "false", "uncertain": "unknown"}
    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["gse_id", "title", "n_samples", "gse_type", "pubdate", "update_date", "has_raw_data", "available", "reason"])
    for r in rows:
        label_map = {l.key: l.value for l in r.labels}
        if "final_conclusion" in label_map:
            available = conclusion_map.get(label_map["final_conclusion"], "unknown")
            reason = label_map.get("reasoning_text", "")
        else:
            available = decision_map.get(r.decision, "unknown")
            reason = r.summary or ""
        writer.writerow([r.dataset_id, r.title, r.n_samples, r.gse_type, r.pubdate, r.update_date, r.has_raw_data, available, reason])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=task_{task_id}_results.csv"})


@router.post("/{task_id}/results/{result_id}/fetch-samples")
async def fetch_and_store_samples(
    task_id: int, result_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_result = await db.execute(
        select(ScreeningTask).where(ScreeningTask.id == task_id, ScreeningTask.owner_id == user.id)
    )
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Not found")
    sr = (await db.execute(
        select(ScreeningResult)
        .options(selectinload(ScreeningResult.samples))
        .where(ScreeningResult.id == result_id, ScreeningResult.task_id == task_id)
    )).scalar_one_or_none()
    if not sr:
        raise HTTPException(status_code=404, detail="Not found")
    if sr.samples:
        return [{"gsm_id": s.gsm_id, "title": s.title, "organism": s.organism,
                 "biosample_id": s.biosample_id, "cell_count": s.cell_count} for s in sr.samples]
    try:
        gsm_list = await fetch_gsm_samples(sr.dataset_id)
    except httpx.HTTPError:
        gsm_list = []
    for gsm in gsm_list:
        db.add(GeoSample(
            result_id=sr.id,
            gsm_id=gsm["gsm_id"],
            title=gsm.get("title", ""),
            organism=gsm.get("organism", ""),
            biosample_id=gsm.get("biosample_id", ""),
        ))
    await db.commit()
    return [{"gsm_id": g["gsm_id"], "title": g.get("title", ""), "organism": g.get("organism", ""),
             "biosample_id": g.get("biosample_id", ""), "cell_count": None} for g in gsm_list]


@router.post("/{task_id}/create-gsm-task", status_code=201)
async def create_gsm_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parent_task = await db.get(ScreeningTask, task_id)
    if not parent_task:
        raise HTTPException(status_code=404, detail="Parent task not found")
    if parent_task.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    gsm_task = ScreeningTask(
        name=f"{parent_task.name} - GSM Annotation",
        source=parent_task.source,
        task_type="gsm_annotation",
        parent_task_id=parent_task.id,
        criteria_text=parent_task.criteria_text,
        owner_id=user.id,
        label_schema=parent_task.label_schema,
    )
    db.add(gsm_task)
    await db.flush()

    stmt = select(ScreeningResult).where(
        ScreeningResult.task_id == parent_task.id,
        ScreeningResult.decision.in_(["include", "uncertain"]),
    )
    parent_results = (await db.execute(stmt)).scalars().all()

    for pr in parent_results:
        db.add(ScreeningResult(
            task_id=gsm_task.id,
            dataset_id=pr.dataset_id,
            title=pr.title,
            description=pr.description,
            decision=pr.decision,
            gse_type=pr.gse_type,
            pubdate=pr.pubdate,
            update_date=pr.update_date,
            has_raw_data=pr.has_raw_data,
            n_samples=pr.n_samples,
        ))

    gsm_task.total = len(parent_results)
    gsm_task.candidate_count = len(parent_results)
    await db.commit()
    return {"id": gsm_task.id, "name": gsm_task.name}


@router.get("/{task_id}/status")
async def get_task_status(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = await db.get(ScreeningTask, task_id)
    if not task or task.owner_id != user.id:
        raise HTTPException(status_code=404)
    return {"status": task.status, "processed": task.processed, "total": task.total}


@router.post("/{task_id}/run-gsm-annotation")
async def run_gsm_annotation(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import asyncio as _asyncio
    task = await db.get(ScreeningTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from backend.worker.tasks import _run_gsm_task_async

    # If called on a screening task, auto-create the GSM child task first
    if task.task_type == "screening":
        # Check if a GSM task already exists for this parent
        existing = (await db.execute(
            select(ScreeningTask).where(
                ScreeningTask.parent_task_id == task_id,
                ScreeningTask.task_type == "gsm_annotation",
            )
        )).scalar_one_or_none()

        if existing:
            gsm_task = existing
        else:
            gsm_task = ScreeningTask(
                name=f"{task.name} - GSM Annotation",
                source=task.source,
                task_type="gsm_annotation",
                parent_task_id=task.id,
                criteria_text=task.criteria_text,
                owner_id=user.id,
                label_schema=task.label_schema,
            )
            db.add(gsm_task)
            await db.flush()

            stmt = select(ScreeningResult).where(
                ScreeningResult.task_id == task.id,
                ScreeningResult.decision.in_(["include", "uncertain"]),
            )
            parent_results = (await db.execute(stmt)).scalars().all()
            for pr in parent_results:
                db.add(ScreeningResult(
                    task_id=gsm_task.id,
                    dataset_id=pr.dataset_id,
                    title=pr.title,
                    description=pr.description,
                    decision=pr.decision,
                    gse_type=pr.gse_type,
                    pubdate=pr.pubdate,
                    update_date=pr.update_date,
                    has_raw_data=pr.has_raw_data,
                    n_samples=pr.n_samples,
                ))
            gsm_task.total = len(parent_results)
            gsm_task.candidate_count = len(parent_results)
            await db.commit()

        _asyncio.create_task(_run_gsm_task_async(gsm_task.id))
        return {"status": "running_inline", "gsm_task_id": gsm_task.id}

    # Called directly on a gsm_annotation task
    if task.task_type != "gsm_annotation":
        raise HTTPException(status_code=400, detail="Task is not a GSM annotation task")

    _asyncio.create_task(_run_gsm_task_async(task_id))
    return {"status": "running_inline", "gsm_task_id": task_id}


@router.delete("/{task_id}/gsm-labels")
async def clear_gsm_labels(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = await db.get(ScreeningTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if task.task_type != "gsm_annotation":
        raise HTTPException(status_code=400, detail="Task is not a GSM annotation task")

    # Delete all gsm_labels for samples belonging to this task's results
    sample_ids = (await db.execute(
        select(GeoSample.id).join(ScreeningResult, GeoSample.result_id == ScreeningResult.id)
        .where(ScreeningResult.task_id == task_id)
    )).scalars().all()

    if sample_ids:
        await db.execute(delete(GsmLabel).where(GsmLabel.sample_id.in_(sample_ids)))

    task.processed = 0
    task.status = "pending"
    await db.commit()
    return {"deleted": len(sample_ids), "status": "cleared"}
