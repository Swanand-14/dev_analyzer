import re
from typing import Dict, List, Literal, Optional
 
from app.services.rag.client import get_or_create_repo_collection, repo_collection_exists
from app.services.rag.embedder import embed_query

_FEATURE_KEYWORDS: Dict[str, List[str]] = {
    "authentication": [
        "auth", "login", "signup", "jwt", "token", "password",
        "session", "verify", "credential", "middleware",
    ],
    "database": [
        "database", "db", "query", "schema", "model", "mongodb",
        "mongoose", "prisma", "sql", "collection", "store",
    ],
    "api_routes": [
        "route", "endpoint", "api", "request", "response",
        "rest", "handler", "controller", "express",
    ],
    "ci_cd": [
        "ci", "cd", "pipeline", "workflow", "github actions",
        "deploy", "build", "lint", "test runner",
    ],
    "testing": [
        "test", "spec", "jest", "pytest", "assertion",
        "mock", "coverage", "unit test", "integration test",
    ],
    "configuration": [
        "config", "env", "environment", "setup", "settings",
        "dotenv", "variable",
    ],
    "validation": [
    "validate", "validation", "sanitize", "schema", "joi",
    "zod", "yup", "input", "required", "rules",
],
   }
 
# Queries that imply holistic reasoning — Mode B
_HOLISTIC_PATTERNS = [
    r"architecture",
    r"system design",
    r"overall",
    r"engineered|tutorial.based|copy.paste",
    r"understand.*(backend|frontend|fullstack)",
    r"skill|experience|senior|junior",
    r"code quality",
    r"project structure",
    r"how (is|does) .*(work|structured|organized)",
]
LOW_CONFIDENCE_THRESHOLD = 0.30
RetrievalMode = Literal["targeted", "holistic", "auto"]

def _detect_mode(query: str) -> RetrievalMode:
    """Auto-detects whether a query needs targeted or holistic retrieval."""
    q = query.lower()
    for pattern in _HOLISTIC_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return "holistic"
    return "targeted"

def _detect_feature_filter(query: str) -> Optional[str]:
    """
    Returns the most likely feature filter for a targeted query.
    Returns None if no clear feature match — query runs unfiltered.
    """
    q = query.lower()
    scores: Dict[str, int] = {}
    for feature, keywords in _FEATURE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q)
        if score > 0:
            scores[feature] = score
    if not scores:
        return None
    return max(scores, key=lambda f: scores[f])

class RAGRetriever:
    """
    Retrieves relevant code chunks from ChromaDB for recruiter questions.
 
    Usage:
        retriever = RAGRetriever()
        results   = retriever.query(
            question  = "Where is authentication implemented?",
            repo_urls = ["Swanand-14/testrepo"],
            top_k     = 5,
        )
    """
 
    DEFAULT_TOP_K = 5
 
    def query(
        self,
        question:  str,
        repo_urls: List[str],
        top_k:     int = DEFAULT_TOP_K,
        mode:      RetrievalMode = "auto",
        feature_filter: Optional[str] = None,
    ) -> Dict:
        """
        Retrieves relevant chunks for a question across one or more repos.
 
        Args:
            question:       Natural-language recruiter question
            repo_urls:      List of repo URLs to search (each has its own collection)
            top_k:          Number of results to return per repo
            mode:           "targeted" | "holistic" | "auto" (default: auto-detect)
            feature_filter: Override feature filter (e.g. "authentication") — auto-detected if None
 
        Returns:
            {
                question:      str,
                mode:          str,
                feature_filter: str | None,
                results:       [ { repo_url, file_path, feature, chunk_type,
                                   is_high_priority, code, score, function_names } ]
            }
        """
        if mode == "auto":
            mode = _detect_mode(question)
 
        if mode == "targeted" and feature_filter is None:
            feature_filter = _detect_feature_filter(question)
 
        all_results = []
 
        for repo_url in repo_urls:
            if not repo_collection_exists(repo_url):
                print(f"   ⚠️  No RAG index for {repo_url} — skipping")
                continue
 
            if mode == "targeted":
                chunks = self._targeted_search(repo_url, question, top_k, feature_filter)
            else:
                chunks = self._holistic_sample(repo_url, top_k)
 
            all_results.extend(chunks)
 
        # Sort all results by score descending (targeted) or by feature (holistic)
        if mode == "targeted":
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        
 
        final_results = all_results[:top_k * len(repo_urls)]
        low_confidence = (
            mode == "targeted"
            and bool(final_results)
            and all((c["score"] or 0) < LOW_CONFIDENCE_THRESHOLD for c in final_results)
        )

        return {
            "question":       question,
            "mode":           mode,
            "feature_filter": feature_filter,
            "low_confidence": low_confidence,   
            "results":        final_results,
        }
     
    def _targeted_search(
        self,
        repo_url:       str,
        question:       str,
        top_k:          int,
        feature_filter: Optional[str],
    ) -> List[Dict]:
        """
        Embeds the question, filters by feature if detected,
        then does vector similarity search within that subset.
        """
        collection    = get_or_create_repo_collection(repo_url)
        query_vector  = embed_query(question)
 
        where_filter  = {"feature": feature_filter} if feature_filter else None
 
        try:
            results = collection.query(
                query_embeddings = [query_vector],
                n_results        = top_k,
                where            = where_filter,
                include          = ["documents", "metadatas", "distances"],
            )
        except Exception as e:
            # If filtered query has fewer results than n_results, Chroma raises
            # Retry without filter
            print(f"   ⚠️  Filtered query failed ({e}) — retrying without filter")
            results = collection.query(
                query_embeddings = [query_vector],
                n_results        = min(top_k, collection.count()),
                include          = ["documents", "metadatas", "distances"],
            )
 
        chunks = self._format_results(results, repo_url, mode="targeted")

        

        return chunks
    

    def _holistic_sample(self, repo_url: str, top_k: int) -> List[Dict]:
        """
        Stratified sample — pulls the highest-priority chunk from each
        detected feature category. Gives LLM breadth across the codebase
        rather than depth on a single topic.
 
        Used for: "does this show strong architecture", "tutorial vs engineered", etc.
        """
        collection = get_or_create_repo_collection(repo_url)
 
        features = list(_FEATURE_KEYWORDS.keys()) + ["business_logic"]
        sampled  = []
 
        for feature in features:
            try:
                # Get best chunk per feature — prioritize high-priority files
                result = collection.get(
                    where   = {"feature": feature, "is_high_priority": "True"},
                    limit   = 1,
                    include = ["documents", "metadatas"],
                )
                if result["documents"]:
                    sampled.append(self._format_single(
                        result["documents"][0],
                        result["metadatas"][0],
                        repo_url,
                        score=None,
                    ))
                    continue
 
                # Fallback — any chunk for this feature
                result = collection.get(
                    where   = {"feature": feature},
                    limit   = 1,
                    include = ["documents", "metadatas"],
                )
                if result["documents"]:
                    sampled.append(self._format_single(
                        result["documents"][0],
                        result["metadatas"][0],
                        repo_url,
                        score=None,
                    ))
            except Exception:
                continue
 
        return sampled
    
    def _format_results(
        self, results: Dict, repo_url: str, mode: str
    ) -> List[Dict]:
        """Formats ChromaDB query results into clean dicts."""
        formatted = []
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
 
        for doc, meta, dist in zip(docs, metas, distances):
            
            score = round(1 - dist, 4) if dist is not None else None
            formatted.append(self._format_single(doc, meta, repo_url, score))
 
        return formatted
 
    @staticmethod
    def _format_single(
        doc: str, meta: Dict, repo_url: str, score: Optional[float]
    ) -> Dict:
        return {
            "repo_url":        repo_url,
            "file_path":       meta.get("file_path", ""),
            "feature":         meta.get("feature", ""),
            "chunk_type":      meta.get("chunk_type", ""),
            "language":        meta.get("language", ""),
            "is_high_priority":meta.get("is_high_priority", "False") == "True",
            "function_names":  meta.get("function_names", ""),
            "imports":         meta.get("imports", ""),
            "code":            doc,
            "score":           score,
        }
    

