from typing import Optional
import os
import shutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import json
from backend.database import get_db
from backend.models import AnnotationSchema, User
from backend.auth import get_current_user
from backend.label_schema import DEFAULT_GSE_LABELS, DEFAULT_GSM_LABELS

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

def _serialize(schema: AnnotationSchema, active_id: int | None = None) -> dict:
    return {
        "id": schema.id,
        "name": schema.name,
        "description": schema.description,
        "gse_labels": json.loads(schema.gse_labels),
        "gsm_labels": json.loads(schema.gsm_labels),
        "created_at": schema.created_at,
        "updated_at": schema.updated_at,
        "is_active": schema.id == active_id,
    }

def _get_prompts_dir() -> str:
    """Get the prompts directory path."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")

def _create_schema_prompt_files(schema_name: str):
    """Create prompt directory for a new schema (without copying defaults)."""
    prompts_dir = _get_prompts_dir()
    schema_dir = os.path.join(prompts_dir, schema_name)
    os.makedirs(schema_dir, exist_ok=True)

def _delete_schema_prompt_files(schema_name: str):
    """Delete prompt files for a schema."""
    prompts_dir = _get_prompts_dir()
    schema_dir = os.path.join(prompts_dir, schema_name)
    if os.path.exists(schema_dir) and schema_name != "default":
        shutil.rmtree(schema_dir)

@router.get("/default-template")
async def get_default_template():
    return {
        "name": "Default",
        "description": "Default annotation schema for PSC differentiation studies",
        "gse_labels": DEFAULT_GSE_LABELS,
        "gsm_labels": DEFAULT_GSM_LABELS,
    }

@router.get("")
async def list_schemas(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(AnnotationSchema).where(AnnotationSchema.owner_id == user.id))
    return [_serialize(s, user.active_annotation_schema_id) for s in result.scalars().all()]

@router.post("/{schema_id}/set-active")
async def set_active_schema(schema_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    schema = (await db.execute(select(AnnotationSchema).where(
        AnnotationSchema.id == schema_id, AnnotationSchema.owner_id == user.id
    ))).scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Not found")
    user.active_annotation_schema_id = schema_id
    await db.commit()
    return {"active_schema_id": schema_id}

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

    # Create prompt files for this schema
    _create_schema_prompt_files(schema.name)

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

    if user.active_annotation_schema_id == schema_id:
        user.active_annotation_schema_id = None
        await db.flush()

    # Delete prompt files for this schema
    _delete_schema_prompt_files(schema.name)

    await db.delete(schema)
    await db.commit()

