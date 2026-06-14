import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
 
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, Field, validator
from pymongo import DESCENDING
 
from app.auth.dependencies import CurrentUser
 
router = APIRouter(prefix="/analysis", tags=["analysis"])

class AnalyzeRequest(BaseModel):
    repo_urls:           List[str] = Field(..., min_items=1, max_items=3)
    leetcode_username:   Optional[str] = None
    codeforces_username: Optional[str] = None
    candidate_name:      Optional[str] = None
    force_refresh:       bool = Field(default=False)
    @validator("repo_urls")
    def validate_repos(cls, v):
        cleaned = []
        for url in v:
            url = url.strip()
            if not url:
                continue
            if "github.com" in url:
                parts = url.rstrip("/").split("/")
                if len(parts) >= 2:
                    cleaned.append(f"{parts[-2]}/{parts[-1]}")
            else:
                cleaned.append(url)
        if not cleaned:
            raise ValueError("At least one valid repository URL is required")
        if len(cleaned) > 3:
            raise ValueError("Maximum 3 repositories allowed")
        return cleaned
    
def _run_analysis(
    analysis_id:         str,
    repo_urls:           List[str],
    user_id:             str,
    leetcode_username:   Optional[str],
    codeforces_username: Optional[str],
    candidate_name:      Optional[str],
    force_refresh:       bool,
    app_state,
):
    """
    Background task — orchestrates the full analysis pipeline:
      Stage-1 per repo → merge → LeetCode cache → Codeforces cache → LLM-2 dashboard
    """
    from app.analysis.stage1 import RepoAnalysisPipeline
    from app.analysis.stage2 import merge_repo_analyses, generate_recruiter_dashboard
    from app.services.github.rate_limiter import AdaptiveRateLimiter
    from app.services.leetcode import LeetCodeCache
    from app.services.codeforces import CodeforcesCache
    from app.db.mongo import MongoDBSanitizer
 
    db             = app_state.db
    github_client  = app_state.github
    gemini_model   = app_state.gemini_flash_lite
    rate_limiter   = AdaptiveRateLimiter()
 
    try:
        db.repositories.update_one(
            {"analysis_id": analysis_id},
            {"$set": {"status": "processing", "started_at": datetime.utcnow().replace(microsecond=0)}},
        )
 
        # Stage-1 per repo
        print(f"\n🔄 Analyzing {len(repo_urls)} repositories...")
        repo_analyses = []
        for i, repo_url in enumerate(repo_urls, 1):
            print(f"  [{i}/{len(repo_urls)}] {repo_url}...")
            try:
                pipeline = RepoAnalysisPipeline(gemini_model, rate_limiter, github_client)
                repo_analyses.append(pipeline.analyze_complete(repo_url))
            except Exception as e:
                print(f"  ❌ Failed {repo_url}: {e}")
                repo_analyses.append({"repo_url": repo_url, "error": str(e), "status": "failed"})
 
        #  Merge 
        merged = merge_repo_analyses(repo_analyses)
 
        #  LeetCode 
        leetcode_data = None
        if leetcode_username:
            print(f"\n🟡 Fetching LeetCode: {leetcode_username}...")
            leetcode_data = LeetCodeCache.get(db, leetcode_username, force_refresh=force_refresh)
 
        # Codeforces 
        codeforces_data = None
        if codeforces_username:
            print(f"\n🔵 Fetching Codeforces: {codeforces_username}...")
            codeforces_data = CodeforcesCache.get(db, codeforces_username, force_refresh=force_refresh)
 
        #  LLM-2 recruiter dashboard 
        dashboard_result = generate_recruiter_dashboard(merged)
 
        if dashboard_result["status"] == "success":
            dashboard_doc = {
                "status":            "success",
                "dashboard":         dashboard_result["dashboard"],
                "generation_time_s": dashboard_result.get("generation_time_s"),
                "generated_at":      datetime.utcnow().replace(microsecond=0),
            }
        else:
            dashboard_doc = {
                "status":            "generation_failed",
                "error":             dashboard_result.get("error"),
                "validation_errors": dashboard_result.get("validation_errors", []),
                "raw_output":        dashboard_result.get("raw_output", "")[:2000],
                "generation_time_s": dashboard_result.get("generation_time_s"),
                "generated_at":      datetime.utcnow().replace(microsecond=0),
            }
 
        #  Store 
        def _strip_signals(repo: Dict) -> Dict:
            return {k: v for k, v in repo.items() if k != "signals_by_capability"}
 
        update_data = {
            "status":               "completed",
            "completed_at":         datetime.utcnow().replace(microsecond=0),
            "candidate_name":       candidate_name,
            "candidate_leetcode":   leetcode_username,
            "candidate_codeforces": codeforces_username,
            "repo_analyses":        [_strip_signals(r) for r in repo_analyses if not r.get("error")],
            "merged_repo_analysis": merged,
            "leetcode_data":        leetcode_data,
            "codeforces_data":      codeforces_data,
            "recruiter_dashboard":  dashboard_doc,
        }
 
        sanitized = MongoDBSanitizer.sanitize(update_data)
        db.repositories.update_one({"analysis_id": analysis_id}, {"$set": sanitized})
        db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"total_analyses": 1}})
 
        print(f"\n✅ Analysis complete! Dashboard: {dashboard_doc['status']}")
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.repositories.update_one(
            {"analysis_id": analysis_id},
            {"$set": {
                "status":    "failed",
                "error":     str(e),
                "failed_at": datetime.utcnow().replace(microsecond=0),
            }},
        )

@router.post("")
def start_analysis(
    request:          Request,
    body:             AnalyzeRequest,
    background_tasks: BackgroundTasks,
    user:             CurrentUser,
) -> Dict[str, Any]:
    """Triggers a new analysis. Returns immediately with analysis_id."""
    db          = request.app.state.db
    analysis_id = str(uuid.uuid4())[:8]
 
    db.repositories.insert_one({
        "analysis_id":        analysis_id,
        "repo_urls":          body.repo_urls,
        "user_id":            user["_id"],
        "user_email":         user.get("email"),
        "leetcode_username":  body.leetcode_username or user.get("leetcode_username"),
        "codeforces_username":body.codeforces_username or user.get("codeforces_username"),
        "force_refresh":      body.force_refresh,
        "status":             "pending",
        "created_at":         datetime.utcnow(),
    })
 
    background_tasks.add_task(
        _run_analysis,
        analysis_id,
        body.repo_urls,
        user["_id"],
        body.leetcode_username or user.get("leetcode_username"),
        body.codeforces_username or user.get("codeforces_username"),
        body.candidate_name,
        body.force_refresh,
        request.app.state,
    )
 
    return {
        "success":        True,
        "analysis_id":    analysis_id,
        "status":         "pending",
        "estimated_time": 60 + (len(body.repo_urls) * 30),
    }
@router.get("/list")
def list_analyses(
    request: Request,
    user:    CurrentUser,
    skip:    int = 0,
    limit:   int = 20,
) -> Dict[str, Any]:
    """Returns a paginated list of analyses for the current user."""
    db = request.app.state.db
    cursor = db.repositories.find(
        {"user_id": user["_id"]},
        {
            "_id": 0, "user_id": 0,
            "repo_analyses": 0,
            "merged_repo_analysis": 0,
            "leetcode_data": 0,
            "codeforces_data": 0,
        }
    ).sort("created_at", DESCENDING).skip(skip).limit(limit)
    analyses = []
    for doc in cursor:
        rd = doc.pop("recruiter_dashboard", None)
        doc["dashboard_status"] = rd.get("status") if rd else "not_generated"
        analyses.append(doc)
 
    total = db.repositories.count_documents({"user_id": user["_id"]})
    return {"success": True, "total": total, "skip": skip, "limit": limit, "analyses": analyses}

@router.get("/{analysis_id}")
def get_analysis(
    request:           Request,
    analysis_id:       str,
    user:              CurrentUser,
    include_dashboard: bool = True,
) -> Dict[str, Any]:
    """
    Returns the full analysis result.
    Pass ?include_dashboard=false to skip the dashboard payload.
    """
    db = request.app.state.db
 
    projection = {"_id": 0, "user_id": 0, "merged_repo_analysis": 0}
    if not include_dashboard:
        projection["recruiter_dashboard"] = 0
 
    analysis = db.repositories.find_one(
        {"analysis_id": analysis_id, "user_id": user["_id"]},
        projection,
    )
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
 
    rd = analysis.get("recruiter_dashboard")
    analysis["dashboard_status"] = rd.get("status") if rd else "not_generated"
 
    return {"success": True, "analysis": analysis}


@router.get("/{analysis_id}/dashboard")
def get_dashboard(
    request:     Request,
    analysis_id: str,
    user:        CurrentUser,
) -> Dict[str, Any]:
    """Returns the pre-generated LLM-2 recruiter dashboard."""
    db = request.app.state.db
 
    analysis = db.repositories.find_one(
        {"analysis_id": analysis_id, "user_id": user["_id"]},
        {"_id": 0, "analysis_id": 1, "status": 1, "candidate_name": 1, "recruiter_dashboard": 1},
    )
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
 
    current_status = analysis.get("status")
 
    if current_status in ("pending", "processing"):
        return {
            "success":     False,
            "analysis_id": analysis_id,
            "status":      current_status,
            "message":     "Analysis still in progress.",
        }
 
    if current_status == "failed":
        return {
            "success":     False,
            "analysis_id": analysis_id,
            "status":      "analysis_failed",
            "message":     "Analysis failed. Please re-run.",
        }
 
    rd = analysis.get("recruiter_dashboard")
    if not rd:
        return {
            "success":     False,
            "analysis_id": analysis_id,
            "status":      "dashboard_not_generated",
            "message":     "Dashboard not generated. Re-run to generate.",
        }
 
    if rd.get("status") == "success":
        return {
            "success":           True,
            "analysis_id":       analysis_id,
            "status":            "success",
            "candidate_name":    analysis.get("candidate_name"),
            "dashboard":         rd.get("dashboard"),
            "generated_at":      rd.get("generated_at"),
            "generation_time_s": rd.get("generation_time_s"),
        }
 
    return {
        "success":           True,
        "analysis_id":       analysis_id,
        "status":            "generation_failed",
        "error":             rd.get("error"),
        "validation_errors": rd.get("validation_errors", []),
        "message":           "Dashboard generation failed. Raw analysis still available.",
    }

@router.delete("/{analysis_id}")
def delete_analysis(
    request:     Request,
    analysis_id: str,
    user:        CurrentUser,
) -> Dict[str, Any]:
    """Deletes an analysis owned by the current user."""
    db     = request.app.state.db
    result = db.repositories.delete_one({"analysis_id": analysis_id, "user_id": user["_id"]})
 
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
 
    return {"success": True, "message": "Analysis deleted"}