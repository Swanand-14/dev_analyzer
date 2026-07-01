# tests/test_qa_router.py
#
# Unified test pipeline — runs ALL question types through ONE router.
# Tests both DB-tool questions and codebase-search questions in a single pass,
# letting Gemini decide the path for each.
#
# Run: python tests/test_qa_router.py
#
# Requires:
#   1. FIXED_ANALYSIS_ID set below (run /analyze once to get this)
#   2. RAG already ingested for the test repo (run test_rag.py once with
#      FORCE_REINGEST=True if you haven't indexed yet)

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai
from app.core.config import get_settings
from app.db.mongo import connect_db
from app.services.rag.qa_router import QARouter

# ──────────────────────────────────────────────────────────────
FIXED_ANALYSIS_ID = "50ad758a"
TEST_REPO_URLS    = ["Swanand-14/sample-vuln-repo"]

QUESTIONS = [
    # ── Expect: DB tool — extract_technologies ──────────────────
    "What tech stack does this developer know?",

    # ── Expect: DB tool — get_repo_summary ──────────────────────
    "What kind of project is this?",

    # ── Expect: DB tool — security_scan ─────────────────────────
    
    "How are passwords stored?",

    # ── Expect: search_codebase (RAG) ───────────────────────────
    "Where exactly is authentication implemented?",
    "How is JWT token verification done in the code?",
    "Show me where the database connection is configured.",
]
# ──────────────────────────────────────────────────────────────


def print_section(title: str) -> None:
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def print_result(result: dict) -> None:
    print(f"\n❓ {result['question']}")
    print(f"   🔧 tool_used: {result['tool_used']}")

    if result["tool_args"]:
        print(f"   📥 args:      {json.dumps(result['tool_args'], default=str)}")

    if result["tool_result"]:
        preview = json.dumps(result["tool_result"], default=str)
        if len(preview) > 300:
            preview = preview[:300] + "... (truncated)"
        print(f"   📤 raw result: {preview}")

    print(f"\n   💬 answer:")
    for line in result["answer"].splitlines():
        print(f"      {line}")


def main():
    settings = get_settings()

    if FIXED_ANALYSIS_ID == "YOUR_ANALYSIS_ID_HERE":
        print("❌ Set FIXED_ANALYSIS_ID in test_qa_router.py before running")
        sys.exit(1)

    if not settings.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set in .env")
        sys.exit(1)

    db = connect_db()
    genai.configure(api_key=settings.GEMINI_API_KEY)

    router = QARouter(db)

    print_section(f"UNIFIED Q&A ROUTER TEST — analysis_id: {FIXED_ANALYSIS_ID}")
    print(f"  repo_urls: {TEST_REPO_URLS}")

    tool_usage_count: dict = {}

    for question in QUESTIONS:
        result = router.ask(
            question    = question,
            analysis_id = FIXED_ANALYSIS_ID,
            repo_urls   = TEST_REPO_URLS,
        )
        print_result(result)

        tool = result["tool_used"] or "direct_answer"
        tool_usage_count[tool] = tool_usage_count.get(tool, 0) + 1

    print_section("ROUTING SUMMARY")
    for tool, count in tool_usage_count.items():
        print(f"  {tool}: {count} question(s)")

    print(f"\n{'='*70}\n  Done\n{'='*70}\n")


if __name__ == "__main__":
    main()