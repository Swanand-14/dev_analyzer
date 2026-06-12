from typing import Annotated, Any, Dict
 
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
 
from app.auth.clerk_handler import get_or_provision_user, verify_clerk_token
 
_security = HTTPBearer()

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
    db      = request.app.state.db
    payload = verify_clerk_token(credentials.credentials)
    return get_or_provision_user(db, payload)
 
 

CurrentUser = Annotated[Dict[str, Any], Depends(get_current_user)]