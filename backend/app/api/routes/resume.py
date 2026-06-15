from typing import Any, Dict
 
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
 
from app.auth.dependencies import CurrentUser

from app.services.resume.resume import extract_from_resume
 
router = APIRouter(prefix="/resume", tags=["resume"])
 
_MAX_SIZE = 10 * 1024 * 1024  # 10MB
 
 
@router.post("/extract")
async def extract_resume(
    request: Request,
    file:    UploadFile = File(...),
    user:    CurrentUser = None,
) -> Dict[str, Any]:
    """
    Extracts candidate fields from an uploaded PDF resume.
 
    Accepts:  multipart/form-data, field name 'file', PDF only
    Returns:  name, email, github_username, leetcode_username,
              codeforces_username, repo_urls, confidence per field
    Storage:  none — pure extraction, caller fills the form
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported.",
        )
 
    pdf_bytes = await file.read()
 
    if len(pdf_bytes) > _MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 10MB.",
        )
 
    if len(pdf_bytes) < 100:
        raise HTTPException(
            status_code=400,
            detail="File appears empty or corrupt.",
        )
 
    
    result = extract_from_resume(pdf_bytes)
 
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
 
    return {
        "success": True,
        "extracted": {
            "name":                result.get("name"),
            "email":               result.get("email"),
            "github_username":     result.get("github_username"),
            "leetcode_username":   result.get("leetcode_username"),
            "codeforces_username": result.get("codeforces_username"),
            "repo_urls":           result.get("repo_urls", []),
        },
        "confidence":       result.get("confidence", {}),
        "raw_text_length":  result.get("raw_text_length", 0),
    }