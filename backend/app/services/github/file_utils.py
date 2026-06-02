import os
import re
from collections import defaultdict
from typing import Dict, List
 
from app.services.github.constants import (
    IGNORE_PATTERNS,
    BOILERPLATE_PATTERNS,
    HIGH_PRIORITY_PATTERNS,
    CICD_AND_CONFIG_PATTERNS,
    CODE_EXTENSIONS,
    IMPORTANT_FILES,
    FEATURE_PATTERNS,
)

def should_include_file(file_path: str) -> bool:
    """
    Returns True if the file is worth fetching and analyzing.
    Skips build artifacts, locks, media, and other noise.
    Always includes CI/CD configs and important root files.
    """
    file_lower = file_path.lower()
 
    # Hard excludes first — fastest exit
    for pattern in IGNORE_PATTERNS:
        if pattern.lower() in file_lower:
            return False
 
    # Always include important root files (readme, license, etc.)
    for name in IMPORTANT_FILES:
        if name in file_lower:
            return True
 
    # Always include CI/CD and config files
    for pattern in CICD_AND_CONFIG_PATTERNS:
        if pattern.lower() in file_lower:
            return True
 
    # Include by extension
    ext = os.path.splitext(file_path)[-1].lower()
    return ext in CODE_EXTENSIONS

def is_boilerplate(file_path: str) -> bool:
    """
    Returns True if the file is a pre-built UI component
    (Shadcn, Radix, Lucide) — not worth AI analysis.
    """
    file_lower = file_path.lower()
    return any(p.lower() in file_lower for p in BOILERPLATE_PATTERNS)

def is_high_priority(file_path:str) -> bool:
    file_lower = file_path.lower()
    return any(p.lower() in file_lower for p in HIGH_PRIORITY_PATTERNS)

def extract_code_metadata(code: str, file_path: str) -> Dict[str, List[str]]:
    """
    Extracts imports and function names from source code.
    Supports JS/TS (import/require) and Python (from X import).
    Used to score files into feature groups before chunking.
    """
    metadata: Dict[str, List[str]] = {"imports": [], "functions": []}
 
    import_patterns = [
        r'import\s+(?:\{[^}]+\}|[^\s]+)\s+from\s+[\'"]([^\'"]+)[\'"]',  # ES6 import
        r'const\s+\w+\s*=\s*require\([\'"]([^\'"]+)[\'"]\)',              # CommonJS require
        r'import\s+[\'"]([^\'"]+)[\'"]',                                   # side-effect import
        r'from\s+([a-zA-Z][^\s,;]+)\s+import',                            # Python from X import
    ]
    for pattern in import_patterns:
        metadata["imports"].extend(re.findall(pattern, code))
 
    func_patterns = [
        r"function\s+(\w+)",                        # function declaration
        r"const\s+(\w+)\s*=\s*(?:async\s+)?\(",    # arrow / const function
        r"export\s+(?:async\s+)?function\s+(\w+)",  # exported function
        r"def\s+(\w+)\(",                           # Python def
    ]
    for pattern in func_patterns:
        metadata["functions"].extend(re.findall(pattern, code))
 
    return metadata

def calculate_feature_score(
    file_path: str,
    code: str,
    metadata: Dict[str, List[str]],
) -> Dict[str, int]:
    """
    Scores a file against each feature group (authentication, database, etc.).
    Returns a dict of feature → score. Highest score wins during chunking.
 
    Boilerplate files are immediately assigned to ui_library (score 100)
    and skip all other checks.
    """
    scores: Dict[str, int] = defaultdict(int)
    file_lower = file_path.lower()
    code_lower = code.lower()
 
    # Short-circuit: boilerplate files always go to ui_library
    if is_boilerplate(file_path):
        scores["ui_library"] += 100
        return dict(scores)
 
    for feature, patterns in FEATURE_PATTERNS.items():
        base = 0
 
        # Path match — strong signal (weight 5)
        for path_pat in patterns["paths"]:
            if path_pat.lower() in file_lower:
                base += 5
 
        # Import match — medium signal (weight 3)
        for imp_pat in patterns.get("imports", []):
            if any(imp_pat.lower() in imp.lower() for imp in metadata["imports"]):
                base += 3
 
        # Keyword match — weak signal (weight 1)
        for kw in patterns.get("keywords", []):
            if kw.lower() in code_lower:
                base += 1
 
        scores[feature] = base * patterns.get("priority", 5)
 
    return dict(scores)
 

