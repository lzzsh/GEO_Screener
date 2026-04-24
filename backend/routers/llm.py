from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from backend.database import get_db
from backend.models import LLMConfig, User
from backend.auth import get_current_user
from backend.worker.llm_client import PROVIDER_DEFAULTS

router = APIRouter(prefix="/llm", tags=["llm"])

class LLMConfigUpdate(BaseModel):
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None

def _effective_base_url(provider: str, stored: Optional[str]) -> str:
    """Return the URL that will actually be used (stored override or PROVIDER_DEFAULTS fallback)."""
    if stored and stored.strip():
        return stored.strip()
    return PROVIDER_DEFAULTS.get(provider, {}).get("base_url", "")

async def _get_active_config(user: User, db: AsyncSession) -> Optional[LLMConfig]:
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.owner_id == user.id, LLMConfig.is_active == True)
    )
    return result.scalar_one_or_none()

async def _get_provider_config(user: User, provider: str, db: AsyncSession) -> Optional[LLMConfig]:
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.owner_id == user.id, LLMConfig.provider == provider)
    )
    return result.scalar_one_or_none()

def _row_to_dict(r: LLMConfig) -> dict:
    return {
        "model": r.model,
        "base_url": r.base_url,
        "effective_base_url": _effective_base_url(r.provider, r.base_url),
        "temperature": r.temperature,
        "has_key": bool(r.api_key),
    }

def _serialize(c: LLMConfig, saved_providers: list[str], provider_configs: dict) -> dict:
    return {
        "provider": c.provider,
        "base_url": c.base_url,
        "effective_base_url": _effective_base_url(c.provider, c.base_url),
        "api_key": "***" if c.api_key else None,
        "model": c.model,
        "temperature": c.temperature,
        "saved_providers": saved_providers,
        "provider_configs": provider_configs,
    }

def _build_provider_configs(rows: list[LLMConfig]) -> dict:
    return {r.provider: _row_to_dict(r) for r in rows}

@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = await _get_active_config(user, db)
    all_rows = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == user.id))).scalars().all()
    saved_providers = [r.provider for r in all_rows if r.api_key]
    provider_configs = _build_provider_configs(all_rows)
    if not cfg:
        return {"provider": "deepseek", "base_url": None,
                "effective_base_url": _effective_base_url("deepseek", None),
                "api_key": None, "model": "deepseek-chat", "temperature": 0.1,
                "saved_providers": saved_providers, "provider_configs": provider_configs}
    return _serialize(cfg, saved_providers, provider_configs)

class LLMCredentialsUpdate(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None

@router.put("/credentials")
async def update_credentials(req: LLMCredentialsUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Save key/model for a provider without changing the active provider."""
    provider = req.provider.strip()
    cfg = await _get_provider_config(user, provider, db)
    if not cfg:
        cfg = LLMConfig(owner_id=user.id, provider=provider, is_active=False)
        db.add(cfg)

    if provider == "custom" and req.base_url is not None:
        cfg.base_url = req.base_url.strip() or None
    else:
        cfg.base_url = None

    if req.model is not None:
        cfg.model = req.model.strip()
    if req.temperature is not None:
        cfg.temperature = req.temperature
    if req.api_key and req.api_key.strip():
        cfg.api_key = req.api_key.strip()

    await db.commit()
    await db.refresh(cfg)

    all_rows = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == user.id))).scalars().all()
    return {"provider_configs": _build_provider_configs(all_rows)}

@router.put("/config")
async def update_config(req: LLMConfigUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    provider = req.provider.strip()
    await db.execute(update(LLMConfig).where(LLMConfig.owner_id == user.id).values(is_active=False))

    cfg = await _get_provider_config(user, provider, db)
    if not cfg:
        cfg = LLMConfig(owner_id=user.id, provider=provider, is_active=True)
        db.add(cfg)
    else:
        cfg.is_active = True

    # Only store base_url override for custom provider; clear it for known providers
    if provider == "custom":
        if req.base_url is not None:
            cfg.base_url = req.base_url.strip() or None
    else:
        cfg.base_url = None  # always use PROVIDER_DEFAULTS for known providers

    if req.model is not None:
        cfg.model = req.model.strip()
    if req.temperature is not None:
        cfg.temperature = req.temperature
    if req.api_key and req.api_key.strip():
        cfg.api_key = req.api_key.strip()

    await db.commit()
    await db.refresh(cfg)

    all_rows = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == user.id))).scalars().all()
    saved_providers = [r.provider for r in all_rows if r.api_key]
    return _serialize(cfg, saved_providers, _build_provider_configs(all_rows))

@router.post("/test")
async def test_connection(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = await _get_active_config(user, db)
    if not cfg or not cfg.api_key:
        raise HTTPException(status_code=400, detail="API key not configured")
    from backend.worker.llm_client import LLMClient
    client = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                       base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature)
    try:
        ok = await client.test_connection()
        return {"success": ok}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
