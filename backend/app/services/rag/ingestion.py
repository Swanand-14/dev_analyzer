import os
import re
import uuid
from typing import Dict, List, Optional, Tuple
 
from github import Github
from github.Repository import Repository
 
from app.services.github.file_utils import (
    should_include_file,
    is_boilerplate,
    is_high_priority,
    extract_code_metadata,
    calculate_feature_score,
)
from app.services.rag.client import (
    get_or_create_repo_collection,
    delete_repo_collection,
)
from app.services.rag.embedder import embed_texts


MAX_CHUNK_CHARS = 6_000
SPLITTABLE_LANGUAGES = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rs", ".rb", ".php",
}
def _detect_language(file_path: str) -> str:
    ext = os.path.splitext(file_path)[-1].lower()
    return ext if ext else "unknown"

_SPLIT_PATTERNS = [
    # Python: def / async def / class at column 0
    re.compile(r"^(?:async\s+)?def\s+\w+|^class\s+\w+", re.MULTILINE),
    # JS/TS: function / async function / class / arrow function assigned to const/let
    re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+\w+|^(?:export\s+)?class\s+\w+|^(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\(", re.MULTILINE),
    # Generic: anything that looks like a top-level named block
    re.compile(r"^(?:public|private|protected|static)?\s*(?:async\s+)?(?:function|def|class|func|fn)\s+\w+", re.MULTILINE),
]

def _split_into_logical_chunks(content: str, language: str) -> List[Tuple[str, str]]:
    """
    Splits file content into (chunk_type, chunk_code) pairs.
 
    Strategy:
      1. Find all function/class start positions via regex
      2. Slice content between consecutive starts
      3. If a slice exceeds MAX_CHUNK_CHARS, split further by line count
      4. Files with no detected boundaries → single "whole_file" chunk
 
    Returns list of (chunk_type, code) tuples.
    chunk_type: "function" | "class" | "whole_file"
    """
    if language not in SPLITTABLE_LANGUAGES:
        return [("whole_file", content)]
 
    # Find all boundary positions
    boundaries = []
    for pattern in _SPLIT_PATTERNS:
        for match in pattern.finditer(content):
            start = match.start()
            # Determine type from the matched text
            matched = match.group(0).strip()
            if "class" in matched:
                chunk_type = "class"
            else:
                chunk_type = "function"
            boundaries.append((start, chunk_type))
    if not boundaries:
        return [("whole_file", content)]
    boundaries.sort(key=lambda x: x[0])
    deduplicated = [boundaries[0]]
    for pos, ctype in boundaries[1:]:
        if pos - deduplicated[-1][0] > 10:  # ignore matches within 10 chars
            deduplicated.append((pos, ctype))

    chunks = []
    for i, (start, ctype) in enumerate(deduplicated):
        end = deduplicated[i + 1][0] if i + 1 < len(deduplicated) else len(content)
        chunk_code = content[start:end].strip()
 
        if not chunk_code:
            continue
 
        # If chunk is too large, split by lines into sub-chunks
        if len(chunk_code) > MAX_CHUNK_CHARS:
            lines = chunk_code.splitlines(keepends=True)
            sub = []
            accumulated = 0
            for line in lines:
                if accumulated + len(line) > MAX_CHUNK_CHARS and sub:
                    chunks.append((ctype, "".join(sub).strip()))
                    sub = []
                    accumulated = 0
                sub.append(line)
                accumulated += len(line)
            if sub:
                chunks.append((ctype, "".join(sub).strip()))
        else:
            chunks.append((ctype, chunk_code))
 
    return chunks if chunks else [("whole_file", content)]


class RepoIngestionPipeline:
    EMBED_BATCH_SIZE = 32
 
    def __init__(self, github_client: Github) -> None:
        if not github_client:
            raise ValueError("GitHub client required — check GITHUB_TOKEN in .env")
        self.github_client = github_client

    def ingest(self, repo_url: str, force_refresh: bool = False) -> Dict:
         """
        Ingests a GitHub repo into ChromaDB.
 
        If force_refresh=True, deletes the existing collection first.
        If force_refresh=False and collection already exists, skips ingestion.
 
        Returns summary dict with chunk counts and status.
        """
         from app.services.rag.client import repo_collection_exists
         print(f"\n RAG INGESTION: {repo_url}")
         if not force_refresh and repo_collection_exists(repo_url):
            print(f"  Already indexed — skipping (use force_refresh=True to re-index)")
            return {"status": "skipped", "repo_url": repo_url}
         if force_refresh:
            delete_repo_collection(repo_url)
 
        # Fetch repo
         repo, branch = self._connect(repo_url)
         print("   📂 Fetching files and building chunks...")
         all_chunks = self._build_chunks(repo, branch, repo_url)
 
         if not all_chunks:
            print("  No chunks produced — repo may be empty or all files filtered")
            return {"status": "empty", "repo_url": repo_url, "chunks": 0}
         
         print(f"   Embedding {len(all_chunks)} chunks...")
         self._embed_and_store(all_chunks, repo_url)
 
         print(f"   Ingestion complete — {len(all_chunks)} chunks stored")
         return {
             "status":       "success",
             "repo_url":     repo_url,
             "chunks":       len(all_chunks),
             "features":     list({c["metadata"]["feature"] for c in all_chunks}),
         }
    def _connect(self, repo_url: str) -> Tuple[Repository, str]:
        """Connects to repo and detects default branch."""
        if "github.com" in repo_url:
            parts = repo_url.rstrip("/").split("/")
            full_name = f"{parts[-2]}/{parts[-1]}"
        else:
            full_name = repo_url
 
        repo   = self.github_client.get_repo(full_name)
        branch = repo.default_branch
        return repo, branch
    
    def _build_chunks(
        self, repo: Repository, branch: str, repo_url: str
    ) -> List[Dict]:
        """
        Walks the repo file tree and builds embeddable chunks.
        Returns list of chunk dicts ready for embedding + storage.
        """
        # Fetch file tree
        sha  = repo.get_branch(branch).commit.sha
        tree = repo.get_git_tree(sha=sha, recursive=True).tree
        files = [
            item.path for item in tree
            if item.type == "blob"
            and should_include_file(item.path)
            and not is_boilerplate(item.path)
        ]
        print(f" {len(files)} files to process")
 
        all_chunks = []
 
        for file_path in files:
            try:
                content  = repo.get_contents(file_path, ref=branch).decoded_content.decode("utf-8")
                language = _detect_language(file_path)
                metadata = extract_code_metadata(content, file_path)
                scores   = calculate_feature_score(file_path, content, metadata)
                feature  = max(scores.items(), key=lambda x: x[1])[0] if scores else "business_logic"
                priority = is_high_priority(file_path)
 
                logical_chunks = _split_into_logical_chunks(content, language)
 
                for chunk_type, chunk_code in logical_chunks:
                    if len(chunk_code.strip()) < 30:
                        continue  # skip trivial fragments
 
                    chunk_id = str(uuid.uuid4())
 
                    all_chunks.append({
                        "id":       chunk_id,
                        "document": chunk_code,
                        "metadata": {
                            "repo_url":        repo_url,
                            "file_path":       file_path,
                            "language":        language,
                            "feature":         feature,
                            "is_high_priority":str(priority),  # Chroma metadata must be str/int/float/bool
                            "chunk_type":      chunk_type,
                            "imports":         ", ".join(metadata["imports"][:20]),
                            "function_names":  ", ".join(metadata["functions"][:20]),
                        },
                    })
 
            except Exception as e:
                print(f" Skipped {file_path}: {str(e)[:60]}")
 
        return all_chunks
    
    def _embed_and_store(self, chunks: List[Dict], repo_url: str) -> None:
        """
        Embeds chunks in batches and stores in the repo's Chroma collection.
        """
        collection = get_or_create_repo_collection(repo_url)
 
        for i in range(0, len(chunks), self.EMBED_BATCH_SIZE):
            batch      = chunks[i: i + self.EMBED_BATCH_SIZE]
            texts      = [c["document"] for c in batch]
            embeddings = embed_texts(texts)
 
            collection.add(
                ids        = [c["id"]       for c in batch],
                embeddings = embeddings,
                documents  = texts,
                metadatas  = [c["metadata"] for c in batch],
            )
 
            print(f"   ✓ Stored batch {i // self.EMBED_BATCH_SIZE + 1}"
                  f"/{-(-len(chunks) // self.EMBED_BATCH_SIZE)}"
                  f" ({len(batch)} chunks)")
         