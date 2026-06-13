from typing import Any, Dict, Optional
 
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
 
from app.auth.dependencies import CurrentUser
 
router = APIRouter(prefix="/profile", tags=["profile"])

class UpdateProfile(BaseModel):
    leetcode_username:   Optional[str] = None
    codeforces_username: Optional[str] = None


router.put("/update")
def update_profile(
    request:      Request,
    profile_data: UpdateProfile,
    user:         CurrentUser,
) -> Dict[str, Any]:
    """
    Updates the user's platform usernames.
    Only fields provided (non-None) are updated.
    """
    db = request.app.state.db
 
    update_fields = {k: v for k, v in profile_data.dict().items() if v is not None}
    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update",
        )
 
    db.users.update_one(
        {"_id": ObjectId(user["_id"])},
        {"$set": update_fields},
    )
 
    return {
        "success":        True,
        "message":        "Profile updated successfully",
        "updated_fields": list(update_fields.keys()),
    }
 
 
@router.get("/me")
def get_profile(user: CurrentUser) -> Dict[str, Any]:
    """Returns the current user's profile."""
    return {
        "success": True,
        "profile": {
            "id":                  user["_id"],
            "email":               user.get("email"),
            "leetcode_username":   user.get("leetcode_username"),
            "codeforces_username": user.get("codeforces_username"),
            "total_analyses":      user.get("total_analyses", 0),
            "created_at":          user.get("created_at"),
        },
    }

