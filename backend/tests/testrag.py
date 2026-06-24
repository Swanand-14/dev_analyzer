# tests/test_rag.py
#
# Manual test script for RAG ingestion + retrieval.
# Run directly: python tests/test_rag.py
#
# Tests:
#   1. Ingest a repo
#   2. Run targeted queries (auth, CI/CD, database, API)
#   3. Run holistic queries (architecture, system design)
#   4. Print results clearly so you can verify chunk quality visually

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from github import Github
from app.core.config import get_settings
from app.services.rag.ingestion import RepoIngestionPipeline
from app.services.rag.retriever import RAGRetriever

# ──────────────────────────────────────────────────────────────
# CONFIG — change these to your test repo
# ──────────────────────────────────────────────────────────────

TEST_REPO   = "Swanand-14/sample-vuln-repo"   # owner/repo shorthand
FORCE_REINGEST = True                  # set False to skip ingestion on re-runs

TARGETED_QUESTIONS = [
    "Where exactly is authentication implemented?",
    "How is JWT token verification done?",
    "Where are API routes defined?",
    "Show where CI/CD is configured.",
    "How is the database connection set up?",
    "Where is input validation happening?",
]

HOLISTIC_QUESTIONS = [
    "Does this developer seem to understand backend architecture?",
    "Is the project tutorial-based or genuinely engineered?",
    "Does this codebase show strong system design skills?",
]


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def print_result(i: int, result: dict) -> None:
    print(f"\n  [{i+1}] {result['file_path']}  |  {result['feature']}  |  {result['chunk_type']}"
          f"  |  score: {result['score']}"
          f"  |  high_priority: {result['is_high_priority']}")
    if result["function_names"]:
        print(f"       functions: {result['function_names']}")
    # Show first 300 chars of code so output stays readable
    code_preview = result["code"][:300].replace("\n", "\n       ")
    print(f"       code preview:\n       {code_preview}")
    if len(result["code"]) > 300:
        print(f"       ... ({len(result['code'])} chars total)")


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def main():
    settings = get_settings()

    if not settings.GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not set in .env")
        sys.exit(1)

    github_client = Github(settings.GITHUB_TOKEN)
    retriever     = RAGRetriever()

    # ── Step 1: Ingest ──────────────────────────────────────────
    print_section("STEP 1 — INGESTION")
    pipeline = RepoIngestionPipeline(github_client)
    result   = pipeline.ingest(TEST_REPO, force_refresh=FORCE_REINGEST)
    print(f"\n  Status:   {result['status']}")
    if result.get("chunks"):
        print(f"  Chunks:   {result['chunks']}")
        print(f"  Features: {result.get('features', [])}")

    if result["status"] not in ("success", "skipped"):
        print("❌ Ingestion failed — aborting tests")
        sys.exit(1)

    # ── Step 2: Targeted queries ─────────────────────────────────
    print_section("STEP 2 — TARGETED QUERIES")
    for question in TARGETED_QUESTIONS:
        print(f"\n❓ {question}")
        response = retriever.query(
            question  = question,
            repo_urls = [TEST_REPO],
            top_k     = 3,
            mode      = "targeted",
        )
        print(f"   Mode: {response['mode']}  |  Feature filter: {response['feature_filter']}")
        if not response["results"]:
            print("   ⚠️  No results returned")
        for i, r in enumerate(response["results"]):
            print_result(i, r)

    # ── Step 3: Holistic queries ─────────────────────────────────
    # print_section("STEP 3 — HOLISTIC QUERIES")
    # for question in HOLISTIC_QUESTIONS:
    #     print(f"\n❓ {question}")
    #     response = retriever.query(
    #         question  = question,
    #         repo_urls = [TEST_REPO],
    #         top_k     = 5,
    #         mode      = "holistic",
    #     )
    #     print(f"   Mode: {response['mode']}  |  Sampled {len(response['results'])} chunks across features")
    #     for i, r in enumerate(response["results"]):
    #         print_result(i, r)

    # ── Step 4: Auto-mode detection check ────────────────────────
    print_section("STEP 4 — AUTO MODE DETECTION")
    auto_questions = [
        ("Where is authentication implemented?",          "targeted"),
        ("Does this show strong system design skills?",   "holistic"),
        ("How does state management work?",               "holistic"),
        ("Show me the database schema.",                  "targeted"),
    ]
    all_passed = True
    for question, expected_mode in auto_questions:
        response = retriever.query(
            question  = question,
            repo_urls = [TEST_REPO],
            top_k     = 1,
            mode      = "auto",
        )
        detected = response["mode"]
        status   = "✅" if detected == expected_mode else "❌"
        if detected != expected_mode:
            all_passed = False
        print(f"  {status}  \"{question}\"")
        print(f"       expected={expected_mode}  detected={detected}")

    print(f"\n{'='*60}")
    print(f"  Auto-mode detection: {'ALL PASSED ✅' if all_passed else 'SOME FAILED ❌'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()