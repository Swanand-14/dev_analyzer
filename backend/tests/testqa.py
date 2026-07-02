# tests/test_qa_router.py

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
    # "What tech stack does this developer know?",
    # "What kind of project is this?",
    # "How are passwords stored?",
    # "Where exactly is authentication implemented?",
    # "How is JWT token verification done in the code?",
    # "Show me where the database connection is configured.",
    "What backend technologies does this developer know, and where is authentication actually used in the code?",
]
# ──────────────────────────────────────────────────────────────


def print_section(title: str) -> None:
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def print_result(result: dict) -> None:
    print(f"\n❓ {result['question']}")

    tools = result.get("tools_called", [])
    if tools:
        for t in tools:
            print(f"   🔧 tool:   {t['name']}")
            print(f"   📥 args:   {json.dumps(t['args'], default=str)}")
            preview = json.dumps(t['result'], default=str)
            if len(preview) > 300:
                preview = preview[:300] + "..."
            print(f"   📤 result: {preview}")
    else:
        print(f"   🔧 tool:   none (direct answer)")

    print(f"\n   💬 answer:")
    for line in result["answer"].splitlines():
        print(f"      {line}")


def main():
    settings = get_settings()

    if not settings.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set in .env")
        sys.exit(1)

    db = connect_db()
    genai.configure(api_key=settings.GEMINI_API_KEY)

    router = QARouter(db)

    print_section(f"UNIFIED Q&A ROUTER TEST — analysis_id: {FIXED_ANALYSIS_ID}")
    print(f"  repo_urls: {TEST_REPO_URLS}")

    all_results = []
    tool_usage_count: dict = {}

    for question in QUESTIONS:
        result = router.ask(
            question    = question,
            analysis_id = FIXED_ANALYSIS_ID,
            repo_urls   = TEST_REPO_URLS,
        )
        all_results.append(result)
        print_result(result)

    print_section("ROUTING SUMMARY")
    for result in all_results:
        tools = result.get("tools_called", [])
        if tools:
            for t in tools:
                name = t["name"]
                tool_usage_count[name] = tool_usage_count.get(name, 0) + 1
        else:
            tool_usage_count["direct_answer"] = tool_usage_count.get("direct_answer", 0) + 1

    for tool, count in tool_usage_count.items():
        print(f"  {tool}: {count} question(s)")

    print(f"\n{'='*70}\n  Done\n{'='*70}\n")


if __name__ == "__main__":
    main()