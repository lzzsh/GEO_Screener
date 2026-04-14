from fastapi import APIRouter, Depends, Query
from backend.auth import get_current_user
from backend.models import User
from backend.worker.geo_fetcher import search_geo

router = APIRouter(prefix="/geo", tags=["geo"])

@router.get("/search")
async def geo_search(q: str = Query(..., min_length=2), user: User = Depends(get_current_user)):
    results = await search_geo(q, retmax=20)
    return results
