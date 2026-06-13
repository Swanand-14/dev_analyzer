from typing import Any, Dict
 
from fastapi import APIRouter
 
from app.auth.dependencies import CurrentUser
 
router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/me")
def get_me(user: CurrentUser) -> Dict[str, Any]:
    """
    Returns the current authenticated user.
 
    Clerk token is verified by the CurrentUser dependency.
    If the user doesn't exist in MongoDB yet, they are provisioned automatically.
    """
    return {
        "success": True,
        "user": {
            "id":                  user["_id"],
            "email":               user.get("email"),
            "clerk_user_id":       user.get("clerk_user_id"),
            "leetcode_username":   user.get("leetcode_username"),
            "codeforces_username": user.get("codeforces_username"),
            "total_analyses":      user.get("total_analyses", 0),
            "created_at":          user.get("created_at"),
        },
    }

