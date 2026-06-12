import jwt
import requests
from functools import lru_cache
from datetime import datetime
from typing import Any, Dict, Optional
 
from fastapi import HTTPException, status
 
from app.core.config import get_settings

def _get_jwks() -> Dict:
    """
    Fetches and caches Clerk's public JWKS.
    Cached for the lifetime of the process — Clerk keys rotate rarely.
    """
    settings = get_settings()
    if not settings.CLERK_JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL not configured",
        )
    response = requests.get(settings.CLERK_JWKS_URL, timeout=10)
    response.raise_for_status()
    return response.json()
 
 
def _get_public_key(kid: str):
    """Finds the RSA public key matching the token's key ID."""
    jwks = _get_jwks()
    for key in jwks.get("keys", []):
        if key["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key)
    return None

def verify_clerk_token(token: str) -> Dict[str, Any]:
    """
    Verifies a Clerk-issued RS256 JWT.
 
    Returns the decoded payload on success.
    Raises HTTPException on any failure.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
        )
 
    public_key = _get_public_key(header.get("kid", ""))
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signing key not found",
        )
 
    try:
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
    
def _extract_email(payload: Dict[str, Any]) -> str:
    """
    Extracts email from Clerk JWT payload.
    Clerk puts the email in different fields depending on configuration.
    """
    return (
        payload.get("email")
        or payload.get("email_address")
        or next(iter(payload.get("email_addresses", [])), {}).get("email_address", "")
        or ""
    )

def get_or_provision_user(db, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Finds the user in MongoDB by Clerk user ID.
    If not found, creates a new user document (first login).
 
    Uses upsert with $setOnInsert to avoid race-condition duplicate inserts.
    Returns the full user document.
    """
    clerk_user_id = payload.get("sub")
    if not clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )
 
    email = _extract_email(payload)
 
    db.users.update_one(
        {"clerk_user_id": clerk_user_id},
        {"$setOnInsert": {
            "clerk_user_id":       clerk_user_id,
            "email":               email,
            "created_at":          datetime.utcnow(),
            "total_analyses":      0,
            "leetcode_username":   None,
            "codeforces_username": None,
        }},
        upsert=True,
    )
 
    user = db.users.find_one({"clerk_user_id": clerk_user_id})
    user["_id"] = str(user["_id"])
    return user
