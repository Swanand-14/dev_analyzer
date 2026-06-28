# tests/test_rag.py
#
# Run: python tests/test_rag.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from github import Github
from app.core.config import get_settings
from app.services.rag.ingestion import RepoIngestionPipeline
from app.services.rag.qa import RAGQueryEngine

# ──────────────────────────────────────────────────────────────
TEST_REPO      = "Swanand-14/sample-vuln-repo"
FORCE_REINGEST = True   # True to re-index, False to reuse existing

QUESTIONS = [
    "Where exactly is authentication implemented?",
    "How is JWT token verification done?",
    
]
# ──────────────────────────────────────────────────────────────


def print_section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def print_answer(result):
    print(f"\n❓ {result['question']}")
    print(f"   feature_filter:  {result['feature_filter']}")
    print(f"   low_confidence:  {result['low_confidence']}")
    print(f"   chunks_retrieved:{len(result['retrieved_chunks'])}")

    for i, chunk in enumerate(result["retrieved_chunks"]):
        print(f"\n   chunk [{i+1}] {chunk['file_path']}"
              f" | score={chunk['score']}"
              f" | feature={chunk['feature']}"
              f" | type={chunk['chunk_type']}")

    answer = result.get("answer")
    if not answer:
        print("\n   ⚠️  No LLM answer (low confidence or LLM failed)")
        return

    print(f"\n   📍 located_in:   {answer['located_in']}")
    print(f"\n   ✅ what_exists:")
    print(f"      {answer['what_exists']}")
    print(f"\n   ❌ what_missing:")
    print(f"      {answer['what_missing']}")

    if answer["core_snippet"]:
        snippet = answer["core_snippet"][:400]
        print(f"\n   📝 core_snippet:")
        for line in snippet.splitlines():
            print(f"      {line}")
        if len(answer["core_snippet"]) > 400:
            print(f"      ... ({len(answer['core_snippet'])} chars total)")


def main():
    settings = get_settings()
    if not settings.GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not set"); sys.exit(1)

    github_client = Github(settings.GITHUB_TOKEN)
    engine        = RAGQueryEngine()

    # Step 1: Ingest
    print_section("STEP 1 — INGESTION")
    pipeline = RepoIngestionPipeline(github_client)
    result   = pipeline.ingest(TEST_REPO, force_refresh=FORCE_REINGEST)
    print(f"\n  status:   {result['status']}")
    if result.get("chunks"):
        print(f"  chunks:   {result['chunks']}")
        print(f"  features: {result.get('features', [])}")

    if result["status"] not in ("success", "skipped"):
        print("❌ Ingestion failed"); sys.exit(1)

    # Step 2: Ask questions
    print_section("STEP 2 — TARGETED Q&A")
    for question in QUESTIONS:
        result = engine.ask(question=question, repo_urls=[TEST_REPO], top_k=4)
        print_answer(result)
        print()


if __name__ == "__main__":
    main()