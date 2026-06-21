import re
from typing import Dict, List


class SecurityAnalyzer:
    """
    Extract factual security signals from repository code.
    Output: what EXISTS and what IS MISSING — never how good/bad it is.
    """

    SECURITY_LIBRARIES = {
        "input_validation": ["joi","yup","express-validator","validator","ajv","zod",
                             "pydantic","marshmallow","cerberus","voluptuous"],
        "authentication":   ["passport","jsonwebtoken","bcrypt","argon2","next-auth",
                             "@auth","pyjwt","passlib"],
        "security_headers": ["helmet","cors","csurf","flask-cors","django-cors-headers"],
        "sanitization":     ["xss","dompurify","sanitize-html","escape-html","bleach","html5lib"],
        "encryption":       ["crypto","bcrypt","argon2","jose","cryptography",
                             "pycryptodome","hashlib"],
    }

    MIDDLEWARE_WIRING_PATTERNS = [
        r"app\.use\s*\(",
        r"router\.use\s*\(",
        r"app\.all\s*\(",
        r"server\.use\s*\(",
    ]

    SQL_INJECTION_PATTERNS = [
        r'execute\s*\(\s*["\'].*\+.*["\']',
        r'SELECT.*FROM.*WHERE.*\+',
        r'\.raw\(',
        r'`[^`]*\$\{[^}]+\}[^`]*(?:SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)[^`]*`',
        r'(?:SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)[^`\n]*`[^`]*\$\{',
        r'f["\'](?:SELECT|INSERT|UPDATE|DELETE).*\{[^}]+\}',
        r'(?:query|sql|stmt)\s*=\s*`[^`]*\$\{',
    ]

    XSS_PATTERNS = [
        r'innerHTML\s*=',
        r'dangerouslySetInnerHTML',
        r'document\.write\(',
        r'eval\(',
        r'res\.send\(`.*\$\{',
        r'res\.send\(.*\+.*req\.',
    ]

    SECRET_PATTERNS = [
        r'(api[_-]?key|apikey)\s*=\s*["\'][^"\']{10,}["\']',
        r'(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']',
        r'(secret|token)\s*[=:]\s*["\'][^"\']{10,}["\']',
        r'(aws_access_key_id|aws_secret_access_key)',
        r'(private[_-]?key)\s*=\s*["\']',
        r'mongodb\+srv://[^:]+:[^@]+@',
        r'ghp_[a-zA-Z0-9]{36}',
        r'AIza[0-9A-Za-z_-]{35}',
        r'process\.env\.\w+\s*\|\|\s*["\'][^"\']{3,}["\']',
        r'os\.(?:getenv|environ\.get)\(["\'][^"\']+["\'],\s*["\'][^"\']{3,}["\']',
    ]

    @staticmethod
    def _is_middleware_actually_wired(content: str, middleware_keywords: List[str]) -> bool:
        """
        Returns True if one of the matched keywords (e.g. 'verifytoken') appears
        as an ARGUMENT inside either:
          1. Global mounting:  app.use(...) / router.use(...) / app.all(...)
          2. Inline per-route: router.post('/path', verifyToken, handler) —
             the more common real-world pattern where middleware is passed
             as a positional argument before the route handler.
        """
        wiring_call_pattern = re.compile(
            r"(?:app|router|server)\.(?:use|all|get|post|put|delete|patch)\s*\(([^)]*)\)",
            re.IGNORECASE,
        )
        for match in wiring_call_pattern.finditer(content):
            call_args = match.group(1).lower()
            if any(kw.lower() in call_args for kw in middleware_keywords):
                return True
        return False

    @staticmethod
    def analyze_security(repo, file_tree: List[str]) -> Dict:
        findings = {
            "libraries_detected": {
                "input_validation": [], "authentication": [],
                "security_headers": [], "sanitization": [], "encryption": [],
            },
            "vulnerability_patterns": {
                "sql_injection_risk": [], "xss_risk": [], "hardcoded_secrets": [],
            },
            "practices_detected": {
                "rate_limiting_present":         False,
                "rate_limiting_wired":           False,
                "csrf_protection_present":       False,
                "https_enforcement_present":     False,
                "parameterized_queries_present": False,
                "env_file_example_present":      False,
                "input_validation_present":      False,
                "auth_middleware_present":       False,
            },
            "security_signals": [],
        }

        env_examples = [f for f in file_tree if ".env" in f.lower() and "example" in f.lower()]
        if env_examples:
            findings["practices_detected"]["env_file_example_present"] = True
            findings["security_signals"].append({
                "capability": "configuration", "type": "structural",
                "action": "env_example_file_present",
                "evidence": f"Found: {env_examples[0]}", "file": env_examples[0],
            })

        security_relevant_files = [
            f for f in file_tree
            if any(kw in f.lower() for kw in ["auth","login","signup","password","api","route",
                                               "middleware","config","main","index","app","server"])
            and not any(skip in f.lower() for skip in ["node_modules","dist","build",".next","coverage"])
        ]

        for file_path in security_relevant_files[:40]:
            try:
                content       = repo.get_contents(file_path).decoded_content.decode("utf-8")
                content_lower = content.lower()

                # Library detection
                for category, libs in SecurityAnalyzer.SECURITY_LIBRARIES.items():
                    for lib in libs:
                        if lib in content_lower and lib not in findings["libraries_detected"][category]:
                            findings["libraries_detected"][category].append(lib)
                            findings["security_signals"].append({
                                "capability": "authentication" if category == "authentication" else "configuration",
                                "type": "structural",
                                "action": f"{lib.replace('-','_').replace('@','').replace('/','_')}_library_detected",
                                "evidence": f"'{lib}' found in imports/usage",
                                "file": file_path,
                            })

                # SQL injection
                for pattern in SecurityAnalyzer.SQL_INJECTION_PATTERNS:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        entry = {"file": file_path, "match_count": len(matches)}
                        if entry not in findings["vulnerability_patterns"]["sql_injection_risk"]:
                            findings["vulnerability_patterns"]["sql_injection_risk"].append(entry)
                            sample = matches[0][:100] if isinstance(matches[0], str) else str(matches[0])[:100]
                            findings["security_signals"].append({
                                "capability": "database", "type": "negative",
                                "action": "sql_injection_risk",
                                "evidence": f"User input interpolated into SQL string: {sample}",
                                "file": file_path,
                            })
                        break

                # XSS
                for pattern in SecurityAnalyzer.XSS_PATTERNS:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        sample = matches[0][:80] if isinstance(matches[0], str) else str(matches[0])[:80]
                        findings["vulnerability_patterns"]["xss_risk"].append({
                            "file": file_path, "pattern": pattern,
                            "match_count": len(matches), "sample": sample,
                        })
                        findings["security_signals"].append({
                            "capability": "api", "type": "negative",
                            "action": "xss_risk_unsanitized_output",
                            "evidence": f"Unsanitized output: {sample}", "file": file_path,
                        })

                # Hardcoded secrets
                is_example = "example" in file_path.lower() or "sample" in file_path.lower()
                if not is_example:
                    for pattern in SecurityAnalyzer.SECRET_PATTERNS:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        if matches:
                            if not any(e["file"] == file_path for e in findings["vulnerability_patterns"]["hardcoded_secrets"]):
                                findings["vulnerability_patterns"]["hardcoded_secrets"].append(
                                    {"file": file_path, "type": "potential_hardcoded_secret"}
                                )
                                sample = matches[0][:100] if isinstance(matches[0], str) else str(matches[0])[:100]
                                findings["security_signals"].append({
                                    "capability": "authentication", "type": "negative",
                                    "action": "hardcoded_secret_detected",
                                    "evidence": f"Hardcoded secret or insecure fallback: {sample}",
                                    "file": file_path,
                                })
                            break

                
                pd = findings["practices_detected"]
                ss = findings["security_signals"]

                
                if any(kw in content_lower for kw in ["rate-limit","ratelimit","express-rate"]):
                    if not pd["rate_limiting_present"]:
                        pd["rate_limiting_present"] = True
                        ss.append({"capability":"api","type":"structural","action":"rate_limiting_library_detected","evidence":"Rate limiting library usage detected","file":file_path})
                    if not pd["rate_limiting_wired"] and any(re.search(p, content) for p in SecurityAnalyzer.MIDDLEWARE_WIRING_PATTERNS):
                        pd["rate_limiting_wired"] = True
                        ss.append({"capability":"api","type":"wiring","action":"rate_limiting_applied","evidence":"Rate limiting middleware wired into request pipeline","file":file_path})

                if not pd["csrf_protection_present"] and any(kw in content_lower for kw in ["csrf","csurf"]):
                    pd["csrf_protection_present"] = True
                    ss.append({"capability":"api","type":"wiring","action":"csrf_protection_applied","evidence":"CSRF protection detected","file":file_path})

                if not pd["parameterized_queries_present"] and any(kw in content for kw in ["$1","$2","prepare(","bind(","parameterized"]):
                    pd["parameterized_queries_present"] = True
                    ss.append({"capability":"database","type":"behavioral","action":"parameterized_query_used","evidence":"Parameterized query syntax detected","file":file_path})

                if not pd["input_validation_present"] and any(kw in content_lower for kw in [".validate(","schema.parse(","validator(","joi.object"]):
                    pd["input_validation_present"] = True
                    ss.append({"capability":"api","type":"behavioral","action":"input_validation_applied","evidence":"Schema/validator usage detected in request handling","file":file_path})

                if not pd["auth_middleware_present"] and any(kw in content_lower for kw in ["authmiddleware","requireauth","isauthenticated","verifytoken","protect","authenticate"]):
                    if SecurityAnalyzer._is_middleware_actually_wired(
                        content,
                        ["authmiddleware","requireauth","isauthenticated","verifytoken","protect","authenticate"],
                    ):
                        pd["auth_middleware_present"] = True
                        ss.append({"capability":"authentication","type":"wiring","action":"auth_middleware_applied_to_route","evidence":"Auth middleware wired into route handler","file":file_path})

            except Exception:
                pass

        
        pd = findings["practices_detected"]
        ss = findings["security_signals"]

        if pd["rate_limiting_present"] and not pd["rate_limiting_wired"]:
            ss.append({"capability":"api","type":"negative","action":"rate_limiting_not_wired","evidence":"Rate limiting library detected but no middleware wiring found","file":None})
        elif not pd["rate_limiting_present"]:
            ss.append({"capability":"api","type":"negative","action":"rate_limiting_not_detected","evidence":"No rate limiting library or middleware found in any file","file":None})

        if not pd["input_validation_present"] and not findings["libraries_detected"]["input_validation"]:
            ss.append({"capability":"api","type":"negative","action":"no_input_validation_detected","evidence":"No joi, zod, pydantic, or express-validator usage found","file":None})

        if not pd["auth_middleware_present"] and findings["libraries_detected"]["authentication"]:
            ss.append({"capability":"authentication","type":"negative","action":"auth_middleware_not_wired","evidence":"Auth library present but no middleware wiring detected on routes","file":None})

        if not pd["env_file_example_present"]:
            ss.append({"capability":"configuration","type":"negative","action":"no_env_example_file","evidence":"No .env.example file found","file":None})

        return findings