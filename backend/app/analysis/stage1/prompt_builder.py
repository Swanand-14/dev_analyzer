# app/analysis/stage1/prompt_builder.py
#
# Builds the Gemini prompt for signal extraction from a code chunk.


from typing import Dict

from app.services.github.constants import FEATURE_TO_CAPABILITY


def build_signal_extraction_prompt(chunk: Dict, feature_name: str) -> str:
    """
    Builds the full prompt string for a single code chunk.

    Args:
        chunk:        chunk dict from ChunkingAnalyzer (has 'files', 'code')
        feature_name: feature group name (authentication, database, etc.)

    Returns:
        Complete prompt string ready to send to Gemini.
    """
    capability = FEATURE_TO_CAPABILITY.get(feature_name, "configuration")

    file_list = "\n".join(f"  - {f}" for f in chunk["files"][:10])
    if len(chunk["files"]) > 10:
        file_list += f"\n  ... and {len(chunk['files']) - 10} more"

    return f"""You are a STATIC CODE SIGNAL EXTRACTOR for a developer skill assessment pipeline.

YOUR CONTRACT:
  - Extract factual, evidence-backed signals from the code below.
  - Do NOT score, judge, or recommend anything.
  - Every signal must be directly observable in the provided code.

━━━ CAPABILITY CONTEXT ━━━
Primary capability: {capability}
Files in this chunk ({len(chunk['files'])} total):
{file_list}

━━━ CODE ━━━
{chunk['code'][:4500]}

━━━ SIGNAL TYPE DEFINITIONS ━━━
structural  = a library/module/config EXISTS (import, require, class declaration)
behavioral  = a function IS CALLED or executes logic (hash call, query execution, token sign)
wiring      = something is CONNECTED to the runtime flow (middleware applied to app/router,
              route mounted, CI job triggered, workflow step runs)
negative    = an expected security/quality behaviour is PROVABLY ABSENT in this code

━━━ CAPABILITY ENUM — use exactly one ━━━
authentication | ci_cd | database | testing | api | configuration

━━━ WHAT NOT TO EMIT ━━━
Do NOT emit signals for:
- Standard boilerplate every app has: const app = express(), module.exports, app.listen(),
  const PORT = 3000, const router = express.Router(), require('./routes')
- README or comment content — only emit from executable code
- Duplicate signals for the same fact (e.g. two signals for the same import)
- Generic "file exists" signals unless it's a CI workflow (which counts as wiring)

━━━ NEGATIVE SIGNAL RULES — you MUST emit these when observed ━━━
1. Library imported but critical method never called:
   jwt required but jwt.verify() absent → jwt_verify_never_called

2. Secret/key with hardcoded fallback value:
   process.env.JWT_SECRET || 'secret'  → hardcoded_secret_fallback
   NOTE: the || 'literal' part IS the problem, not the env var part.

3. User input interpolated directly into a SQL string — ANY syntax:
   `SELECT ... WHERE id = ${{userId}}`   → sql_injection_risk  (template literal)
   "SELECT ... WHERE id = " + userId    → sql_injection_risk  (concatenation)
   f"SELECT ... WHERE id = {{user_id}}" → sql_injection_risk  (Python f-string)

4. User input returned/rendered without sanitization:
   res.send(`<div>${{bio}}</div>`)       → xss_risk_unsanitized_output

5. Route defined with no auth middleware applied before it:
   router.post('/profile', async (req,res) => {{...}})  — no verifyToken/auth before it
   → auth_check_missing_on_route   evidence: "POST /profile has no auth middleware"

6. No rate limiting library anywhere in the file set:
   → rate_limiting_not_detected  (emit once, file: null)

7. No input validation library (joi/zod/express-validator/pydantic) in the file set:
   → no_input_validation_detected  (emit once, file: null)

━━━ CI/CD WIRING SIGNALS — for ci_cd capability chunks ━━━
When you see a CI workflow file, emit wiring signals for each step present:
   on: [push, pull_request]  → ci_workflow_triggered
   run: npm test / pytest    → tests_run_in_ci
   run: npm run lint / flake8 → lint_run_in_ci
   run: npm run build        → build_run_in_ci
   deploy / publish step     → deploy_run_in_ci
   node-version: 20          → node_version_pinned
   uses: actions/cache       → dependency_caching_enabled

━━━ OUTPUT FORMAT — return ONLY this JSON, no markdown fences ━━━
{{
  "signals": [
    {{
      "capability": "authentication",
      "type": "structural",
      "action": "jwt_library_imported",
      "evidence": "const jwt = require('jsonwebtoken')",
      "file": "src/auth.js"
    }}
  ]
}}

━━━ WORKED EXAMPLES ━━━

✅ structural — library exists:
   action: "bcrypt_library_imported"
   evidence: "const bcrypt = require('bcrypt')"

✅ behavioral — function executes:
   action: "password_hashed_with_bcrypt"
   evidence: "await bcrypt.hash(password, 12)"

✅ wiring — connected to runtime flow:
   action: "helmet_middleware_applied"
   evidence: "app.use(helmet())"

✅ wiring — CI step:
   action: "tests_run_in_ci"
   evidence: "run: npm test"

✅ negative — jwt.verify absent:
   action: "jwt_verify_never_called"
   evidence: "jwt required and jwt.sign called, but jwt.verify not found anywhere"

✅ negative — hardcoded fallback secret:
   action: "hardcoded_secret_fallback"
   evidence: "process.env.JWT_SECRET || 'secret' — literal fallback makes env var useless"

✅ negative — template literal SQL injection:
   action: "sql_injection_risk"
   evidence: "INSERT INTO users VALUES ('${{username}}') — username interpolated without parameterization"

✅ negative — route missing auth:
   action: "auth_check_missing_on_route"
   evidence: "POST /profile route has no auth middleware before handler"

❌ WRONG — boilerplate, not a signal:
   action: "express_app_declared"  evidence: "const app = express()"

❌ WRONG — import is structural not wiring:
   type: "wiring"  action: "jwt_imported"

❌ WRONG — reading from README, not code:
   action: "jwt_secret_environment_variable_documented"

❌ WRONG — judgment, not observation:
   evidence: "Well-structured authentication implementation"

Be thorough. Negative signals matter as much as positive ones."""