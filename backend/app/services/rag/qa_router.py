import json
from typing import Any, Dict, List, Optional
 
import google.generativeai as genai
 
from app.services.rag.tools import TOOL_DECLARATIONS, dispatch_tool_call
from app.services.rag.qa import RAGQueryEngine

_SEARCH_CODEBASE_TOOL = {
    "name": "search_codebase",
    "description": (
        "Searches the actual source code of the candidate's repository for a "
        "specific implementation detail. Use this when the recruiter asks WHERE "
        "or HOW something is implemented in the code — e.g. 'where is authentication "
        "implemented', 'how is the database connection set up', 'show me the API routes'. "
        "Do NOT use this for questions about tech stack, project type, or security posture — "
        "those have dedicated tools. Use this only when you need to look at actual code."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type":        "string",
                "description": "The implementation question to search code for.",
            }
        },
        "required": ["question"],
    },
}

ALL_TOOLS = TOOL_DECLARATIONS + [_SEARCH_CODEBASE_TOOL]

class QARouter:
    """
    Single entry point for recruiter Q&A.
 
    Usage:
        router = QARouter(db)
        result = router.ask(
            question    = "Where is authentication implemented?",
            analysis_id = "abc12345",
            repo_urls   = ["Swanand-14/testrepo"],
        )
    """
    def __init__(self, db, gemini_model_name: str = "gemini-2.5-flash-lite") -> None:
        self.db          = db
        self.model_name  = gemini_model_name
        self._model      = genai.GenerativeModel(gemini_model_name)
        self._rag_engine = RAGQueryEngine()
    
    def ask(
        self,
        question:    str,
        analysis_id: str,
        repo_urls:   List[str],
    ) -> Dict[str, Any]:
        """
        Routes a question through Gemini's tool-calling, executes whichever
        tool Gemini picks, and returns a final natural-language answer.
 
        Returns:
        {
            question:      str,
            tool_used:     str | None,   # None if Gemini answered directly
            tool_args:     dict | None,
            tool_result:   dict | None,  # raw tool output, for debugging
            answer:        str,
        }
        """
        prompt = (
            f"analysis_id is {analysis_id}. "
            f"repo_urls available are {repo_urls}. "
            f"{question}"
        )
 
        # ── Step 1: Let Gemini pick a tool (or answer directly) ───────
        response = self._model.generate_content(
            prompt,
            tools=[{"function_declarations": ALL_TOOLS}],
        )
 
        part = response.candidates[0].content.parts[0]
 
        # No tool call — Gemini answered directly (rare, but handle it)
        if not hasattr(part, "function_call") or not part.function_call or not part.function_call.name:
            return {
                "question":    question,
                "tool_used":   None,
                "tool_args":   None,
                "tool_result": None,
                "answer":      response.text.strip(),
            }
 
        fn_name = part.function_call.name
        fn_args = dict(part.function_call.args)
        if fn_name in {"extract_technologies", "get_repo_summary", "security_scan"}:
            # DB tools need analysis_id — inject if Gemini omitted it
            fn_args.setdefault("analysis_id", analysis_id)
 
            tool_result = dispatch_tool_call(self.db, fn_name, fn_args)
 
            final = self._model.generate_content([
                {"role": "user",  "parts": [{"text": prompt}]},
                {"role": "model", "parts": [{"function_call": {"name": fn_name, "args": fn_args}}]},
                {"role": "user",  "parts": [{"function_response": {"name": fn_name, "response": tool_result}}]},
            ])
            answer_text = self._safe_extract_text(final, fallback=tool_result)
 
            return {
                "question":    question,
                "tool_used":   fn_name,
                "tool_args":   fn_args,
                "tool_result": tool_result,
                "answer":      answer_text,
            }
        
        if fn_name == "search_codebase":
            rag_question = fn_args.get("question", question)
            rag_result   = self._rag_engine.ask(
                question  = rag_question,
                repo_urls = repo_urls,
                top_k     = 4,
            )
 
            # RAGQueryEngine already does its own LLM extraction internally —
            # its "answer" field (core_snippet/what_exists/what_missing) IS
            # the grounded result. We pass that back through one more Gemini
            # call to phrase it naturally for the recruiter, or use it directly
            # if low_confidence.
            if rag_result["low_confidence"] or not rag_result.get("answer"):
                return {
                    "question":    question,
                    "tool_used":   "search_codebase",
                    "tool_args":   {"question": rag_question},
                    "tool_result": rag_result,
                    "answer":      (
                        "I couldn't find sufficiently relevant code for this question "
                        "in the indexed repository."
                    ),
                }
 
            ans = rag_result["answer"]
            composed_answer = (
                f"{ans['what_exists']}\n\n"
                f"{ans['what_missing']}".strip()
            )
            if ans.get("located_in"):
                composed_answer += f"\n\n(Found in: {ans['located_in']})"
 
            return {
                "question":    question,
                "tool_used":   "search_codebase",
                "tool_args":   {"question": rag_question},
                "tool_result": rag_result,
                "answer":      composed_answer,
            }
        return {
            "question":    question,
            "tool_used":   fn_name,
            "tool_args":   fn_args,
            "tool_result": {"error": f"Unhandled tool: {fn_name}"},
            "answer":      "Something went wrong routing this question.",
        }
    
    @staticmethod
    def _safe_extract_text(response, fallback: Optional[Dict] = None) -> str:
        """
        Safely extracts text from a Gemini response.
 
        Gemini sometimes returns ANOTHER function_call instead of text
        (e.g. if it decides it needs more info). response.text crashes
        in that case. This checks for an actual text part first, and
        falls back to a plain-text rendering of the tool result if
        Gemini didn't produce text.
        """
        try:
            parts = response.candidates[0].content.parts
            text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
            if text_parts:
                return "".join(text_parts).strip()
        except (IndexError, AttributeError):
            pass
 
        # No text part — Gemini likely tried to chain another tool call.
        # Fall back to summarizing the tool result directly so the
        # caller still gets something useful instead of a crash.
        if fallback:
            return f"(Model did not return a text answer — raw data: {json.dumps(fallback, default=str)[:500]})"
        return "(No answer returned by the model.)"
        


