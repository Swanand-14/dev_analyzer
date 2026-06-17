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
        _WEIGHT_BY_TYPE = {"wiring": "high", "behavioral": "medium", "structural": "low"}
 
    # ── Negatives from signals ─────────────────────────────────────────────
    for cap, signals in sigs.items():
        for sig in signals:
            sig_type = sig.get("type")
            if sig_type == "negative":
                negative_findings.append({
                    "area":     cap.replace("_", " ").title(),
                    "finding":  sig.get("evidence", sig.get("action", "Unknown gap")),
                    "file":     sig.get("file"),
                    "severity": classify_severity(sig.get("action", "")),
                })
            elif sig_type in _WEIGHT_BY_TYPE:
                positive_findings.append({
                    "area":    cap.replace("_", " ").title(),
                    "finding": sig.get("evidence", sig.get("action", "Capability present")),
                    "weight":  _WEIGHT_BY_TYPE[sig_type],
                    "signal_type": sig_type,
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

_SYSTEM_PROMPT = """CRITICAL: Your response must be a raw JSON object only. No markdown. No ```json fences. No preamble. No explanation. Start your response with { and end with }.
 
You are a technical recruiting assistant. You receive structured developer analysis data and produce a recruiter-facing JSON summary powering a visual dashboard.
 
YOUR ROLE:
- Translate technical signals into recruiter-readable language
- Be factual and precise — every claim must be traceable to the input data
- Never invent findings not present in the input
- Never use emotional language or personality judgments
- Language is compact — recruiters scan, they don't read essays
- NO scores, NO skill levels, NO recommendations, NO verdicts
 
━━━ CAPABILITY STATUS RULES ━━━
Use exactly one of: "good" | "partial" | "missing" | "risk"
- "good"    = capability present and correctly implemented end-to-end
- "partial" = capability present but has gaps (e.g. imported but not wired)
- "missing" = capability not detected at all
- "risk"    = vulnerability or security issue detected
 
━━━ WIRING STATUS RULES ━━━
For each feature in signal_depth, emit three booleans:
- imported: true if a structural signal exists
- used:     true if a behavioral signal exists
- wired:    true if a wiring signal exists AND no blocking negative signal overrides it
 
━━━ ENGINEERING MATURITY SCORES ━━━
Compute four factual ratios 0–10:
- security_maturity:      (positive security signals) / (positive + negative security signals) * 10
- testing_maturity:       based on test_to_code_ratio, has_tests, has_mocks, only_happy_path (penalty)
- implementation_depth:   (wiring_signals / total_signals) * 10, capped at 10
- production_readiness:   presence of: has_cicd, env_example, parameterized_sql, rate_limiting_wired, secret_management; each worth 2 points
 
━━━ SECURITY POSTURE FIELDS ━━━
Each field is exactly one of: "pass" | "fail" | "partial"
- input_validation:  "pass" if input_validation true, "partial" if validation_libraries exist, "fail" otherwise
- auth_middleware:   "pass" if auth_middleware true, "partial" if auth_libraries exist but not wired, "fail" otherwise
- rate_limiting:     "pass" if rate_limiting_wired true, "partial" if rate_limiting detected but not wired, "fail" otherwise
- xss_protection:    "pass" if sanitization_libraries present, "fail" if xss signal exists, "partial" otherwise
- secret_management: "fail" if hardcoded_secret signal exists, "pass" if env_example and no hardcoded secrets, "partial" otherwise
- parameterized_sql: "pass" if parameterized_queries true, "fail" if sql_injection_risk signal exists, "partial" otherwise
- security_headers:  "pass" if helmet in auth_libraries, "fail" otherwise
- password_hashing:  "pass" if bcrypt or argon2 in auth_libraries, "fail" otherwise
 
━━━ TESTING MATURITY FIELDS ━━━
Boolean fields derived from testing facts:
- happy_path, edge_cases, auth_failure_tests, error_case_tests, mocks, integration_tests, async_tests
Include test_to_code_ratio as a float.
 
━━━ CI/CD PIPELINE FIELDS ━━━
Stages: "Push trigger", "Install", "Lint", "Test", "Build", "Deploy"
Each: { "step": string, "status": "pass" | "fail" | "skipped" }
Include extra_features[] for bonus CI features detected.
 
━━━ INTERVIEW RISK CARDS ━━━
- Pull from BOTH positive_findings and negative_findings in input
- For negatives: cards for "critical" and "high" severity; add 1–2 "medium" if total < 4
- For positives: add 1–2 strength cards (severity: "low") to highlight what went well
- Maximum 8 cards total
- Each card MUST contain: topic, severity, evidence_snippet, question, what_to_listen_for, red_flag
- evidence_snippet: use exact text from the finding field — not paraphrased
 
━━━ CAPABILITY RADAR ━━━
Emit scores 0–10 for exactly these 7 axes:
authentication, api, security, testing, ci_cd, documentation, database
Base each on ratio of positive to negative signals for that capability.
 
━━━ STACK SUMMARY ━━━
Group technologies into 3–4 descriptive labels — not raw library names.
Good: ["Node.js / Express", "JWT + Bcrypt", "Jest + Supertest", "GitHub Actions"]
 
━━━ ONE_LINER ━━━
2–3 sentences. Describe what the project does and its major functionality.
Never mention scoring, verdicts, or the developer.
 
━━━ OUTPUT SCHEMA ━━━
{
  "tldr": {
    "project_type": string,
    "one_liner": string,
    "stack_summary": string[],
    "quick_signals": { "positives": string[], "concerns": string[] }
  },
  "engineering_maturity": {
    "security_maturity": number,
    "testing_maturity": number,
    "implementation_depth": number,
    "production_readiness": number
  },
  "capability_radar": {
    "authentication": number,
    "api": number,
    "security": number,
    "testing": number,
    "ci_cd": number,
    "documentation": number,
    "database": number
  },
  "signal_depth": [
    { "feature": string, "imported": boolean, "used": boolean, "wired": boolean }
  ],
  "security_posture": {
    "input_validation": "pass" | "fail" | "partial",
    "auth_middleware": "pass" | "fail" | "partial",
    "rate_limiting": "pass" | "fail" | "partial",
    "xss_protection": "pass" | "fail" | "partial",
    "secret_management": "pass" | "fail" | "partial",
    "parameterized_sql": "pass" | "fail" | "partial",
    "security_headers": "pass" | "fail" | "partial",
    "password_hashing": "pass" | "fail" | "partial"
  },
  "testing_maturity_breakdown": {
    "happy_path": boolean,
    "edge_cases": boolean,
    "auth_failure_tests": boolean,
    "error_case_tests": boolean,
    "mocks": boolean,
    "integration_tests": boolean,
    "async_tests": boolean,
    "test_to_code_ratio": number
  },
  "cicd_pipeline": {
    "stages": [ { "step": string, "status": "pass" | "fail" | "skipped" } ],
    "extra_features": string[]
  },
  "strengths": [
    { "title": string, "detail": string, "area": string }
  ],
  "interview_risk_cards": [
    {
      "topic": string,
      "severity": "critical" | "high" | "medium" | "low",
      "evidence_snippet": string,
      "question": string,
      "what_to_listen_for": string,
      "red_flag": string
    }
  ],
  "capability_breakdown": [
    {
      "area": string,
      "icon": string,
      "status": "good" | "partial" | "missing" | "risk",
      "summary": string,
      "present": string[],
      "missing": string[]
    }
  ],
  "meta": {
    "repos_analyzed": number,
    "total_files": number,
    "total_lines": number,
    "total_signals": number,
    "wiring_signals": number,
    "negative_signals": number
  }
}"""


def _build_prompt(normalized: Dict) -> str:
    payload_json = json.dumps(normalized, default=str, separators=(",", ":"))
    return f"""**CRITICAL: RESPOND WITH ONLY VALID JSON. NO MARKDOWN. NO EXPLANATION.**
 
Start with: {{
End with: }}
 
Required top-level keys (exactly 11):
tldr, engineering_maturity, capability_radar, signal_depth, security_posture,
testing_maturity_breakdown, cicd_pipeline, strengths, interview_risk_cards,
capability_breakdown, meta
 
ANALYSIS DATA:
{payload_json}
 
ENUM CONSTRAINTS:
- security_posture values: pass | fail | partial
- capability_radar axes (all 7): authentication, api, security, testing, ci_cd, documentation, database
- signal_depth[].imported/used/wired: true or false (boolean)
- interview_risk_cards[].severity: critical | high | medium | low
- capability_breakdown[].status: good | partial | missing | risk
 
VALIDATION:
✓ All numeric values are numbers (not strings)
✓ All boolean values are true/false (not "true"/"false")
✓ No trailing commas
✓ All required fields present
✓ No markdown or backticks"""

def _clamp(value: Any, lo: float = 0.0, hi: float = 10.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return lo

def _validate(dashboard: Dict) -> Tuple[bool, List[str]]:
    errors: List[str] = []
 
    missing_top = REQUIRED_TOP_KEYS - set(dashboard.keys())
    if missing_top:
        errors.append(f"Missing top-level keys: {missing_top}")
 
    # tldr
    tldr = dashboard.get("tldr", {})
    missing_tldr = TLDR_FIELDS - set(tldr.keys() if isinstance(tldr, dict) else [])
    if missing_tldr:
        errors.append(f"tldr missing fields: {missing_tldr}")
    qs = tldr.get("quick_signals", {}) if isinstance(tldr, dict) else {}
    if not isinstance(qs, dict) or "positives" not in qs or "concerns" not in qs:
        errors.append("tldr.quick_signals must have 'positives' and 'concerns' arrays")
 
    # engineering_maturity
    em = dashboard.get("engineering_maturity", {})
    for f in ("security_maturity", "testing_maturity", "implementation_depth", "production_readiness"):
        if f not in em:
            errors.append(f"engineering_maturity missing: {f}")
        elif not isinstance(em[f], (int, float)):
            errors.append(f"engineering_maturity.{f} must be numeric")
 
    # capability_radar
    radar = dashboard.get("capability_radar", {})
    missing_axes = RADAR_AXES - set(radar.keys() if isinstance(radar, dict) else [])
    if missing_axes:
        errors.append(f"capability_radar missing axes: {missing_axes}")
 
    # security_posture
    sp = dashboard.get("security_posture", {})
    missing_sp = SECURITY_POSTURE_FIELDS - set(sp.keys() if isinstance(sp, dict) else [])
    if missing_sp:
        errors.append(f"security_posture missing fields: {missing_sp}")
    for field, val in (sp.items() if isinstance(sp, dict) else []):
        if field in SECURITY_POSTURE_FIELDS and val not in SECURITY_STATUSES:
            errors.append(f"security_posture.{field} invalid: {val!r}")
 
    # signal_depth
    sd = dashboard.get("signal_depth", [])
    if not isinstance(sd, list) or len(sd) == 0:
        errors.append("signal_depth must be a non-empty array")
 
    # testing_maturity_breakdown
    tmb = dashboard.get("testing_maturity_breakdown", {})
    for f in ("happy_path", "edge_cases", "auth_failure_tests", "error_case_tests",
              "mocks", "integration_tests", "async_tests", "test_to_code_ratio"):
        if f not in tmb:
            errors.append(f"testing_maturity_breakdown missing: {f}")
 
    # cicd_pipeline
    cicd_p = dashboard.get("cicd_pipeline", {})
    stages = cicd_p.get("stages", []) if isinstance(cicd_p, dict) else []
    if not isinstance(stages, list) or len(stages) == 0:
        errors.append("cicd_pipeline.stages must be non-empty")
    for i, stage in enumerate(stages):
        if stage.get("status") not in CICD_STEP_STATUSES:
            errors.append(f"cicd_pipeline.stages[{i}].status invalid: {stage.get('status')!r}")
 
    # interview_risk_cards
    cards = dashboard.get("interview_risk_cards", [])
    if not isinstance(cards, list):
        errors.append("interview_risk_cards must be an array")
    for i, card in enumerate(cards[:8]):
        for f in ("topic", "severity", "evidence_snippet", "question", "what_to_listen_for", "red_flag"):
            if f not in card:
                errors.append(f"interview_risk_cards[{i}] missing: {f}")
        if card.get("severity") not in SEVERITY_LEVELS:
            errors.append(f"interview_risk_cards[{i}].severity invalid: {card.get('severity')!r}")
 
    # capability_breakdown
    cb = dashboard.get("capability_breakdown", [])
    if not isinstance(cb, list) or len(cb) == 0:
        errors.append("capability_breakdown must be non-empty")
    for i, item in enumerate(cb[:3]):
        for f in ("area", "status", "summary"):
            if f not in item:
                errors.append(f"capability_breakdown[{i}] missing: {f}")
        if item.get("status") not in CAPABILITY_STATUSES:
            errors.append(f"capability_breakdown[{i}].status invalid: {item.get('status')!r}")
 
    # meta
    meta = dashboard.get("meta", {})
    for f in ("repos_analyzed", "total_files", "total_lines",
              "total_signals", "wiring_signals", "negative_signals"):
        if f not in meta:
            errors.append(f"meta missing: {f}")
 
    return len(errors) == 0, errors
 
 
def _coerce_bounds(dashboard: Dict) -> Dict:
    em = dashboard.get("engineering_maturity", {})
    for f in ("security_maturity", "testing_maturity", "implementation_depth", "production_readiness"):
        if f in em:
            em[f] = round(_clamp(em[f]), 1)
    radar = dashboard.get("capability_radar", {})
    for axis in RADAR_AXES:
        if axis in radar:
            radar[axis] = round(_clamp(radar[axis]), 1)
    return dashboard

def _parse_json(text: str) -> Dict:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
 
    first = text.find("{")
    last  = text.rfind("}")
    if first == -1 or last == -1:
        raise ValueError("No JSON object found in response")
 
    candidate = text[first: last + 1]
    ob = candidate.count("{"); cb = candidate.count("}")
    ob_br = candidate.count("["); cb_br = candidate.count("]")
 
    if ob > cb + 2 or ob_br > cb_br + 2:
        raise ValueError(f"Response truncated: {ob}/{cb} braces, {ob_br}/{cb_br} brackets")
 
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        if ob > cb:   candidate += "}" * (ob - cb)
        if ob_br > cb_br: candidate += "]" * (ob_br - cb_br)
        return json.loads(candidate)
    

def _call_llm(prompt: str, attempt: int = 1) -> Tuple[Optional[Dict], str]:
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=_SYSTEM_PROMPT,
    )
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.1,
            max_output_tokens=16384,
        ),
    )
    raw = response.text.strip()
    try:
        return _parse_json(raw), raw
    except (json.JSONDecodeError, ValueError) as e:
        print(f"   ⚠️  LLM-2 attempt {attempt}: parse failed — {str(e)[:80]}")
        return None, raw
 
 
def _build_repair_prompt(raw: str, errors: List[str]) -> str:
    error_list = "\n".join(f"  - {e}" for e in errors)
    return f"""Your previous response had validation errors. Fix ONLY the listed errors and return corrected JSON.
 
ERRORS:
{error_list}
 
PREVIOUS RESPONSE (fix this):
{raw[:6000]}
 
RULES:
- Return ONLY valid JSON — no markdown, no fences
- Fix every listed error exactly
- Do not change correct fields
- All enum values must be exact allowed values
- All numbers must be numeric (not strings)"""


def generate_recruiter_dashboard(
    merged_repo_analysis: Dict,
    gemini_flash_model=None,   # kept for backward compat but unused — model created internally
) -> Dict:
    """
    Public entry point for LLM-2.
 
    Takes merged_repo_analysis only — no unified_analysis, no scoring.
    Pure input → validated dashboard JSON.
 
    Returns:
      { "status": "success", "dashboard": {...}, "generation_time_s": float }
      { "status": "generation_failed", "error": str, "raw_output": str, "validation_errors": [...] }
    """
    start = time.time()
    print("\n🎨 LLM-2: Generating recruiter dashboard...")
 
    # Step 1 — normalize
    try:
        normalized   = _normalize_input(merged_repo_analysis)
        payload_size = len(json.dumps(normalized, separators=(",", ":")))
        print(f"   ✅ Normalized payload: {payload_size} chars")
        if payload_size > 5000:
            print(f"   ⚠️  Payload large — output may truncate")
    except Exception as e:
        return {"status": "generation_failed", "error": f"Normalization failed: {e}",
                "raw_output": "", "validation_errors": []}
 
    # Step 2 — first call
    prompt    = _build_prompt(normalized)
    raw_output = ""
    dashboard  = None
 
    try:
        dashboard, raw_output = _call_llm(prompt, attempt=1)
    except Exception as e:
        return {"status": "generation_failed", "error": f"LLM-2 API call failed: {e}",
                "raw_output": "", "validation_errors": []}
 
    # Step 3 — validate
    is_valid, validation_errors = False, []
    if dashboard is not None:
        is_valid, validation_errors = _validate(dashboard)
        if is_valid:
            print("   ✅ Dashboard valid on first attempt")
 
    # Step 4 — repair if needed
    if not is_valid:
        print(f"   ⚠️  Validation failed ({len(validation_errors)} errors) — attempting repair...")
        for e in validation_errors[:5]:
            print(f"      • {e}")
        try:
            repaired, raw_output = _call_llm(_build_repair_prompt(raw_output, validation_errors), attempt=2)
            if repaired is not None:
                is_valid2, errors2 = _validate(repaired)
                if is_valid2:
                    dashboard, validation_errors, is_valid = repaired, [], True
                    print("   ✅ Dashboard valid after repair")
                else:
                    validation_errors = errors2
                    print(f"   ❌ Repair failed ({len(errors2)} errors remain)")
        except Exception as e:
            print(f"   ❌ Repair call failed: {e}")
 
    # Step 5 — return
    elapsed = round(time.time() - start, 1)
    if is_valid and dashboard is not None:
        print(f"   ✅ Recruiter dashboard generated in {elapsed}s")
        return {
            "status":            "success",
            "dashboard":         _coerce_bounds(dashboard),
            "generation_time_s": elapsed,
        }
 
    print(f"   ❌ Dashboard generation failed after repair ({elapsed}s)")
    return {
        "status":            "generation_failed",
        "error":             "Schema validation failed after repair attempt",
        "raw_output":        raw_output[:2000],
        "validation_errors": validation_errors,
        "generation_time_s": elapsed,
    }
 