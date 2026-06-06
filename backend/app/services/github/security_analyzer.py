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

    