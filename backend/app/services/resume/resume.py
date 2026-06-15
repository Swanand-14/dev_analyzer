import io
import re
from typing import Dict, List, Optional
 
import google.generativeai as genai
 
from app.core.config import get_settings
 

 
_GITHUB_RE = re.compile(
    r'https?://github\.com/([a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38})'
    r'(?:/([a-zA-Z0-9_.-]+))?',
    re.IGNORECASE,
)
 
_LEETCODE_RE = re.compile(
    r'leetcode\.com/(?:u/)?([a-zA-Z0-9_-]{3,25})/?',
    re.IGNORECASE,
)
 
_CODEFORCES_RE = re.compile(
    r'codeforces\.com/profile/([a-zA-Z0-9_.-]{3,24})/?',
    re.IGNORECASE,
)
 
_EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
)
 
_GITHUB_SKIP = {
    'features', 'pricing', 'enterprise', 'marketplace', 'topics',
    'explore', 'collections', 'trending', 'sponsors', 'about',
    'orgs', 'apps', 'login', 'join', 'notifications', 'settings',
    'pulls', 'issues', 'actions', 'projects',
}
 
 

 
def _extract_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages  = [page.extract_text() for page in reader.pages if page.extract_text()]
        return "\n".join(pages)
    except ImportError:
        raise ImportError("pypdf not installed. Run: pip install pypdf")
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {e}")
 
 
def _regex_extract(text: str) -> Dict:
    result = {
        "github_username":   None,
        "leetcode_username": None,
        "codeforces_username": None,
        "repo_urls": [],
        "email":     None,
    }
 
    # GitHub
    github_matches   = _GITHUB_RE.findall(text)
    repo_urls:List[str] = []
    github_username  = None
 
    for username, repo in github_matches:
        if username.lower() in _GITHUB_SKIP:
            continue
        if not github_username:
            github_username = username
        if repo and repo not in ("", ".git"):
            full_url = f"https://github.com/{username}/{repo.rstrip('.git')}"
            if full_url not in repo_urls:
                repo_urls.append(full_url)
 
    result["github_username"] = github_username
    result["repo_urls"]       = repo_urls[:3]
 
    # LeetCode
    lc = _LEETCODE_RE.search(text)
    if lc and lc.group(1).lower() not in {"problems", "contest", "discuss", "explore"}:
        result["leetcode_username"] = lc.group(1)
 
    # Codeforces
    cf = _CODEFORCES_RE.search(text)
    if cf:
        result["codeforces_username"] = cf.group(1)
 
    # Email
    for email in _EMAIL_RE.findall(text):
        if not any(skip in email for skip in ["noreply", "example.com", "sentry.io"]):
            result["email"] = email.lower()
            break
 
    return result
 
 
def _extract_name_llm(text: str) -> Optional[str]:
    """Uses gemini-flash-lite to extract candidate name from resume header."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return None
 
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(
            "gemini-2.5-flash-lite",
            system_instruction=(
                "You are a resume parser. Extract only the candidate's full name. "
                "Return ONLY the name as plain text — no labels, no explanation. "
                "If you cannot find a name, return: UNKNOWN"
            ),
        )
        response = model.generate_content(
            f"Extract the candidate's full name:\n\n{text[:600].strip()}",
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                max_output_tokens=20,
            ),
        )
        name = response.text.strip()
        if not name or name.upper() == "UNKNOWN":
            return None
        if len(name) > 60 or len(name) < 2:
            return None
        if any(c in name for c in ["{", "}", "<", ">", "@"]):
            return None
        return name
 
    except Exception as e:
        print(f"   ⚠️  Resume name extraction failed: {e}")
        return None
 
 
def _compute_confidence(extracted: Dict) -> Dict:
    confidence = {}
    for field in ("github_username", "leetcode_username", "codeforces_username", "email"):
        confidence[field] = "high" if extracted.get(field) else "low"
    confidence["name"]      = "medium" if extracted.get("name") else "low"
    confidence["repo_urls"] = "high"   if extracted.get("repo_urls") else "low"
    return confidence
 
 

 
def extract_from_resume(pdf_bytes: bytes) -> Dict:
    """
    Extracts candidate fields from PDF bytes.
 
    Returns:
        {
          name, email, github_username, leetcode_username,
          codeforces_username, repo_urls, confidence,
          raw_text_length, error
        }
    """
    try:
        text = _extract_text(pdf_bytes)
    except Exception as e:
        return {
            "name": None, "email": None,
            "github_username": None, "leetcode_username": None,
            "codeforces_username": None, "repo_urls": [],
            "confidence": {}, "raw_text_length": 0,
            "error": str(e),
        }
 
    if not text.strip():
        return {
            "name": None, "email": None,
            "github_username": None, "leetcode_username": None,
            "codeforces_username": None, "repo_urls": [],
            "confidence": {}, "raw_text_length": 0,
            "error": "PDF appears to be scanned/image-only — no extractable text found",
        }
 
    extracted           = _regex_extract(text)
    extracted["name"]   = _extract_name_llm(text)
    extracted["confidence"]       = _compute_confidence(extracted)
    extracted["raw_text_length"]  = len(text)
    extracted["error"]            = None
 
    return extracted