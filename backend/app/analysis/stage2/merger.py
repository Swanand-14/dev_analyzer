# app/analysis/stage2/merger.py
#
# merge_repo_analyses() — merges Stage-1 outputs from 1-3 repos
# into a single deduplicated signal pack.
#
# Per-repo output in the result is scale metadata ONLY — no signal re-embedding.
# All signals are deduplicated via SignalPostprocessor.

from collections import defaultdict
from typing import Any, Dict, List

from app.utils.signal_postprocessor import SignalPostprocessor


def merge_repo_analyses(analyses: List[Dict]) -> Dict[str, Any]:
    """
    Merges Stage-1 outputs from 1-3 repos into one signal pack.

    Steps:
      1. Filter out failed analyses
      2. Merge + deduplicate signals via SignalPostprocessor
      3. Aggregate fact booleans and lists across repos
      4. Return merged dict — per-repo data is scale metadata only

    Returns {"error": "..."} if all repos failed.
    """
    successful = [a for a in analyses if not a.get("error")]
    if not successful:
        return {"error": "All repository analyses failed"}

    
    total_files   = sum(a.get("total_files",  0) for a in successful)
    total_lines   = sum(a.get("total_lines",  0) for a in successful)
    total_commits = sum(a.get("activity_facts", {}).get("total_commits", 0) for a in successful)
    unique_techs  = sorted(set(t for a in successful for t in a.get("technologies", [])))

   
    raw_merged: Dict[str, List] = defaultdict(list)
    for a in successful:
        for cap, signals in a.get("signals_by_capability", {}).items():
            raw_merged[cap].extend(signals)

    cleaned        = SignalPostprocessor.clean(dict(raw_merged))
    merged_signals = cleaned["signals_by_capability"]

    total_signals = wiring_signals = negative_signals = behavioural_signals = structural_signals =  0
    for sigs in merged_signals.values():
        for s in sigs:
            total_signals += 1
            t = s.get("type", "")
            if t == "wiring":    wiring_signals   += 1
            elif t == "negative":negative_signals += 1
            elif t == "behavioral": behavioral_signals += 1
            elif t == "structural": structural_signals += 1

   
    def any_true(key_path: List[str]) -> bool:
        for a in successful:
            obj = a
            for k in key_path:
                obj = obj.get(k, {}) if isinstance(obj, dict) else {}
            if obj is True:
                return True
        return False

    def collect_lists(key_path: List[str]) -> List:
        result = set()
        for a in successful:
            obj = a
            for k in key_path:
                obj = obj.get(k, []) if isinstance(obj, dict) else []
            if isinstance(obj, list):
                result.update(obj)
        return list(result)

    
    testing_summary = {
        "has_tests":          any_true(["testing_facts", "has_tests"]),
        "test_files_count":   sum(a.get("testing_facts", {}).get("test_files_count", 0) for a in successful),
        "test_to_code_ratio": round(
            sum(a.get("testing_facts", {}).get("test_to_code_ratio", 0) for a in successful) / len(successful), 1
        ),
        "frameworks":         collect_lists(["testing_facts", "testing_frameworks"]),
        "only_happy_path":    all(a.get("testing_facts", {}).get("only_happy_path_tested", True) for a in successful),
        "has_mocks":          any_true(["testing_facts", "has_mock_usage"]),
    }

    cicd_summary = {
        "has_cicd":          any_true(["cicd_facts", "has_cicd"]),
        "platforms":         collect_lists(["cicd_facts", "cicd_platforms"]),
        "runs_tests_in_ci":  any_true(["cicd_facts", "runs_tests_in_ci"]),
        "runs_lint_in_ci":   any_true(["cicd_facts", "runs_lint_in_ci"]),
        "runs_build_in_ci":  any_true(["cicd_facts", "runs_build_in_ci"]),
        "runs_deploy_in_ci": any_true(["cicd_facts", "runs_deploy_in_ci"]),
    }

    security_summary = {
        "auth_libraries":            collect_lists(["security_facts", "auth_libraries"]),
        "validation_libraries":      collect_lists(["security_facts", "validation_libraries"]),
        "rate_limiting":             any_true(["security_facts", "rate_limiting_present"]),
        "rate_limiting_wired":       any_true(["security_facts", "rate_limiting_wired"]),
        "csrf_protection":           any_true(["security_facts", "csrf_protection_present"]),
        "csrf_protection_wired":     any_true(["security_facts", "csrf_protection_wired"]),
        "input_validation_present":  any_true(["security_facts", "input_validation_present"]),
        "auth_middleware_present":   any_true(["security_facts", "auth_middleware_present"]),
        "env_example_present":       any_true(["security_facts", "env_file_example_present"]),
        "parameterized_queries":     any_true(["security_facts", "parameterized_queries_present"]),
    }

    doc_summary = {
        "has_readme":       any_true(["documentation_facts", "has_readme"]),
        "has_contributing": any_true(["documentation_facts", "has_contributing_guide"]),
        "has_license":      any_true(["documentation_facts", "has_license"]),
        "readme_sections":  collect_lists(["documentation_facts", "readme_sections_present"]),
    }

    
    repo_summaries = [
        {
            "repo_url":      a["repo_url"],
            "repo_name":     a.get("repo_name"),
            "total_files":   a.get("total_files",  0),
            "total_lines":   a.get("total_lines",  0),
            "total_signals": a.get("total_signals", 0),
            "project_type":  a.get("project_context", {}).get("project_type", "Unknown"),
            "project_summary": a.get("project_context", {}).get("project_summary", ""),
        }
        for a in successful
    ]

    return {
        "total_repos_analyzed":   len(successful),
        "total_files":            total_files,
        "total_lines":            total_lines,
        "total_commits":          total_commits,
        "technologies":           unique_techs,
        "signals_by_capability":  merged_signals,
        "total_signals":          total_signals,
        "total_wiring_signals":   wiring_signals,
        "total_negative_signals": negative_signals,
        "total_behavioral_signals": behavioral_signals,
        "total_structural_signals": structural_signals,
        "testing_summary":        testing_summary,
        "cicd_summary":           cicd_summary,
        "security_summary":       security_summary,
        "documentation_summary":  doc_summary,
        "repositories":           repo_summaries,
    }