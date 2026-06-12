import json
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
 
import google.generativeai as genai
 
from app.analysis.stage1.fact_extractors import (
    lean_activity_facts,
    lean_cicd_facts,
    lean_doc_facts,
    lean_security_facts,
    lean_testing_facts,
)
from app.analysis.stage1.prompt_builder import build_signal_extraction_prompt
from app.analysis.stage1.signal_validator import clean_signals, validate_signal
from app.services.github.chunker import ChunkingAnalyzer
from app.services.github.constants import FEATURE_TO_CAPABILITY, TECH_MAP
from app.services.github.rate_limiter import AdaptiveRateLimiter
from app.utils.signal_postprocessor import SignalPostprocessor

class RepoAnalysisPipeline:
    """
    Orchestrates Stage-1 signal extraction for a single GitHub repo.
 
    Steps:
      1. Chunk repo files by feature group (ChunkingAnalyzer)
      2. Extract facts — testing, CI/CD, security, activity, docs
      3. Send each chunk to Gemini for signal extraction
      4. Aggregate + deduplicate signals (SignalPostprocessor)
      5. Return structured fact + signal dict — no scoring
 
    Usage:
        pipeline = RepoAnalysisPipeline(gemini_model, rate_limiter, github_client)
        result   = pipeline.analyze_complete(repo_url)
    """
 
    def __init__(
        self,
        gemini_model,
        rate_limiter: AdaptiveRateLimiter,
        github_client,
    ) -> None:
        self.model        = gemini_model
        self.rate_limiter = rate_limiter
        self.github_client= github_client
        self.total_tokens = 0
 
    
 
    def analyze_complete(self, repo_url: str, jd_text: Optional[str] = None) -> Dict:
        """
        Runs the full Stage-1 pipeline for one repo.
        Returns a structured dict or raises on unrecoverable error.
        """
        
        from app.services.github.quality_metrics import QualityMetricsAnalyzer
        from app.services.github.security_analyzer import SecurityAnalyzer
        from app.services.github.activity_analyzer import GitHubActivityAnalyzer
 
        start = time.time()
        print(f"\n{'='*70}")
        print(f"🔬 STAGE-1 SIGNAL EXTRACTION: {repo_url}")
        print(f"{'='*70}")
 
        # Step 1 — chunk repo
        print("\n Step 1: Chunking files...")
        analyzer     = ChunkingAnalyzer(repo_url, self.github_client)
        chunk_result = analyzer.chunk_repo()
        file_tree    = analyzer.get_file_tree()
 
        # Step 2 — extract facts
        print("\n Step 2: Testing & CI/CD facts...")
        testing_facts = lean_testing_facts(QualityMetricsAnalyzer.analyze_testing(analyzer.repo, file_tree))
        cicd_facts    = lean_cicd_facts(QualityMetricsAnalyzer.analyze_cicd(analyzer.repo, file_tree))
        doc_facts     = lean_doc_facts(QualityMetricsAnalyzer.analyze_documentation(analyzer.repo, file_tree))
 
        print("\n🔒 Step 3: Security facts...")
        raw_security_facts = SecurityAnalyzer.analyze_security(analyzer.repo, file_tree)
        security_facts = lean_security_facts(raw_security_facts)

 
        print("\n Step 4: Activity facts...")
        activity_facts = lean_activity_facts(GitHubActivityAnalyzer.analyze_commit_patterns(analyzer.repo))
 
        # Step 3 — set rate limit based on repo size
        total_files = chunk_result["total_files"] + chunk_result["boilerplate_files"]
        self.rate_limiter.set_limit_based_on_files(total_files)
 
        # Step 4 — AI signal extraction
        print("\n Step 5: AI signal extraction...")
        features_analyzed = self._analyze_all_chunks(chunk_result["chunks"])
 
        # Step 5 — aggregate + deduplicate
        print("\n Step 6: Aggregating + cleaning signals...")
        signals_by_capability, signal_counts = self._aggregate_signals(
            features_analyzed, raw_security_facts
        )
        technologies = self._extract_technologies(features_analyzed)
        total_lines = sum(
            c.get("lines", 0)
            for f in features_analyzed
            for c in f.get("chunks", [])
        )
        # Step 6 — LLM project context
        print("\n Step 7: Building project context...")
        readme_content = self._fetch_readme(analyzer.repo, doc_facts)
        project_context = self._build_project_context_llm(
            readme_content, technologies, signals_by_capability,
            chunk_result, total_lines, activity_facts,
        )
 
        
 
        elapsed = int(time.time() - start)
        print(
            f"\n✅ STAGE-1 COMPLETE ({elapsed}s) | "
            f"Signals: {signal_counts['total']} "
            f"(wiring: {signal_counts['wiring']}, negative: {signal_counts['negative']}, behavioral: {signal_counts['behavioral']}, structural: {signal_counts['structural']}) | "
        )
 
        return {
            "repo_url":              repo_url,
            "repo_name":             chunk_result["repo_name"],
            "owner":                 chunk_result["owner"],
            "total_files":           chunk_result["total_files"],
            "total_lines":           total_lines,
            "total_tokens":          self.total_tokens,
            "project_context":       project_context,
            "technologies":          self._extract_technologies(features_analyzed),
            "signals_by_capability": signals_by_capability,
            "total_signals":         signal_counts["total"],
            "total_wiring_signals":  signal_counts["wiring"],
            "total_negative_signals":signal_counts["negative"],
            "total_behavioral_signals": signal_counts["behavioral"],
            "total_structural_signals": signal_counts["structural"],
            "testing_facts":         testing_facts,
            "cicd_facts":            cicd_facts,
            "documentation_facts":   doc_facts,
            "security_facts":        security_facts,
            "activity_facts":        activity_facts,
        }
    
    def _analyze_all_chunks(self, chunks_dict: Dict) -> List[Dict]:
        features_analyzed = []
        total_chunks = sum(len(v) for v in chunks_dict.values())
        processed    = 0
 
        for feature_name, chunks in chunks_dict.items():
            chunk_results = []
 
            for chunk in chunks:
                processed += 1
                print(f"   [{processed}/{total_chunks}] {chunk['name']}...")
 
                if chunk.get("is_boilerplate"):
                    chunk_results.append(self._boilerplate_chunk_result(chunk))
                    continue
 
                self.rate_limiter.wait_if_needed()
                try:
                    signals = self._extract_signals_from_chunk(chunk, feature_name)
                    chunk_results.append({
                        "files":   chunk["files"],
                        "lines":   chunk["total_lines"],
                        "signals": signals,
                    })
                except Exception as e:
                    print(f"   ⚠️  Chunk failed: {str(e)[:60]}")
                    chunk_results.append({
                        "files":   chunk["files"],
                        "lines":   chunk["total_lines"],
                        "signals": [],
                    })
 
            if chunk_results:
                features_analyzed.append({
                    "feature_name": feature_name,
                    "capability":   FEATURE_TO_CAPABILITY.get(feature_name, "configuration"),
                    "chunks":       chunk_results,
                })
 
        return features_analyzed
    
    def _extract_signals_from_chunk(self, chunk: Dict, feature_name: str) -> List[Dict]:
        """
        Sends one chunk to Gemini and returns cleaned signals.
        Retries once on failure, falls back to deterministic library detection.
        """
        prompt = build_signal_extraction_prompt(chunk, feature_name)
 
        for attempt in range(2):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=2000,
                    ),
                )
                self.total_tokens += response.usage_metadata.total_token_count
                content = response.text.strip()
 
                # Strip markdown fences if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
 
                # Extract JSON object
                first = content.find("{")
                last  = content.rfind("}")
                if first != -1 and last != -1:
                    content = content[first: last + 1]
 
                result = json.loads(content)
                if "signals" in result and isinstance(result["signals"], list):
                    return clean_signals(result["signals"], chunk["files"])
 
            except Exception as e:
                print(f"      ⚠️  Attempt {attempt + 1}: {str(e)[:60]}")
 
        return self._fallback_signals(chunk, feature_name)
    
    def _fallback_signals(self, chunk: Dict, feature_name: str) -> List[Dict]:
        """
        Deterministic fallback when Gemini fails.
        Scans code for known library names and emits structural signals.
        CI workflow files always emit wiring signals.
        """
        signals = []
        code    = chunk.get("code",  "").lower()
        files   = chunk.get("files", [])
 
        lib_signals = {
            "jsonwebtoken": ("authentication", "jwt_library_imported"),
            "bcrypt":       ("authentication", "bcrypt_library_imported"),
            "argon2":       ("authentication", "argon2_library_imported"),
            "next-auth":    ("authentication", "nextauth_library_imported"),
            "prisma":       ("database",       "prisma_orm_imported"),
            "mongoose":     ("database",       "mongoose_orm_imported"),
            "sequelize":    ("database",       "sequelize_orm_imported"),
            "express":      ("api",            "express_framework_imported"),
            "fastapi":      ("api",            "fastapi_framework_imported"),
            "jest":         ("testing",        "jest_framework_imported"),
            "vitest":       ("testing",        "vitest_framework_imported"),
            "pytest":       ("testing",        "pytest_framework_imported"),
            "helmet":       ("api",            "helmet_security_imported"),
            "zod":          ("api",            "zod_validation_imported"),
            "joi":          ("api",            "joi_validation_imported"),
        }
 
        for lib, (cap, action) in lib_signals.items():
            if lib in code:
                signals.append({
                    "capability": cap,
                    "type":       "structural",
                    "action":     action,
                    "evidence":   f"'{lib}' detected in code",
                    "file":       files[0] if files else None,
                })
 
        for file_ in files:
            if ".github/workflows" in file_:
                signals.append({
                    "capability": "ci_cd",
                    "type":       "wiring",
                    "action":     "ci_workflow_triggered",
                    "evidence":   f"GitHub Actions workflow: {file_}",
                    "file":       file_,
                })
                if "npm test" in code or "pytest" in code or "yarn test" in code:
                    signals.append({
                        "capability": "ci_cd", "type": "wiring",
                        "action":     "tests_run_in_ci",
                        "evidence":   "Test command found in CI workflow",
                        "file":       file_,
                    })
                if "lint" in code or "eslint" in code or "flake8" in code:
                    signals.append({
                        "capability": "ci_cd", "type": "wiring",
                        "action":     "lint_run_in_ci",
                        "evidence":   "Lint command found in CI workflow",
                        "file":       file_,
                    })
 
        return signals
    
    @staticmethod
    def _boilerplate_chunk_result(chunk: Dict) -> Dict:
        return {
            "files":   chunk["files"],
            "lines":   chunk["total_lines"],
            "signals": [{
                "capability": "configuration",
                "type":       "structural",
                "action":     "ui_component_library_present",
                "evidence":   f"{len(chunk['files'])} pre-built UI component files (Shadcn/Radix)",
                "file":       chunk["files"][0] if chunk["files"] else None,
            }],
        }
    
    def _aggregate_signals(
        self,
        features: List[Dict],
        security_facts: Dict,
    ) -> Tuple[Dict[str, List[Dict]], Dict[str, int]]:
        """
        Merges signals from all chunks + security scanner,
        then runs SignalPostprocessor to deduplicate and clean.
        """
        raw: Dict[str, List] = defaultdict(list)
 
        for feature in features:
            for chunk in feature.get("chunks", []):
                for signal in chunk.get("signals", []):
                    cap = signal.get("capability", "configuration")
                    raw[cap].append(signal)
 
        # Merge security scanner signals
        for sig in security_facts.get("security_signals", []):
            if validate_signal(sig):
                raw[sig.get("capability", "configuration")].append(sig)
 
        cleaned = SignalPostprocessor.clean(dict(raw))
        sbc     = cleaned["signals_by_capability"]
 
        total = wiring = negative = behavioural = structural =  0
        for signals in sbc.values():
            for sig in signals:
                total += 1
                t = sig.get("type", "")
                if t == "wiring":   wiring   += 1
                elif t == "negative": negative += 1
                elif t == "behavioral": behavioural += 1
                elif t == "structural": structural += 1
 
        return sbc, {"total": total, "wiring": wiring, "negative": negative, "behavioral": behavioural, "structural": structural}
    

    def _fetch_readme(self, repo, doc_facts: Dict) -> str:
        """Fetches README content. Returns empty string if not found."""
        readme_path = doc_facts.get("documentation_files", {}).get("readme")
        if not readme_path:
            return ""
        try:
            content = repo.get_contents(readme_path).decoded_content.decode("utf-8")
            # Cap at 1500 chars to keep prompt lean
            return content[:1500].strip()
        except Exception:
            return ""
 
    def _build_project_context_llm(
        self,
        readme: str,
        technologies: List[str],
        signals_by_capability: Dict,
        chunk_result: Dict,
        total_lines: int,
        activity_facts: Dict,
    ) -> Dict:
        """
        Asks Gemini to produce a 2-sentence project_type + project_summary
        from README, technologies, and capability signals.
        Falls back to a minimal static context on failure.
        """
        # Build a compact signals summary — capability names + signal count only
        signals_summary = ", ".join(
            f"{cap}({len(sigs)})"
            for cap, sigs in signals_by_capability.items()
            if sigs
        )
 
        # Shrink readme further if signals_summary is long
        readme_budget = 1200 if len(signals_summary) < 200 else 800
        readme_snippet = readme[:readme_budget] if readme else "No README found."
 
        prompt = f"""You are analyzing a software project.
 
README (truncated):
{readme_snippet}
 
Technologies: {', '.join(technologies) or 'unknown'}
Capabilities detected: {signals_summary or 'none'}
 
Return ONLY this JSON, no markdown:
{{
  "project_type": "",
  "project_summary": ""
}}
 
Rules:
- project_type: one short label (e.g. "REST API", "Full-Stack Web App", "CLI Tool")
- project_summary: maximum 2 sentences. What the software does and its major user-facing functionality.
- Do not evaluate quality. Do not mention the developer. Do not mention implementation details unless central to the product."""
 
        try:
            self.rate_limiter.wait_if_needed()
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=150,
                ),
            )
            self.total_tokens += response.usage_metadata.total_token_count
            content = response.text.strip()
 
            if "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
 
            first = content.find("{")
            last  = content.rfind("}")
            if first != -1 and last != -1:
                result = json.loads(content[first: last + 1])
                if result.get("project_type") and result.get("project_summary"):
                    return {
                        "project_type":    result["project_type"],
                        "project_summary": result["project_summary"],
                        "scale": {
                            "total_files":   chunk_result["total_files"],
                            "total_lines":   total_lines,
                            "total_commits": activity_facts.get("total_commits", 0),
                            "contributors":  len(activity_facts.get("top_contributors", [])),
                        },
                    }
        except Exception as e:
            print(f"   ⚠️  Project context LLM failed: {str(e)[:60]}")
 
        # Fallback — static context
        return {
            "project_type":    "Unknown",
            "project_summary": "Could not generate project summary.",
            "scale": {
                "total_files":   chunk_result["total_files"],
                "total_lines":   total_lines,
                "total_commits": activity_facts.get("total_commits", 0),
                "contributors":  len(activity_facts.get("top_contributors", [])),
            },
        }
    
    def _extract_technologies(features: List[Dict]) -> List[str]:
        techs: Set[str] = set()
 
        for feature in features:
            for chunk in feature.get("chunks", []):
                for signal in chunk.get("signals", []):
                    if signal.get("type") == "structural":
                        action   = signal.get("action",   "").lower()
                        evidence = signal.get("evidence", "").lower()
                        for pattern, tech_name in TECH_MAP.items():
                            if pattern in action or pattern in evidence:
                                techs.add(tech_name)
 
        return sorted(techs)