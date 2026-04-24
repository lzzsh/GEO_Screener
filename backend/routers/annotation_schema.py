from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import json
from backend.database import get_db
from backend.models import AnnotationSchema, User
from backend.auth import get_current_user

router = APIRouter(prefix="/annotation-schemas", tags=["annotation-schemas"])

class LabelDefCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str
    allowed_values: Optional[list[str]] = None

class AnnotationSchemaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    gse_labels: list[LabelDefCreate]
    gsm_labels: list[LabelDefCreate]

class AnnotationSchemaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    gse_labels: Optional[list[LabelDefCreate]] = None
    gsm_labels: Optional[list[LabelDefCreate]] = None

def _serialize(schema: AnnotationSchema) -> dict:
    return {
        "id": schema.id,
        "name": schema.name,
        "description": schema.description,
        "gse_labels": json.loads(schema.gse_labels),
        "gsm_labels": json.loads(schema.gsm_labels),
        "created_at": schema.created_at,
        "updated_at": schema.updated_at,
    }

@router.get("")
async def list_schemas(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(AnnotationSchema).where(AnnotationSchema.owner_id == user.id))
    return [_serialize(s) for s in result.scalars().all()]

@router.post("", status_code=201)
async def create_schema(req: AnnotationSchemaCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    schema = AnnotationSchema(
        name=req.name,
        description=req.description,
        owner_id=user.id,
        gse_labels=json.dumps([label.dict() for label in req.gse_labels], ensure_ascii=False),
        gsm_labels=json.dumps([label.dict() for label in req.gsm_labels], ensure_ascii=False),
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)
    return _serialize(schema)

@router.get("/{schema_id}")
async def get_schema(schema_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(AnnotationSchema).where(
        AnnotationSchema.id == schema_id, AnnotationSchema.owner_id == user.id))
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(schema)

@router.put("/{schema_id}")
async def update_schema(schema_id: int, req: AnnotationSchemaUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(AnnotationSchema).where(
        AnnotationSchema.id == schema_id, AnnotationSchema.owner_id == user.id))
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Not found")
    if req.name is not None:
        schema.name = req.name
    if req.description is not None:
        schema.description = req.description
    if req.gse_labels is not None:
        schema.gse_labels = json.dumps([label.dict() for label in req.gse_labels], ensure_ascii=False)
    if req.gsm_labels is not None:
        schema.gsm_labels = json.dumps([label.dict() for label in req.gsm_labels], ensure_ascii=False)
    await db.commit()
    await db.refresh(schema)
    return _serialize(schema)

@router.delete("/{schema_id}", status_code=204)
async def delete_schema(schema_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(AnnotationSchema).where(
        AnnotationSchema.id == schema_id, AnnotationSchema.owner_id == user.id))
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(schema)
    await db.commit()
