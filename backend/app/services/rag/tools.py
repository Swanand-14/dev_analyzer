from typing import Any, Dict, List

TOOL_DECLARATIONS = [
    {
        "name": "extract_technologies",
        "description": (
            "Returns the list of technologies and libraries detected in the "
            "candidate's GitHub repositories. Use this when the recruiter asks "
            "about the tech stack, frameworks, languages, or tools the developer knows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_id": {
                    "type":        "string",
                    "description": "The analysis ID for the candidate's analysis run.",
                }
            },
            "required": ["analysis_id"],
        },
    },
    {
        "name": "get_repo_summary",
        "description": (
            "Returns a high-level summary of the candidate's repositories: "
            "project type, detected features, file count, repo names, and technologies. "
            "Use this when the recruiter asks what kind of project this is, what the "
            "codebase does, or what capabilities were detected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_id": {
                    "type":        "string",
                    "description": "The analysis ID for the candidate's analysis run.",
                }
            },
            "required": ["analysis_id"],
        },
    },
]

def extract_technologies(db, analysis_id: str) -> Dict[str, Any]:
    """
    Reads detected technologies from the stored merged_repo_analysis.
    Returns the list produced by Stage-1's _extract_technologies() —
    no re-computation needed.
    """
    doc = db.repositories.find_one(
        {"analysis_id": analysis_id},
        {
            "_id": 0,
            "merged_repo_analysis.technologies": 1,
        }
    )
 
    if not doc:
        return {"error": f"No analysis found for id: {analysis_id}"}
 
    technologies = (
        doc.get("merged_repo_analysis", {})
           .get("technologies", [])
    )
 
    return {
        "analysis_id":  analysis_id,
        "technologies": technologies,
        "count":        len(technologies),
    }

def get_repo_summary(db, analysis_id: str) -> Dict[str, Any]:
    """
    Reads repo summary from the stored analysis document.
    Combines merged_repo_analysis scale data + recruiter_dashboard tldr
    for a complete picture without re-running anything.
    """
    doc = db.repositories.find_one(
        {"analysis_id": analysis_id},
        {
            "_id": 0,
            "merged_repo_analysis.technologies":           1,
            "merged_repo_analysis.total_files":            1,
            "merged_repo_analysis.total_lines":            1,
            "merged_repo_analysis.signals_by_capability":  1,
            "merged_repo_analysis.repositories":           1,
            "recruiter_dashboard.dashboard.tldr":          1,
        }
    )
 
    if not doc:
        return {"error": f"No analysis found for id: {analysis_id}"}
 
    merged = doc.get("merged_repo_analysis", {})
    tldr   = (
        doc.get("recruiter_dashboard", {})
           .get("dashboard", {})
           .get("tldr", {})
    )
 
    return {
        "analysis_id":       analysis_id,
        "project_type":      tldr.get("project_type", "Unknown"),
        "one_liner":         tldr.get("one_liner", ""),
        "technologies":      merged.get("technologies", []),
        "total_files":       merged.get("total_files", 0),
        "total_lines":       merged.get("total_lines", 0),
        "features_detected": list(merged.get("signals_by_capability", {}).keys()),
        "repos": [
            {
                "name":         r.get("repo_name", ""),
                "project_type": r.get("project_type", "Unknown"),
                "files":        r.get("total_files", 0),
            }
            for r in merged.get("repositories", [])
        ],
        "stack_summary": tldr.get("stack_summary", []),
    }

def dispatch_tool_call(db, function_name: str, function_args: Dict) -> Dict:
    """
    Routes a Gemini function_call to the correct Python function.
    Returns the tool result as a dict.
    """
    analysis_id = function_args.get("analysis_id", "")
 
    if function_name == "extract_technologies":
        return extract_technologies(db, analysis_id)
 
    if function_name == "get_repo_summary":
        return get_repo_summary(db, analysis_id)
 
    return {"error": f"Unknown tool: {function_name}"}