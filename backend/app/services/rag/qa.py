import json
from typing import Any, Dict, List, Optional
 
import google.generativeai as genai
 
from app.services.rag.retriever import RAGRetriever

LOW_CONFIDENCE_THRESHOLD = 0.2   # below this → skip LLM, return raw chunks only
MAX_CHUNK_CHARS_TO_LLM   = 3000

_SYSTEM_PROMPT = """You are a code analysis assistant for a technical recruiting tool.
 
YOUR STRICT RULES:
- Only reference code that is explicitly present in the provided chunks.
- Never invent, infer, or assume anything not visible in the code.
- Never evaluate the developer's skill level or make hiring recommendations.
- Be factual and concise — recruiters scan, they don't read essays.
 
YOUR OUTPUT FORMAT (JSON only, no markdown):
{
  "core_snippet": "the most relevant code extracted verbatim from the chunks",
  "located_in":   "file path where the core snippet was found",
  "what_exists":  "1-2 sentences: what is actually implemented in the code",
  "what_missing": "1-2 sentences: what is absent or incomplete based only on what you can see"
}
 
If the chunks do not contain relevant code for the question, return:
{
  "core_snippet": "",
  "located_in":   "",
  "what_exists":  "No relevant code found in the retrieved chunks.",
  "what_missing": ""
}"""

def _build_prompt(question: str, chunks: List[Dict]) -> str:
    # Assemble chunks into a compact code block, capped to MAX_CHUNK_CHARS_TO_LLM
    code_blocks = []
    accumulated = 0
 
    for chunk in chunks:
        header = f"// FILE: {chunk['file_path']} [{chunk['chunk_type']}]\n"
        code   = chunk["code"]
        block  = header + code
 
        if accumulated + len(block) > MAX_CHUNK_CHARS_TO_LLM:
            remaining = MAX_CHUNK_CHARS_TO_LLM - accumulated
            if remaining > 200:
                code_blocks.append(block[:remaining] + "\n// ... truncated")
            break
 
        code_blocks.append(block)
        accumulated += len(block)
 
    code_section = "\n\n".join(code_blocks)
 
    return f"""QUESTION: {question}
 
RETRIEVED CODE CHUNKS:
{code_section}
 
Answer the question using ONLY the code above. Return JSON only."""

class RAGQueryEngine:
    """
    End-to-end RAG Q&A for targeted recruiter questions.
 
    Usage:
        engine = RAGQueryEngine(gemini_model)
        result = engine.ask(
            question  = "Where is authentication implemented?",
            repo_urls = ["Swanand-14/testrepo"],
        )
    """
 
    def __init__(self, gemini_model=None) -> None:
        # Accept an existing model or create one internally
        self._model = gemini_model
        self._retriever = RAGRetriever()
 
    def _get_model(self):
        if self._model is None:
            self._model = genai.GenerativeModel(
                "gemini-2.5-flash-lite",
                system_instruction=_SYSTEM_PROMPT,
            )
        return self._model
 
    def ask(
        self,
        question:       str,
        repo_urls:      List[str],
        top_k:          int = 4,
        feature_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves relevant chunks and optionally runs LLM extraction.
 
        Returns:
        {
            question:        str,
            feature_filter:  str | None,
            low_confidence:  bool,
            retrieved_chunks: [...],   # always returned
            answer:          { core_snippet, located_in, what_exists, what_missing }
                             | None    # None if low_confidence
        }
        """
        # Step 1- Retrieve
        retrieval = self._retriever.query(
            question       = question,
            repo_urls      = repo_urls,
            top_k          = top_k,
            mode           = "targeted",
            feature_filter = feature_filter,
        )
 
        chunks         = retrieval["results"]
        low_confidence = retrieval.get("low_confidence", False)
 
        base_response = {
            "question":        question,
            "feature_filter":  retrieval["feature_filter"],
            "low_confidence":  low_confidence,
            "retrieved_chunks":chunks,
            "answer":          None,
        }
 
        # Step 2 Skip LLM if low confidence 
        if low_confidence or not chunks:
            if low_confidence:
                print(f"   ⚠️  Low confidence retrieval — skipping LLM extraction")
            return base_response
 
        # Step 3- LLM extraction 
        try:
            prompt   = _build_prompt(question, chunks)
            model    = self._get_model()
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0,
                    max_output_tokens=800,
                ),
            )
 
            raw = response.text.strip()
 
            # Strip markdown fences if present
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
 
            answer = json.loads(raw)
 
            # Validate expected keys present
            for key in ("core_snippet", "located_in", "what_exists", "what_missing"):
                if key not in answer:
                    answer[key] = ""
 
            base_response["answer"] = answer
 
        except Exception as e:
            print(f"   ⚠️  RAG LLM extraction failed: {str(e)[:80]}")
            # Return retrieval results even if LLM fails
            base_response["answer"] = None
 
        return base_response