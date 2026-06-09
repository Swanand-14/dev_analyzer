

from typing import Literal

SeverityLevel = Literal["critical", "high", "medium", "low"]

# Keywords per severity tier — checked against the action name
_CRITICAL_KEYWORDS = ["xss", "injection", "hardcoded_secret", "csrf"]
_HIGH_KEYWORDS     = ["no_input_validation", "auth_not", "jwt_verify", "unprotected", "auth_middleware_not_wired"]
_MEDIUM_KEYWORDS   = ["env", "happy_path", "no_error", "rate_limit", "not_wired", "not_detected"]


def classify_severity(action: str) -> SeverityLevel:
    """
    Returns a severity level for a negative signal action.

    Tiers:
      critical — exploitable vulnerabilities (XSS, SQL injection, hardcoded secrets)
      high     — missing auth checks, unverified tokens, no input validation
      medium   — missing env example, rate limiting gaps, happy-path-only tests
      low      — everything else
    """
    action_lower = action.lower()

    if any(kw in action_lower for kw in _CRITICAL_KEYWORDS):
        return "critical"
    if any(kw in action_lower for kw in _HIGH_KEYWORDS):
        return "high"
    if any(kw in action_lower for kw in _MEDIUM_KEYWORDS):
        return "medium"
    return "low"