from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from backend.database import get_db
from backend.models import CriteriaTemplate, User
from backend.auth import get_current_user

router = APIRouter(prefix="/criteria", tags=["criteria"])

class CriteriaCreate(BaseModel):
    name: str
    criteria_text: str

class CriteriaUpdate(BaseModel):
    name: Optional[str] = None
    criteria_text: Optional[str] = None

def _serialize(c: CriteriaTemplate) -> dict:
    return {"id": c.id, "name": c.name, "criteria_text": c.criteria_text,
            "created_at": c.created_at, "updated_at": c.updated_at}

@router.get("")
async def list_criteria(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(CriteriaTemplate).where(CriteriaTemplate.owner_id == user.id))
    return [_serialize(c) for c in result.scalars().all()]

@router.post("", status_code=201)
async def create_criteria(req: CriteriaCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    c = CriteriaTemplate(name=req.name, criteria_text=req.criteria_text, owner_id=user.id)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _serialize(c)

@router.get("/{criteria_id}")
async def get_criteria(criteria_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(CriteriaTemplate).where(
        CriteriaTemplate.id == criteria_id, CriteriaTemplate.owner_id == user.id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(c)

@router.put("/{criteria_id}")
async def update_criteria(criteria_id: int, req: CriteriaUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(CriteriaTemplate).where(
        CriteriaTemplate.id == criteria_id, CriteriaTemplate.owner_id == user.id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    if req.name is not None:
        c.name = req.name
    if req.criteria_text is not None:
        c.criteria_text = req.criteria_text
    await db.commit()
    await db.refresh(c)
    return _serialize(c)

@router.delete("/{criteria_id}", status_code=204)
async def delete_criteria(criteria_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(CriteriaTemplate).where(
        CriteriaTemplate.id == criteria_id, CriteriaTemplate.owner_id == user.id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(c)
    await db.commit()
