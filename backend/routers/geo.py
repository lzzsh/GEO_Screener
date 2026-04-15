from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from backend.auth import get_current_user
from backend.models import User
from backend.worker.geo_fetcher import search_geo as fetch_geo_candidates

router = APIRouter(prefix="/geo", tags=["geo"])


class GeoSearchRequest(BaseModel):
    q: str = Field(..., min_length=2)
    retmax: int = Field(default=100, ge=1, le=10000)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=200)


async def _search_payload(q: str, retmax: int, page: int, page_size: int):
    results = await fetch_geo_candidates(q, retmax=retmax)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "query": q,
        "retmax": retmax,
        "total": len(results),
        "page": page,
        "page_size": page_size,
        "items": results[start:end],
    }

@router.get("/search")
async def geo_search(
    q: str = Query(..., min_length=2),
    retmax: int = Query(default=100, ge=1, le=10000),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    return await _search_payload(q=q, retmax=retmax, page=page, page_size=page_size)


@router.post("/search")
async def geo_search_post(
    req: GeoSearchRequest,
    user: User = Depends(get_current_user),
):
    return await _search_payload(q=req.q, retmax=req.retmax, page=req.page, page_size=req.page_size)
