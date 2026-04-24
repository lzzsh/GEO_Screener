import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from backend.database import get_db
from backend.models import AnnotationSchema, User
from backend.auth import get_current_user

router = APIRouter(tags=["prompts"])

class PromptContent(BaseModel):
    content: str

def _get_prompts_dir() -> Path:
    """Get the prompts directory path."""
    # Get the backend directory
    backend_dir = Path(__file__).parent.parent
    return backend_dir / "prompts"

def _get_prompt_path(schema_name: str, prompt_type: str) -> Path:
    """Get the full path to a prompt file."""
    prompts_dir = _get_prompts_dir()
    return prompts_dir / schema_name / f"{prompt_type}.txt"

@router.get("/prompts/default/{prompt_type}")
async def get_default_prompt(prompt_type: str):
    """Get default prompt file (public endpoint)."""
    prompt_path = _get_prompt_path("default", prompt_type)

    if not prompt_path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt file not found at {prompt_path}")

    with open(prompt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return {"content": content}

@router.get("/annotation-schemas/{schema_id}/prompts/{prompt_type}")
async def get_prompt(schema_id: int, prompt_type: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Get prompt content for a schema."""
    result = await db.execute(select(AnnotationSchema).where(
        AnnotationSchema.id == schema_id, AnnotationSchema.owner_id == user.id))
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    prompt_path = _get_prompt_path(schema.name, prompt_type)

    if not prompt_path.exists():
        raise HTTPException(status_code=404, detail="Prompt file not found")

    with open(prompt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return {"content": content}

@router.put("/annotation-schemas/{schema_id}/prompts/{prompt_type}")
async def update_prompt(schema_id: int, prompt_type: str, req: PromptContent, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update prompt content for a schema."""
    result = await db.execute(select(AnnotationSchema).where(
        AnnotationSchema.id == schema_id, AnnotationSchema.owner_id == user.id))
    schema = result.scalar_one_or_none()
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    prompt_path = _get_prompt_path(schema.name, prompt_type)

    # Ensure directory exists
    prompt_path.parent.mkdir(parents=True, exist_ok=True)

    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(req.content)

    return {"message": "Prompt updated successfully"}


