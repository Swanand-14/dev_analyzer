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
    {
        "name": "security_scan",
        "description": (
            "Returns a full security analysis of the candidate's codebase including: "
            "security posture (pass/fail/partial per category), security facts "
            "(libraries detected, practices present), and capability breakdown for security. "
            "Use this when the recruiter asks about security awareness, SQL injection, "
            "password hashing, secret management, XSS protection, input validation, "
            "rate limiting, or overall backend security."
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

def security_scan(db, analysis_id: str) -> Dict[str, Any]:
    """
    Reads security data from three sources in the stored analysis:
      1. security_posture      — pass/fail/partial per security field
      2. security_facts        — raw detected libraries + boolean practices
      3. capability_breakdown  — risk summary with present/missing lists
    Aggregates security_facts across all repos in the analysis.
    """
    doc = db.repositories.find_one(
        {"analysis_id": analysis_id},
        {
            "_id": 0,
            "repo_analyses.security_facts":                       1,
            "recruiter_dashboard.dashboard.security_posture":     1,
            "recruiter_dashboard.dashboard.capability_breakdown": 1,
        }
    )
    if not doc:
        return {"error": f"No analysis found for id: {analysis_id}"}
 
    # ── Security posture (pass/fail/partial) ──────────────────
    security_posture = (
        doc.get("recruiter_dashboard", {})
           .get("dashboard", {})
           .get("security_posture", {})
    )
    merged_facts: Dict[str, Any] = {
        "auth_libraries":                [],
        "validation_libraries":          [],
        "sanitization_libraries":        [],
        "rate_limiting_present":         False,
        "csrf_protection_present":       False,
        "input_validation_present":      False,
        "auth_middleware_present":       False,
        "env_file_example_present":      False,
        "parameterized_queries_present": False,
    }
    for repo in doc.get("repo_analyses", []):
        facts = repo.get("security_facts", {})
        for lib_key in ("auth_libraries", "validation_libraries", "sanitization_libraries"):
            for lib in facts.get(lib_key, []):
                if lib not in merged_facts[lib_key]:
                    merged_facts[lib_key].append(lib)
        for bool_key in (
            "rate_limiting_present", "csrf_protection_present",
            "input_validation_present", "auth_middleware_present",
            "env_file_example_present", "parameterized_queries_present",
        ):
            if facts.get(bool_key):
                merged_facts[bool_key] = True


    capability_breakdown = (
        doc.get("recruiter_dashboard", {})
           .get("dashboard", {})
           .get("capability_breakdown", [])
    )
    security_breakdown = next(
        (c for c in capability_breakdown
         if c.get("area", "").lower() == "security"),
        None,
    )
 
    return {
        "analysis_id":        analysis_id,
        "security_posture":   security_posture,
        "security_facts":     merged_facts,
        "security_breakdown": security_breakdown,
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
    
    if function_name == "security_scan":
        return security_scan(db, analysis_id)
 
    return {"error": f"Unknown tool: {function_name}"}