import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
 
from dotenv import load_dotenv
load_dotenv()
 
import google.generativeai as genai
from app.core.config import get_settings
from app.db.mongo import connect_db
from app.services.rag.tools import TOOL_DECLARATIONS, dispatch_tool_call
 
# ──────────────────────────────────────────────────────────────
# CONFIG — set your fixed analysis_id here
FIXED_ANALYSIS_ID = "50ad758a"
 
QUESTIONS = [
    "What tech stack does this developer know?",
    "What kind of project is this?",
    "What frameworks and libraries are used in this codebase?",
    "Give me a summary of what this project does.",
]
# ──────────────────────────────────────────────────────────────
 
 
def print_section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")
 
 
def run_tool_call(model, db, question: str) -> None:
    print(f"\n❓ {question}")
 
    # Step 1 — ask Gemini, let it choose a tool
    response = model.generate_content(
        f"analysis_id is {FIXED_ANALYSIS_ID}. {question}",
        tools=[{"function_declarations": TOOL_DECLARATIONS}],
    )
 
    # Step 2 — check if Gemini made a function call
    part = response.candidates[0].content.parts[0]
 
    if not hasattr(part, "function_call") or not part.function_call:
        # Gemini answered directly without calling a tool
        print(f"   (no tool call — direct answer)")
        print(f"   {response.text}")
        return
 
    fn_name = part.function_call.name
    fn_args = dict(part.function_call.args)
    print(f"   🔧 tool called: {fn_name}")
    print(f"   📥 args:        {json.dumps(fn_args, indent=6)}")
 
    # Step 3 — execute the tool
    tool_result = dispatch_tool_call(db, fn_name, fn_args)
    print(f"   📤 result:")
    print(json.dumps(tool_result, indent=6, default=str))
 
    # Step 4 — send result back to Gemini for final natural-language answer
    final = model.generate_content([
        {"role": "user",  "parts": [{"text": f"analysis_id is {FIXED_ANALYSIS_ID}. {question}"}]},
        {"role": "model", "parts": [{"function_call": {"name": fn_name, "args": fn_args}}]},
        {"role": "user",  "parts": [{"function_response": {"name": fn_name, "response": tool_result}}]},
    ])
 
    print(f"\n   💬 Gemini answer:")
    print(f"   {final.text.strip()}")
 
 
def main():
    settings = get_settings()
 
    if FIXED_ANALYSIS_ID == "YOUR_ANALYSIS_ID_HERE":
        print("❌ Set FIXED_ANALYSIS_ID in test_tools.py before running")
        sys.exit(1)
 
    if not settings.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set in .env")
        sys.exit(1)
 
    # Connect to MongoDB
    db = connect_db()
 
    # Init Gemini
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
 
    print_section("TOOL CALLING TESTS")
    print(f"  analysis_id: {FIXED_ANALYSIS_ID}")
 
    for question in QUESTIONS:
        run_tool_call(model, db, question)
 
    print(f"\n{'='*60}")
    print("  Done")
    print(f"{'='*60}\n")
 
 
if __name__ == "__main__":
    main()
 