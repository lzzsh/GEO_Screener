import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from backend.auth import get_current_user
from backend.models import User
from backend.worker.geo_fetcher import search_geo_page, fetch_gsm_samples, fetch_gse_detail, fetch_gsm_detail

router = APIRouter(prefix="/geo", tags=["geo"])


class GeoSearchRequest(BaseModel):
    q: str = Field(..., min_length=2)
    retmax: int = Field(default=100, ge=1, le=10000)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=10000)


async def _search_payload(q: str, retmax: int, page: int, page_size: int):
    try:
        return await search_geo_page(q, retmax=retmax, page=page, page_size=page_size)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 429:
            raise HTTPException(status_code=503, detail="NCBI rate limit reached. Please retry in a moment.")
        raise HTTPException(status_code=502, detail="GEO upstream request failed.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Unable to reach GEO right now.")

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


def _geo_http_errors(exc_503_detail="NCBI rate limit reached. Please retry in a moment."):
    def handler(exc):
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 429:
                raise HTTPException(status_code=503, detail=exc_503_detail)
            raise HTTPException(status_code=502, detail="GEO upstream request failed.")
        raise HTTPException(status_code=502, detail="Unable to reach GEO right now.")
    return handler


@router.get("/gse/{gse_id}/samples")
async def get_gse_samples(gse_id: str, user: User = Depends(get_current_user)):
    try:
        samples = await fetch_gsm_samples(gse_id)
        return {"gse_id": gse_id, "samples": samples}
    except (httpx.HTTPStatusError, httpx.HTTPError) as exc:
        _geo_http_errors()(exc)


@router.get("/gse/{gse_id}/detail")
async def get_gse_detail(gse_id: str, user: User = Depends(get_current_user)):
    try:
        return await fetch_gse_detail(gse_id)
    except (httpx.HTTPStatusError, httpx.HTTPError) as exc:
        _geo_http_errors()(exc)


@router.get("/gsm/{gsm_id}/detail")
async def get_gsm_detail(gsm_id: str, user: User = Depends(get_current_user)):
    try:
        return await fetch_gsm_detail(gsm_id)
    except (httpx.HTTPStatusError, httpx.HTTPError) as exc:
        _geo_http_errors()(exc)
