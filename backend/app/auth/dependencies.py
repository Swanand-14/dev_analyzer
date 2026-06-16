from typing import Annotated, Any, Dict
import os
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import get_settings
 
from app.auth.clerk_handler import get_or_provision_user, verify_clerk_token
 
_security = HTTPBearer(auto_error=False)


_MOCK_USER = {
    "_id":                 "000000000000000000000001",
    "clerk_user_id":       "dev_clerk_id",
    "email":               "dev@test.com",
    "leetcode_username":   None,
    "codeforces_username": None,
    "total_analyses":      0,
}

def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_security)],
) -> Dict[str, Any]:
    
    """
    FastAPI dependency — verifies Clerk token and returns the current user.
 
    Usage in a route:
        @router.get("/me")
        def me(user: CurrentUser):
            return user
    """
    if get_settings().DEV_MODE:
        return _MOCK_USER
    
    if not credentials:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    db      = request.app.state.db
    payload = verify_clerk_token(credentials.credentials)
    return get_or_provision_user(db, payload)
 
 

CurrentUser = Annotated[Dict[str, Any], Depends(get_current_user)]