# app/api/routes/platforms.py
#
# Platform data routes — LeetCode and Codeforces.
# Thin layer over the cache services — no business logic here.

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status

from app.auth.dependencies import CurrentUser
from app.services.leetcode import LeetCodeCache
from app.services.codeforces import CodeforcesCache

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("/leetcode/{username}")
def get_leetcode(
    request:       Request,
    username:      str,
    user:          CurrentUser,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Returns LeetCode profile data for the given username.
    Served from MongoDB cache (1hr TTL) unless force_refresh=true.
    """
    db   = request.app.state.db
    data = LeetCodeCache.get(db, username, force_refresh=force_refresh)

    if data.get("error"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LeetCode user not found: {data['error']}",
        )

    return {"success": True, "data": data}


@router.get("/codeforces/{username}")
def get_codeforces(
    request:       Request,
    username:      str,
    user:          CurrentUser,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Returns Codeforces profile data for the given username.
    Served from MongoDB cache (1hr TTL) unless force_refresh=true.
    """
    db   = request.app.state.db
    data = CodeforcesCache.get(db, username, force_refresh=force_refresh)

    if data.get("error"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Codeforces user not found: {data['error']}",
        )

    return {"success": True, "data": data}