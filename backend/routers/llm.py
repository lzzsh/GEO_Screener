from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from backend.database import get_db
from backend.models import LLMConfig, User
from backend.auth import get_current_user

router = APIRouter(prefix="/llm", tags=["llm"])

class LLMConfigUpdate(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None

def _serialize(c: LLMConfig) -> dict:
    return {"provider": c.provider, "base_url": c.base_url,
            "api_key": "***" if c.api_key else None,
            "model": c.model, "temperature": c.temperature}

async def _get_or_create_config(user: User, db: AsyncSession) -> LLMConfig:
    result = await db.execute(select(LLMConfig).where(LLMConfig.owner_id == user.id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = LLMConfig(owner_id=user.id)
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg

@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = await _get_or_create_config(user, db)
    return _serialize(cfg)

@router.put("/config")
async def update_config(req: LLMConfigUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = await _get_or_create_config(user, db)
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(cfg, field, value)
    await db.commit()
    await db.refresh(cfg)
    return _serialize(cfg)

@router.post("/test")
async def test_connection(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = await _get_or_create_config(user, db)
    if not cfg.api_key:
        raise HTTPException(status_code=400, detail="API key not configured")
    from backend.worker.llm_client import LLMClient
    client = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                       base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature)
    try:
        ok = await client.test_connection()
        return {"success": ok}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
