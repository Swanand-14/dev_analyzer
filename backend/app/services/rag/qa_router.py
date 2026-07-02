import json
from typing import Any, Dict, List, Optional
 
import google.generativeai as genai
 
from app.services.rag.tools import TOOL_DECLARATIONS, dispatch_tool_call
from app.services.rag.qa import RAGQueryEngine

# Safety cap — prevents infinite loops if model keeps calling tools
MAX_TOOL_ROUNDS = 5

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
 
        # Conversation history — grows as tools are called
        messages = [
            {"role": "user", "parts": [{"text": prompt}]}
        ]

        tools_called: List[Dict] = []
        rounds = 0

        while True:
            rounds += 1
            if rounds > MAX_TOOL_ROUNDS:
                return {
                    "question":    question,
                    "tools_called":tools_called,
                    "answer":      f"(Stopped after {MAX_TOOL_ROUNDS} tool rounds without a final answer.)",
                }
 
            # Ask model 
            response = self._model.generate_content(
                messages,
                tools=[{"function_declarations": ALL_TOOLS}],
            )
 
            # Check what the model returned
            parts = response.candidates[0].content.parts
 
            # Collect text parts if any
            text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
 
            # Collect function calls if any
            fn_calls = [
                p.function_call for p in parts
                if hasattr(p, "function_call") and p.function_call and p.function_call.name
            ]
 
            # Model returned text → done 
            if text_parts and not fn_calls:
                return {
                    "question":    question,
                    "tools_called":tools_called,
                    "answer":      "".join(text_parts).strip(),
                }
 
            #  No function calls and no text → something went wrong 
            if not fn_calls:
                return {
                    "question":    question,
                    "tools_called":tools_called,
                    "answer":      "(Model returned no text and no tool call.)",
                }
 
            # Execute all function calls in this round 
            # Add model's response to conversation history
            messages.append({
                "role":  "model",
                "parts": [{"function_call": {"name": fc.name, "args": dict(fc.args)}} for fc in fn_calls],
            })
 
            # Execute each tool and collect results
            fn_responses = []
            for fc in fn_calls:
                fn_name = fc.name
                fn_args = dict(fc.args)
                fn_args.setdefault("analysis_id", analysis_id)
 
                tool_result = self._execute_tool(fn_name, fn_args, repo_urls)
 
                tools_called.append({
                    "name":   fn_name,
                    "args":   fn_args,
                    "result": tool_result,
                })
 
                fn_responses.append({
                    "function_response": {
                        "name":     fn_name,
                        "response": tool_result,
                    }
                })
 
            # Add all tool results to conversation history
            messages.append({
                "role":  "user",
                "parts": fn_responses,
            })
 
            # Loop — model will now see tool results and either
            # call more tools or give a final text answer

    def _execute_tool(
        self,
        fn_name:   str,
        fn_args:   Dict,
        repo_urls: List[str],
    ) -> Dict:
        """Dispatches to the correct tool implementation."""
 
        # DB tools
        if fn_name in {"extract_technologies", "get_repo_summary", "security_scan"}:
            return dispatch_tool_call(self.db, fn_name, fn_args)
 
        # RAG search
        if fn_name == "search_codebase":
            question   = fn_args.get("question", "")
            rag_result = self._rag_engine.ask(
                question  = question,
                repo_urls = repo_urls,
                top_k     = 4,
            )
 
            if rag_result["low_confidence"] or not rag_result.get("answer"):
                return {
                    "found":   False,
                    "message": "No sufficiently relevant code found for this question.",
                }
 
            ans = rag_result["answer"]
            return {
                "found":        True,
                "located_in":   ans.get("located_in", ""),
                "core_snippet": ans.get("core_snippet", ""),
                "what_exists":  ans.get("what_exists", ""),
                "what_missing": ans.get("what_missing", ""),
            }
        return {"error": f"Unknown tool: {fn_name}"}
    
    
        


