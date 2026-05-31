from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from bson import ObjectId
from app.core.security import decode_token

security = HTTPBearer()


def get_db(request: Request):
    return request.app.state.db


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
):
    db = get_db(request)
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    user["_id"] = str(user["_id"])
    return user


# Reusable type aliases for route signatures
DBDep = Annotated[object, Depends(get_db)]
CurrentUser = Annotated[dict, Depends(get_current_user)]