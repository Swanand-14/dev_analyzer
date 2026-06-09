# app/utils/signal_postprocessor.py
#
# Stage-1.5 Signal Cleanup Pipeline
#
# DESIGN PHILOSOPHY:
#   Rules operate on PATTERNS (action name shapes, evidence shapes, capability
#   mismatches) — NOT on specific known values from one sample repo.
#   This means the pipeline generalises to any future repo automatically.
#
# PIPELINE STAGES (in order):
#   A. Pattern-based noise drop   — catches structural boilerplate by shape
#   B. Canonicalization           — explicit map for known semantic duplicates
#   C. Pattern-based canonicalization — catches unknown LLM variants by regex
#   D. Evidence compression       — shortens verbose evidence strings
#   E. Cross-capability dedupe    — removes library signals in wrong buckets
#   F. Within-capability dedupe   — (action,file) pairs + global-property actions
#      F1. Semantic alias collapse — *_detected superseded by *_imported
#   G. Aggregate recalculation    — recomputes all counters from cleaned signals

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple




ACTION_CANON: Dict[str, str] = {
    # XSS family
    "xss_risk_unsanitized_template":            "xss_risk_unsanitized_output",
    "xss_risk_unsanitized_input":               "xss_risk_unsanitized_output",
    "user_input_rendered_without_sanitization": "xss_risk_unsanitized_output",
    "unsanitized_user_input_in_response":       "xss_risk_unsanitized_output",
    "xss_vulnerability_detected":              "xss_risk_unsanitized_output",
    "xss_vulnerability_unsanitized_output":    "xss_risk_unsanitized_output",

    # Auth-not-wired family
    "routes_lack_authentication_check":              "auth_middleware_not_wired",
    "route_lacks_authentication_check":              "auth_middleware_not_wired",
    "profile_endpoint_auth_check_missing":           "auth_middleware_not_wired",
    "endpoint_lacks_auth_check":                     "auth_middleware_not_wired",
    "auth_library_imported_but_middleware_not_wired":"auth_middleware_not_wired",
    "auth_middleware_missing_on_routes":             "auth_middleware_not_wired",
    "no_auth_middleware_on_routes":                  "auth_middleware_not_wired",
    "protected_route_missing_auth_check":            "auth_middleware_not_wired",
    "missing_authentication_on_route":               "auth_middleware_not_wired",
    "route_unprotected":                             "auth_middleware_not_wired",

    # SQL injection family
    "sql_injection_vulnerability":             "sql_injection_risk",
    "sql_injection_risk_pattern_detected":     "sql_injection_risk",
    "string_concatenation_in_sql_query":       "sql_injection_risk",

    # Noise: pure boilerplate structural signals
    "router_exported":                         "_DROP_",
    "app_listen_called":                       "_DROP_",
    "root_route_responds_with_json":           "_DROP_",
    "send_data_to_api_register":               "_DROP_",
    "console_log_called":                      "_DROP_",
    "module_exported":                         "_DROP_",
    "app_imported":                            "_DROP_",
    "express_json_middleware_imported":        "_DROP_",
    "root_route_defined":                      "_DROP_",
    "express_app_initialized":                 "_DROP_",
    "routes_imported":                         "_DROP_",
}




ALWAYS_DROP_ACTIONS: frozenset = frozenset([
    "router_exported", "app_listen_called", "root_route_responds_with_json",
    "send_data_to_api_register", "console_log_called", "module_exported",
    "app_imported", "express_json_middleware_imported", "root_route_defined",
    "express_app_initialized", "routes_imported",
])



ACTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r".*lacks?_auth.*|.*no_auth.*on.*|.*missing.*auth.*check.*|.*unprotected.*route.*", re.IGNORECASE), "auth_middleware_not_wired"),
    (re.compile(r".*xss.*|.*unsanitized.*(output|template|render|response).*|.*(input|user_data).*rendered.*without.*", re.IGNORECASE), "xss_risk_unsanitized_output"),
    (re.compile(r".*sql.*inject.*|.*string.*concat.*sql.*|.*query.*concatenat.*", re.IGNORECASE), "sql_injection_risk"),
    (re.compile(r"^app_(listen|start|run|boot)_called$", re.IGNORECASE), "_DROP_"),
    (re.compile(r"^(module|file|component|class)_exported$", re.IGNORECASE), "_DROP_"),
    (re.compile(r"^(json|body_parser|cors)_middleware_(imported|declared)$", re.IGNORECASE), "_DROP_"),
]



DEDUPE_BY_ACTION_ONLY: frozenset = frozenset([
    "auth_middleware_not_wired",
    "no_input_validation_detected",
    "rate_limiting_not_detected",
    "rate_limiting_not_wired",
    "csrf_protection_not_wired",
    "no_env_example_file",
    "jwt_verify_never_called",
    "no_csrf_protection_detected",
    "https_not_enforced",
    "no_error_handling_detected",
    "no_logging_detected",
])



SEMANTIC_ALIASES: Dict[str, str] = {
    "jsonwebtoken_library_detected": "jwt_library_imported",
    "bcrypt_library_detected":       "bcrypt_library_imported",
    "argon2_library_detected":       "argon2_library_imported",
    "nextauth_library_detected":     "nextauth_library_imported",
    "passport_library_detected":     "passport_library_imported",
    "mongoose_library_detected":     "mongoose_orm_imported",
    "prisma_library_detected":       "prisma_orm_imported",
    "sequelize_library_detected":    "sequelize_orm_imported",
    "express_library_detected":      "express_framework_imported",
    "helmet_library_detected":       "helmet_security_imported",
    "zod_library_detected":          "zod_validation_imported",
    "joi_library_detected":          "joi_validation_imported",
}

_DETECTED_PATTERN = re.compile(r"^(.+)_library_detected$")
_IMPORTED_PATTERN = re.compile(r"^(.+)_library_imported$")



AUTHORITATIVE_CAPABILITY: Dict[str, str] = {
    "bcrypt_library_detected":          "authentication",
    "bcrypt_library_imported":          "authentication",
    "jsonwebtoken_library_detected":    "authentication",
    "jwt_library_imported":             "authentication",
    "argon2_library_detected":          "authentication",
    "argon2_library_imported":          "authentication",
    "nextauth_library_detected":        "authentication",
    "nextauth_library_imported":        "authentication",
    "passport_library_detected":        "authentication",
    "passport_library_imported":        "authentication",
    "pyjwt_library_detected":           "authentication",
    "passlib_library_detected":         "authentication",
    "helmet_library_detected":          "api",
    "helmet_security_imported":         "api",
    "xss_library_detected":             "api",
    "zod_library_detected":             "api",
    "zod_validation_imported":          "api",
    "joi_library_detected":             "api",
    "joi_validation_imported":          "api",
    "express_framework_imported":       "api",
    "express_validator_library_detected":"api",
    "dompurify_library_detected":       "api",
    "sanitize_html_library_detected":   "api",
    "prisma_orm_imported":              "database",
    "mongoose_orm_imported":            "database",
    "sequelize_orm_imported":           "database",
    "typeorm_library_detected":         "database",
    "mongoose_library_detected":        "database",
    "prisma_library_detected":          "database",
}

_AUTHORITATIVE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"(jwt|bcrypt|argon|passlib|passport|next.?auth|pyjwt).*", re.IGNORECASE), "authentication"),
    (re.compile(r"(helmet|xss|zod|joi|validator|express.?validator|dompurify|sanitize).*", re.IGNORECASE), "api"),
    (re.compile(r"(prisma|mongoose|sequelize|typeorm|sqlalchemy|pymongo|pg_library|mysql).*", re.IGNORECASE), "database"),
]




EVIDENCE_COMPRESSIONS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"The\s+['\"/]?\/?\w*['\"/]?\s+route.*?(?:mounted|applied).*?without.*?auth.*?checks.*", re.IGNORECASE | re.DOTALL), "Routes mounted without auth checks"),
    (re.compile(r"Auth\s*lib.*?(?:present|imported).*?(?:no|but).*?middleware.*?(?:wired|applied).*", re.IGNORECASE | re.DOTALL), "Auth library present but middleware not wired to routes"),
    (re.compile(r".*README.*lists.*endpoint.*but.*(?:no|missing).*auth.*check.*", re.IGNORECASE | re.DOTALL), "Endpoint listed in README lacks authentication check"),
    (re.compile(r"(POST|GET|PUT|DELETE|PATCH)\s+\S+\s+route does not appear to have an? authentication check.*", re.IGNORECASE), r"\1 route lacks authentication check"),
    (re.compile(r"jwt.*(?:library|module)?.*(?:imported|required).*but.*jwt\.verify.*(?:not|never).*call.*", re.IGNORECASE | re.DOTALL), "jwt imported but jwt.verify not called anywhere"),
    (re.compile(r"jwt\.verify.*(?:not|never).*(?:called|used|invoked).*", re.IGNORECASE | re.DOTALL), "jwt imported but jwt.verify not called anywhere"),
    (re.compile(r"The\s+\w+\s+secret has a fallback to\s+['\"].*?['\"].*?if.*?environment.*?variable.*", re.IGNORECASE | re.DOTALL), "Secret has insecure hardcoded fallback value"),
    (re.compile(r"No\s+\.env(?:\.example)?\s+file\s+found.*", re.IGNORECASE | re.DOTALL), "No .env.example file found"),
    (re.compile(r"Unsanitized output pattern:\s*", re.IGNORECASE), "Unsanitized output: "),
    (re.compile(r"res\.send\(.*?\$\{.*?\}.*?\).*?(?:innerHTML|XSS|unsanitized|risk).*", re.IGNORECASE | re.DOTALL), "res.send() with unescaped user input — XSS risk"),
    (re.compile(r"'([^']+)'\s+found\s+in\s+imports(?:/usage)?", re.IGNORECASE), r"\1 library imported"),
    (re.compile(r"(\w+)\s+(?:library\s+)?is\s+imported\s+but\s+\1\.\w+\s+is\s+not\s+called.*", re.IGNORECASE | re.DOTALL), r"\1 imported but critical method not called"),
]



class SignalPostprocessor:
    """
    Stateless post-processing pipeline — generalises to any repository.
    Rules operate on action name shapes and evidence patterns, not repo-specific data.
    """

    @classmethod
    def clean(cls, signals_by_capability: Dict[str, List]) -> Dict:
        if not signals_by_capability:
            return {"signals_by_capability": {}, "statistics": cls._empty_stats()}

        normalized = {
            cap: cls._normalize_signals(signals)
            for cap, signals in signals_by_capability.items()
        }
        normalized = {k: v for k, v in normalized.items() if v}
        normalized = cls._cross_capability_dedupe(normalized)

        deduped = {
            cap: cls._within_capability_dedupe(signals)
            for cap, signals in normalized.items()
        }
        deduped = {k: v for k, v in deduped.items() if v}

        return {"signals_by_capability": deduped, "statistics": cls._compute_statistics(deduped)}

    @classmethod
    def _normalize_signals(cls, signals: List) -> List:
        result = []
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            action = sig.get("action", "")
            if action in ALWAYS_DROP_ACTIONS:
                continue
            canonical = ACTION_CANON.get(action)
            if canonical == "_DROP_":
                continue
            if canonical:
                action = canonical
            else:
                pc = cls._pattern_canonicalize(action)
                if pc == "_DROP_":
                    continue
                if pc:
                    action = pc
            cleaned          = dict(sig)
            cleaned["action"]   = action
            cleaned["evidence"] = cls._compress_evidence(cleaned.get("evidence", ""))
            result.append(cleaned)
        return result

    @classmethod
    def _pattern_canonicalize(cls, action: str) -> Optional[str]:
        for pattern, canonical in ACTION_PATTERNS:
            if pattern.fullmatch(action):
                return canonical
        return None

    @classmethod
    def _compress_evidence(cls, evidence: str) -> str:
        if not evidence:
            return evidence
        evidence = evidence.strip()
        for pattern, replacement in EVIDENCE_COMPRESSIONS:
            try:
                compressed = pattern.sub(replacement, evidence)
                if compressed != evidence:
                    return compressed.strip()
            except Exception:
                pass
        if len(evidence) > 150:
            evidence = evidence[:147] + "..."
        return evidence

    @classmethod
    def _cross_capability_dedupe(cls, signals_by_cap: Dict[str, List]) -> Dict[str, List]:
        index: Dict[Tuple, List] = defaultdict(list)
        for cap, signals in signals_by_cap.items():
            for sig in signals:
                key = (sig.get("action", ""), sig.get("file"))
                index[key].append((cap, sig))

        to_drop: set = set()
        for key, entries in index.items():
            if len(entries) <= 1:
                continue
            authoritative = cls._resolve_authoritative_cap(key[0])
            if authoritative:
                for cap, sig in entries:
                    if cap != authoritative:
                        to_drop.add(id(sig))
            else:
                for _cap, sig in entries[1:]:
                    to_drop.add(id(sig))

        result = {}
        for cap, signals in signals_by_cap.items():
            kept = [s for s in signals if id(s) not in to_drop]
            if kept:
                result[cap] = kept
        return result

    @classmethod
    def _resolve_authoritative_cap(cls, action: str) -> Optional[str]:
        if action in AUTHORITATIVE_CAPABILITY:
            return AUTHORITATIVE_CAPABILITY[action]
        for pattern, cap in _AUTHORITATIVE_PATTERNS:
            if pattern.match(action):
                return cap
        return None

    @classmethod
    def _within_capability_dedupe(cls, signals: List) -> List:
        present_actions = {sig.get("action", "") for sig in signals}
        imported_stems  = {
            m.group(1)
            for a in present_actions
            if (m := _IMPORTED_PATTERN.match(a))
        }

        seen_keys:   set = set()
        seen_global: set = set()
        result = []

        for sig in signals:
            action = sig.get("action", "")
            file_  = sig.get("file")

            if action in SEMANTIC_ALIASES and SEMANTIC_ALIASES[action] in present_actions:
                continue

            m = _DETECTED_PATTERN.match(action)
            if m and m.group(1) in imported_stems:
                continue

            if action in DEDUPE_BY_ACTION_ONLY:
                if action in seen_global:
                    continue
                seen_global.add(action)
                result.append(sig)
                continue

            key = (action, file_)
            if key not in seen_keys:
                seen_keys.add(key)
                result.append(sig)

        return result

    @classmethod
    def _compute_statistics(cls, signals_by_cap: Dict[str, List]) -> Dict:
        stats: Dict = {
            "total_signals": 0,
            "by_capability": {},
            "by_type": {"structural": 0, "behavioral": 0, "wiring": 0, "negative": 0},
        }
        for cap, signals in signals_by_cap.items():
            cap_counts = {"total": len(signals), "structural": 0, "behavioral": 0, "wiring": 0, "negative": 0}
            for sig in signals:
                t = sig.get("type", "structural")
                cap_counts[t] = cap_counts.get(t, 0) + 1
                stats["by_type"][t] = stats["by_type"].get(t, 0) + 1
            stats["by_capability"][cap] = cap_counts
            stats["total_signals"] += len(signals)
        return stats

    @classmethod
    def _empty_stats(cls) -> Dict:
        return {
            "total_signals": 0,
            "by_capability": {},
            "by_type": {"structural": 0, "behavioral": 0, "wiring": 0, "negative": 0},
        }




def recalculate_merged_aggregates(merged: Dict) -> Dict:
    """Recompute top-level signal counters from cleaned signals_by_capability."""
    sbc     = merged.get("signals_by_capability", {})
    total   = wiring = negative = 0
    for signals in sbc.values():
        for sig in signals:
            total += 1
            t = sig.get("type", "")
            if t == "wiring":    wiring   += 1
            elif t == "negative":negative += 1
    merged["total_signals"]         = total
    merged["total_wiring_signals"]  = wiring
    merged["total_negative_signals"]= negative
    return merged