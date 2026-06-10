import json
import time
from typing import Any, Dict, List, Optional, Tuple
 
import google.generativeai as genai
 
from app.analysis.stage2.severity import classify_severity

CAPABILITY_STATUSES = {"good", "partial", "missing", "risk"}
CICD_STEP_STATUSES  = {"pass", "fail", "skipped"}
SECURITY_STATUSES   = {"pass", "fail", "partial"}
SEVERITY_LEVELS     = {"critical", "high", "medium", "low"}
 
REQUIRED_TOP_KEYS = {
    "tldr", "engineering_maturity", "capability_radar",
    "signal_depth", "security_posture", "testing_maturity_breakdown",
    "cicd_pipeline", "strengths", "interview_risk_cards",
    "capability_breakdown", "meta",
}
 
SECURITY_POSTURE_FIELDS = {
    "input_validation", "auth_middleware", "rate_limiting", "xss_protection",
    "secret_management", "parameterized_sql", "security_headers", "password_hashing",
}
 
RADAR_AXES = {
    "authentication", "api", "security", "testing", "ci_cd", "documentation", "database",
}
 
TLDR_FIELDS = {
    "project_type", "one_liner", "stack_summary", "quick_signals",
}


def _build_findings(repo_analysis: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Derives positive and negative findings directly from merged_repo_analysis.
    No scoring. No platform data. Pure GitHub signal facts.
    """
    positive_findings: List[Dict] = []
    negative_findings: List[Dict] = []
 
    if repo_analysis.get("error"):
        return positive_findings, negative_findings
 
    sigs     = repo_analysis.get("signals_by_capability", {})
    testing  = repo_analysis.get("testing_summary",  {})
    cicd     = repo_analysis.get("cicd_summary",     {})
    security = repo_analysis.get("security_summary", {})
 
    # ── Positives ─────────────────────────────────────────────────────────
    implemented = [
        cap for cap, signals in sigs.items()
        if sum(1 for s in signals if s.get("type") == "wiring") >= 2
    ]
    if len(implemented) >= 3:
        positive_findings.append({
            "area":    "Architecture",
            "finding": f"Multiple capabilities proven in execution flow: {', '.join(implemented)}",
            "weight":  "high",
        })
 
    if security.get("auth_libraries"):
        positive_findings.append({
            "area":    "Authentication",
            "finding": f"Auth libraries in use: {', '.join(security['auth_libraries'])}",
            "weight":  "high",
        })
 
    if cicd.get("has_cicd"):
        ci_steps = [s for s in ["tests", "lint", "build", "deploy"] if cicd.get(f"runs_{s}_in_ci")]
        positive_findings.append({
            "area":    "DevOps",
            "finding": f"CI/CD pipeline ({', '.join(cicd.get('platforms', []))})"
                       + (f" — runs: {', '.join(ci_steps)}" if ci_steps else ""),
            "weight":  "medium",
        })
 
    if testing.get("has_tests"):
        ratio = testing.get("test_to_code_ratio", 0)
        positive_findings.append({
            "area":    "Testing",
            "finding": f"Test suite present — {ratio}% test-to-code ratio"
                       + (f", frameworks: {', '.join(testing.get('frameworks', []))}" if testing.get("frameworks") else ""),
            "weight":  "medium" if ratio >= 30 else "low",
        })
 
    if security.get("rate_limiting_wired"):
        positive_findings.append({
            "area":    "Security",
            "finding": "Rate limiting wired into request flow",
            "weight":  "medium",
        })
 
    if security.get("csrf_protection_wired"):
        positive_findings.append({
            "area":    "Security",
            "finding": "CSRF protection wired into request flow",
            "weight":  "medium",
        })
 
    # ── Negatives from signals ─────────────────────────────────────────────
    for cap, signals in sigs.items():
        for sig in signals:
            if sig.get("type") == "negative":
                negative_findings.append({
                    "area":     cap.replace("_", " ").title(),
                    "finding":  sig.get("evidence", sig.get("action", "Unknown gap")),
                    "file":     sig.get("file"),
                    "severity": classify_severity(sig.get("action", "")),
                })
 
    # ── Summary-level negatives ────────────────────────────────────────────
    if not security.get("input_validation_present") and not security.get("validation_libraries"):
        negative_findings.append({
            "area": "API", "finding": "No input validation library detected on any route",
            "file": None, "severity": "high",
        })
 
    if not testing.get("has_tests"):
        negative_findings.append({
            "area": "Testing", "finding": "No test files found in repository",
            "file": None, "severity": "high",
        })
    elif testing.get("only_happy_path"):
        negative_findings.append({
            "area": "Testing", "finding": "Only happy-path tests detected — no error case coverage",
            "file": None, "severity": "medium",
        })
 
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    negative_findings.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))
 
    return positive_findings, negative_findings

def _normalize_input(merged_repo_analysis: Dict) -> Dict:
    """
    Compress merged_repo_analysis into a minimal token-efficient payload for LLM-2.
    Target: under 4000 chars so the model has room to generate output.
    """
    signals_by_cap: Dict[str, List] = merged_repo_analysis.get("signals_by_capability", {})
 
    # Signal counts only — not individual signals
    signal_counts_by_cap = {}
    for cap, signals in signals_by_cap.items():
        counts = {"structural": 0, "behavioral": 0, "wiring": 0, "negative": 0}
        for s in signals:
            t = s.get("type", "structural")
            counts[t] = counts.get(t, 0) + 1
        signal_counts_by_cap[cap] = counts
 
    testing  = merged_repo_analysis.get("testing_summary",       {})
    cicd     = merged_repo_analysis.get("cicd_summary",          {})
    security = merged_repo_analysis.get("security_summary",      {})
    docs     = merged_repo_analysis.get("documentation_summary", {})
 
    positive_findings, negative_findings = _build_findings(merged_repo_analysis)
 
    # Trim to keep payload lean
    neg_trimmed = [
        {"area": n["area"], "finding": n["finding"][:80], "severity": n["severity"]}
        for n in negative_findings[:6]
    ]
    pos_trimmed = [
        {"area": p["area"], "finding": p["finding"][:60]}
        for p in positive_findings[:4]
    ]
 
    return {
        "scale": {
            "repos":        merged_repo_analysis.get("total_repos_analyzed", 0),
            "files":        merged_repo_analysis.get("total_files",          0),
            "lines":        merged_repo_analysis.get("total_lines",          0),
            "technologies": merged_repo_analysis.get("technologies",         []),
        },
        "signal_counts": {
            "total":         merged_repo_analysis.get("total_signals",          0),
            "wiring":        merged_repo_analysis.get("total_wiring_signals",   0),
            "negative":      merged_repo_analysis.get("total_negative_signals", 0),
            "behavioral":    merged_repo_analysis.get("total_behavioral_signals", 0),
            "structural":    merged_repo_analysis.get("total_structural_signals", 0),
            "by_capability": signal_counts_by_cap,
        },
        "positive_findings": pos_trimmed,
        "negative_findings": neg_trimmed,
        "testing": {
            "has_tests":       testing.get("has_tests",          False),
            "ratio":           testing.get("test_to_code_ratio", 0),
            "only_happy_path": testing.get("only_happy_path",    True),
            "has_mocks":       testing.get("has_mocks",          False),
            "frameworks":      testing.get("frameworks",         []),
        },
        "cicd": {
            "has_cicd":    cicd.get("has_cicd",          False),
            "platforms":   cicd.get("platforms",         []),
            "runs_tests":  cicd.get("runs_tests_in_ci",  False),
            "runs_lint":   cicd.get("runs_lint_in_ci",   False),
            "runs_build":  cicd.get("runs_build_in_ci",  False),
            "runs_deploy": cicd.get("runs_deploy_in_ci", False),
        },
        "security": {
            "auth_libraries":        security.get("auth_libraries",           []),
            "validation_libraries":  security.get("validation_libraries",     []),
            "rate_limiting":         security.get("rate_limiting",            False),
            "rate_limiting_wired":   security.get("rate_limiting_wired",      False),
            "csrf_wired":            security.get("csrf_protection_wired",    False),
            "input_validation":      security.get("input_validation_present", False),
            "auth_middleware":        security.get("auth_middleware_present",  False),
            "env_example":           security.get("env_example_present",      False),
            "parameterized_queries": security.get("parameterized_queries",    False),
        },
        "docs": {
            "has_readme":      docs.get("has_readme",           False),
            "has_license":     docs.get("has_license",          False),
            "readme_sections": docs.get("readme_sections",      []),
        },
        "capabilities_detected": list(signals_by_cap.keys()),
        "meta": {
            "repos_analyzed":  merged_repo_analysis.get("total_repos_analyzed",    0),
            "total_files":     merged_repo_analysis.get("total_files",             0),
            "total_lines":     merged_repo_analysis.get("total_lines",             0),
            "total_signals":   merged_repo_analysis.get("total_signals",           0),
            "wiring_signals":  merged_repo_analysis.get("total_wiring_signals",    0),
            "negative_signals":merged_repo_analysis.get("total_negative_signals",  0),
        },
    }


