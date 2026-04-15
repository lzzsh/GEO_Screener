import csv
import io
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.database import get_db
from backend.models import Library, LibraryEntry, LibraryEntryLabel, LibraryEntrySample, User
from backend.auth import get_current_user

router = APIRouter(prefix="/library", tags=["library"])


class LibraryCreate(BaseModel):
    name: str
    description: str | None = None
    search_query: str | None = None


class EntryItem(BaseModel):
    gse_id: str
    title: str | None = None
    organism: str | None = None
    n_samples: int = 0
    gse_type: str | None = None
    has_raw_data: bool = False
    summary: str | None = None
    pubdate: str | None = None
    update_date: str | None = None


class EntriesSave(BaseModel):
    entries: list[EntryItem]
    source: str = "search"
    task_id: int | None = None


class EntryUpdate(BaseModel):
    status: str | None = None


class LabelUpsert(BaseModel):
    key: str
    value: str | None = None


@router.post("", status_code=201)
async def create_library(body: LibraryCreate, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    lib = Library(name=body.name, description=body.description,
                  search_query=body.search_query, owner_id=user.id)
    db.add(lib)
    await db.commit()
    await db.refresh(lib)
    return {"id": lib.id, "name": lib.name, "description": lib.description,
            "search_query": lib.search_query, "created_at": lib.created_at}


@router.get("")
async def list_libraries(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(Library).where(Library.owner_id == user.id).order_by(Library.created_at.desc())
    )).scalars().all()
    return [{"id": l.id, "name": l.name, "description": l.description,
             "search_query": l.search_query, "created_at": l.created_at} for l in rows]


@router.delete("/{library_id}", status_code=204)
async def delete_library(library_id: int, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    lib = (await db.execute(
        select(Library).where(Library.id == library_id, Library.owner_id == user.id)
    )).scalar_one_or_none()
    if not lib:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(lib)
    await db.commit()


@router.post("/{library_id}/entries", status_code=201)
async def save_entries(library_id: int, body: EntriesSave,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    lib = (await db.execute(
        select(Library).where(Library.id == library_id, Library.owner_id == user.id)
    )).scalar_one_or_none()
    if not lib:
        raise HTTPException(status_code=404, detail="Not found")
    existing = set((await db.execute(
        select(LibraryEntry.gse_id).where(LibraryEntry.library_id == library_id)
    )).scalars().all())
    added = 0
    for e in body.entries:
        if e.gse_id in existing:
            continue
        db.add(LibraryEntry(
            library_id=library_id, gse_id=e.gse_id, title=e.title,
            organism=e.organism, n_samples=e.n_samples, gse_type=e.gse_type,
            has_raw_data=e.has_raw_data, summary=e.summary,
            pubdate=e.pubdate, update_date=e.update_date,
            source=body.source, task_id=body.task_id, status="new",
        ))
        added += 1
    await db.commit()
    return {"added": added, "skipped": len(body.entries) - added}


@router.get("/{library_id}/entries")
async def list_entries(
    library_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lib = (await db.execute(
        select(Library).where(Library.id == library_id, Library.owner_id == user.id)
    )).scalar_one_or_none()
    if not lib:
        raise HTTPException(status_code=404, detail="Not found")
    q = select(LibraryEntry).where(LibraryEntry.library_id == library_id)
    if status:
        q = q.where(LibraryEntry.status == status)
    total = len((await db.execute(q)).scalars().all())
    rows = (await db.execute(
        q.options(selectinload(LibraryEntry.labels), selectinload(LibraryEntry.samples))
         .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [{
            "id": r.id, "gse_id": r.gse_id, "title": r.title,
            "organism": r.organism, "n_samples": r.n_samples,
            "gse_type": r.gse_type, "has_raw_data": r.has_raw_data,
            "summary": r.summary, "pubdate": r.pubdate, "update_date": r.update_date,
            "status": r.status, "source": r.source, "task_id": r.task_id,
            "labels": [{"id": l.id, "key": l.key, "value": l.value, "source": l.source} for l in r.labels],
            "samples": [{"gsm_id": s.gsm_id, "title": s.title, "organism": s.organism,
                         "biosample_id": s.biosample_id, "cell_count": s.cell_count} for s in r.samples],
        } for r in rows],
    }


@router.patch("/{library_id}/entries/{entry_id}")
async def update_entry(library_id: int, entry_id: int, body: EntryUpdate,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    entry = (await db.execute(
        select(LibraryEntry).join(Library).where(
            LibraryEntry.id == entry_id,
            LibraryEntry.library_id == library_id,
            Library.owner_id == user.id,
        )
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    if body.status is not None:
        entry.status = body.status
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "gse_id": entry.gse_id, "status": entry.status}


@router.get("/entries/{entry_id}/labels")
async def get_entry_labels(entry_id: int, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(LibraryEntryLabel).where(LibraryEntryLabel.entry_id == entry_id)
    )).scalars().all()
    return [{"id": r.id, "key": r.key, "value": r.value, "source": r.source} for r in rows]


@router.put("/entries/{entry_id}/labels")
async def upsert_label(entry_id: int, body: LabelUpsert,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    existing = (await db.execute(
        select(LibraryEntryLabel).where(
            LibraryEntryLabel.entry_id == entry_id,
            LibraryEntryLabel.key == body.key,
        )
    )).scalar_one_or_none()
    if existing:
        existing.value = body.value
        existing.source = "human"
        await db.commit()
        await db.refresh(existing)
        return {"id": existing.id, "key": existing.key, "value": existing.value, "source": existing.source}
    label = LibraryEntryLabel(entry_id=entry_id, key=body.key, value=body.value, source="human")
    db.add(label)
    await db.commit()
    await db.refresh(label)
    return {"id": label.id, "key": label.key, "value": label.value, "source": label.source}


@router.get("/{library_id}/export")
async def export_library(library_id: int, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    lib = (await db.execute(
        select(Library).where(Library.id == library_id, Library.owner_id == user.id)
    )).scalar_one_or_none()
    if not lib:
        raise HTTPException(status_code=404, detail="Not found")
    rows = (await db.execute(
        select(LibraryEntry).where(LibraryEntry.library_id == library_id)
        .options(selectinload(LibraryEntry.labels))
    )).scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    all_keys: list[str] = []
    for r in rows:
        for l in r.labels:
            if l.key not in all_keys:
                all_keys.append(l.key)
    writer.writerow(["gse_id", "title", "organism", "n_samples", "gse_type",
                     "has_raw_data", "pubdate", "status", "source"] + all_keys)
    for r in rows:
        label_map = {l.key: l.value for l in r.labels}
        writer.writerow([r.gse_id, r.title, r.organism, r.n_samples, r.gse_type,
                         r.has_raw_data, r.pubdate, r.status, r.source]
                        + [label_map.get(k, "") for k in all_keys])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=library_{library_id}.csv"})
