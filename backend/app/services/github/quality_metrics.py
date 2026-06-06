import os
import re
from pathlib import Path
from typing import Dict, List
 
 
class QualityMetricsAnalyzer:
    """
    Extract factual quality signals from repository structure and files.
    Output: raw counts, booleans, file lists, framework names — never ratings.
    """
 
    TEST_PATTERNS = [
        r"\.test\.(js|jsx|ts|tsx)$",
        r"\.spec\.(js|jsx|ts|tsx)$",
        r"_test\.py$",
        r"test_.*\.py$",
        r"\.test\.java$",
        r"Test\.java$",
        r"\.test\.go$",
    ]
 
    TEST_DIRS = ["test/", "tests/", "__tests__/", "spec/", "specs/", "__test__/"]
 
    CICD_FILES = [
        "workflows", ".github", "gitlab-ci", "jenkins", "circleci",
        "travis", "azure-pipeline", "ci.yml", "cd.yml", "deploy.yml",
        "build.yml", "test.yml",
    ]
 
    TEST_FRAMEWORKS = {
        "jest":            ["jest", "jest.config", "@jest", "describe(", "test(", "it(",
                            "expect(", "beforeEach(", "afterEach(", "jest.fn", "jest.mock"],
        "mocha":           ["mocha", "mochajs", "chai"],
        "pytest":          ["pytest", "pytest.ini", "def test_", "@pytest", "import pytest"],
        "unittest":        ["unittest", "TestCase", "import unittest"],
        "junit":           ["@Test", "junit", "@BeforeEach", "@AfterEach"],
        "vitest":          ["vitest", "vitest.config", "vi."],
        "cypress":         ["cypress", "cy.visit", "cy.get", "cy.click"],
        "playwright":      ["playwright", "@playwright", "page."],
        "testing-library": ["@testing-library", "screen.", "fireEvent"],
        "supertest":       ["supertest", "request(app)"],
    }
 
    @staticmethod
    def analyze_testing(repo, file_tree: List[str]) -> Dict:
        print(f"   🔍 Scanning {len(file_tree)} files for test signals...")
 
        test_files        = []
        test_directories  = set()
        production_files  = []
 
        for file_path in file_tree:
            is_test = False
            for test_dir in QualityMetricsAnalyzer.TEST_DIRS:
                if test_dir in file_path.lower():
                    test_files.append(file_path)
                    test_directories.add(test_dir.rstrip("/"))
                    is_test = True
                    break
 
            if not is_test:
                for pattern in QualityMetricsAnalyzer.TEST_PATTERNS:
                    if re.search(pattern, file_path, re.IGNORECASE):
                        test_files.append(file_path)
                        is_test = True
                        break
 
            if not is_test and QualityMetricsAnalyzer._is_production_code(file_path):
                production_files.append(file_path)
 
        print(f"   📊 Test files: {len(test_files)}, Production files: {len(production_files)}")
 
        test_lines         = 0
        prod_lines         = 0
        detected_frameworks= set()
        only_happy_path    = True
        has_mock_usage     = False
        has_async_tests    = False
 
        for test_file in test_files[:50]:
            try:
                content       = repo.get_contents(test_file).decoded_content.decode("utf-8")
                content_lower = content.lower()
                test_lines   += len(content.splitlines())
 
                for framework, patterns in QualityMetricsAnalyzer.TEST_FRAMEWORKS.items():
                    if framework in detected_frameworks:
                        continue
                    for pat in patterns:
                        if pat.lower() in content_lower:
                            detected_frameworks.add(framework)
                            break
 
                if any(kw in content_lower for kw in ["status(4", "statuscode(4", ".tobe(4",
                                                        "error", "fail", "reject", "throw"]):
                    only_happy_path = False
 
                if any(kw in content_lower for kw in ["jest.mock", "vi.mock", "sinon", "stub", "spy"]):
                    has_mock_usage = True
 
                if "async" in content_lower and ("await" in content_lower or "done(" in content_lower):
                    has_async_tests = True
 
            except Exception as e:
                print(f"   ⚠️  Could not read {test_file}: {str(e)[:50]}")
 
        for prod_file in production_files[:100]:
            try:
                content     = repo.get_contents(prod_file).decoded_content.decode("utf-8")
                prod_lines += len(content.splitlines())
            except Exception:
                pass
 
        return {
            "test_files_count":       len(test_files),
            "production_files_count": len(production_files),
            "test_lines":             test_lines,
            "production_lines":       prod_lines,
            "test_to_code_ratio":     round((test_lines / prod_lines * 100) if prod_lines > 0 else 0.0, 1),
            "has_tests":              len(test_files) > 0,
            "only_happy_path_tested": only_happy_path,
            "has_mock_usage":         has_mock_usage,
            "has_async_tests":        has_async_tests,
            "test_directories":       list(test_directories),
            "testing_frameworks":     list(detected_frameworks),
            "sample_test_files":      test_files[:10],
        }
    
    @staticmethod
    def analyze_cicd(repo, file_tree: List[str]) -> Dict:
        cicd_files_found = []
        cicd_platforms   = []
 
        for file_path in file_tree:
            file_lower = file_path.lower()
            is_cicd    = any(pat.lower() in file_lower for pat in QualityMetricsAnalyzer.CICD_FILES)
 
            if not is_cicd and (file_lower.endswith(".yml") or file_lower.endswith(".yaml")):
                if any(folder in file_lower for folder in ["github", "gitlab", "circleci", "workflows"]):
                    is_cicd = True
 
            if is_cicd:
                cicd_files_found.append(file_path)
                if   "github"    in file_lower or "workflows" in file_lower: cicd_platforms.append("GitHub Actions")
                elif "gitlab"    in file_lower:                              cicd_platforms.append("GitLab CI")
                elif "jenkins"   in file_lower:                              cicd_platforms.append("Jenkins")
                elif "circleci"  in file_lower:                              cicd_platforms.append("CircleCI")
                elif "travis"    in file_lower:                              cicd_platforms.append("Travis CI")
                elif "azure"     in file_lower:                              cicd_platforms.append("Azure Pipelines")
 
        workflow_analysis = {}
        for cicd_file in cicd_files_found[:5]:
            try:
                content       = repo.get_contents(cicd_file).decoded_content.decode("utf-8")
                content_lower = content.lower()
                workflow_analysis[cicd_file] = {
                    "runs_tests":         any(kw in content_lower for kw in ["npm test","pytest","jest","yarn test","run: test","go test"]),
                    "runs_lint":          any(kw in content_lower for kw in ["lint","eslint","flake8","pylint","ruff"]),
                    "runs_build":         any(kw in content_lower for kw in ["npm run build","yarn build","make","cargo build","go build"]),
                    "runs_deploy":        any(kw in content_lower for kw in ["deploy","publish","release","push to","heroku","vercel","fly.io"]),
                    "uses_docker":        "docker"   in content_lower,
                    "uses_caching":       "cache"    in content_lower,
                    "uses_secrets":       "secrets." in content_lower,
                    "node_version_pinned":bool(re.search(r"node-version:\s*\d+", content)),
                }
            except Exception as e:
                print(f"   ⚠️  Could not analyze {cicd_file}: {str(e)[:50]}")
 
        any_wf = lambda key: any(w.get(key) for w in workflow_analysis.values())
 
        return {
            "has_cicd":           len(cicd_files_found) > 0,
            "cicd_files":         cicd_files_found,
            "cicd_platforms":     list(set(cicd_platforms)),
            "workflow_count":     len(cicd_files_found),
            "workflow_analysis":  workflow_analysis,
            "runs_tests_in_ci":   any_wf("runs_tests"),
            "runs_lint_in_ci":    any_wf("runs_lint"),
            "runs_build_in_ci":   any_wf("runs_build"),
            "runs_deploy_in_ci":  any_wf("runs_deploy"),
            "uses_docker_in_ci":  any_wf("uses_docker"),
            "uses_caching_in_ci": any_wf("uses_caching"),
            "uses_secrets_in_ci": any_wf("uses_secrets"),
        }
    
    @staticmethod
    def analyze_documentation(repo, file_tree: List[str]) -> Dict:
        doc_files = {
            "readme": None, "contributing": None, "license": None,
            "changelog": None, "code_of_conduct": None,
            "architecture_docs": [], "api_docs": [],
        }
 
        for file_path in file_tree:
            file_lower = file_path.lower()
            file_name  = os.path.basename(file_path).lower()
 
            if not doc_files["readme"] and "readme" in file_name:
                if file_name.endswith((".md", ".rst", ".txt")) or file_name == "readme":
                    doc_files["readme"] = file_path
            elif "contributing"  in file_lower:                                         doc_files["contributing"]   = file_path
            elif "license"       in file_lower or "licence" in file_lower:              doc_files["license"]        = file_path
            elif "changelog"     in file_lower:                                         doc_files["changelog"]      = file_path
            elif "code_of_conduct" in file_lower or "code-of-conduct" in file_lower:   doc_files["code_of_conduct"]= file_path
            elif "docs/" in file_lower and any(kw in file_lower for kw in ["architecture","design"]): doc_files["architecture_docs"].append(file_path)
            elif "docs/" in file_lower and any(kw in file_lower for kw in ["api","swagger","openapi"]): doc_files["api_docs"].append(file_path)
 
        readme_sections_present  = []
        readme_has_code_examples = False
        readme_has_images        = False
        readme_char_count        = 0
 
        if doc_files["readme"]:
            try:
                content       = repo.get_contents(doc_files["readme"]).decoded_content.decode("utf-8")
                content_lower = content.lower()
                readme_char_count = len(content)
 
                section_keywords = {
                    "installation":  ["install", "setup", "getting started"],
                    "usage":         ["usage", "how to use", "example"],
                    "api_reference": ["api", "endpoints", "reference"],
                    "contributing":  ["contribut", "development"],
                    "license":       ["license"],
                    "testing":       ["test", "testing"],
                    "configuration": ["config", "environment", ".env"],
                    "deployment":    ["deploy", "production", "heroku", "docker"],
                }
 
                for section, keywords in section_keywords.items():
                    if any(kw in content_lower for kw in keywords):
                        readme_sections_present.append(section)
 
                readme_has_code_examples = "```" in content
                readme_has_images        = "![" in content or "<img" in content
 
            except Exception as e:
                print(f"   ⚠️  Could not read README: {str(e)[:50]}")
 
        return {
            "has_readme":              doc_files["readme"]       is not None,
            "has_contributing_guide":  doc_files["contributing"] is not None,
            "has_license":             doc_files["license"]      is not None,
            "has_changelog":           doc_files["changelog"]    is not None,
            "has_architecture_docs":   len(doc_files["architecture_docs"]) > 0,
            "has_api_docs":            len(doc_files["api_docs"])           > 0,
            "readme_sections_present": readme_sections_present,
            "readme_has_code_examples":readme_has_code_examples,
            "readme_has_images":       readme_has_images,
            "readme_char_count":       readme_char_count,
            "documentation_files":     doc_files,
        }
    @staticmethod
    def _is_production_code(file_path: str) -> bool:
        code_extensions = {".py",".js",".jsx",".ts",".tsx",".java",".go",".rs",".rb",".php"}
        if Path(file_path).suffix.lower() not in code_extensions:
            return False
        return not any(p in file_path for p in ["node_modules/","dist/","build/",".next/","coverage/","vendor/","__pycache__/",".git/"])