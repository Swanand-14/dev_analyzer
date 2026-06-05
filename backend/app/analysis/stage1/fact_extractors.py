#Each function strips noise and normalises the shape so Stage-2

from typing import Any, Dict, List


def lean_testing_facts(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts testing facts from QualityMetricsAnalyzer output.
    Keeps: presence, file count, ratio, frameworks, mock usage.
    """
    return {
        "has_tests":              raw.get("has_tests",              False),
        "test_files_count":       raw.get("test_files_count",       0),
        "test_to_code_ratio":     raw.get("test_to_code_ratio",     0.0),
        "only_happy_path_tested": raw.get("only_happy_path_tested", True),
        "has_mock_usage":         raw.get("has_mock_usage",         False),
        "has_async_tests":        raw.get("has_async_tests",        False),
        "testing_frameworks":     raw.get("testing_frameworks",     []),
        "test_directories":       raw.get("test_directories",       []),
    }


def lean_cicd_facts(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts CI/CD facts from QualityMetricsAnalyzer output.
    Keeps: presence, platforms, what runs in CI.
    """
    return {
        "has_cicd":          raw.get("has_cicd",          False),
        "cicd_platforms":    raw.get("cicd_platforms",    []),
        "runs_tests_in_ci":  raw.get("runs_tests_in_ci",  False),
        "runs_lint_in_ci":   raw.get("runs_lint_in_ci",   False),
        "runs_build_in_ci":  raw.get("runs_build_in_ci",  False),
        "runs_deploy_in_ci": raw.get("runs_deploy_in_ci", False),
        "uses_docker_in_ci": raw.get("uses_docker_in_ci", False),
    }


def lean_doc_facts(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts documentation facts from QualityMetricsAnalyzer output.
    Keeps: readme presence, sections, contributing guide, license.
    """
    return {
        "has_readme":              raw.get("has_readme",              False),
        "has_contributing_guide":  raw.get("has_contributing_guide",  False),
        "has_license":             raw.get("has_license",             False),
        "has_changelog":           raw.get("has_changelog",           False),
        "readme_sections_present": raw.get("readme_sections_present", []),
        "readme_has_code_examples":raw.get("readme_has_code_examples",False),
    }


def lean_security_facts(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts security facts from SecurityAnalyzer output.
    Keeps: libraries detected, practices present.
    Drops raw signal lists — those go through the signal pipeline.
    """
    libs      = raw.get("libraries_detected", {})
    practices = raw.get("practices_detected",  {})

    return {
        "auth_libraries":                libs.get("authentication",    []),
        "validation_libraries":          libs.get("input_validation",  []),
        "sanitization_libraries":        libs.get("sanitization",      []),
        "rate_limiting_present":         practices.get("rate_limiting_present",         False),
        "csrf_protection_present":       practices.get("csrf_protection_present",       False),
        "input_validation_present":      practices.get("input_validation_present",      False),
        "auth_middleware_present":       practices.get("auth_middleware_present",       False),
        "env_file_example_present":      practices.get("env_file_example_present",      False),
        "parameterized_queries_present": practices.get("parameterized_queries_present", False),
    }


def lean_activity_facts(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts activity facts from GitHubActivityAnalyzer output.
    Keeps: commit count, streaks, working pattern, contributors.
    """
    streak     = raw.get("streak",          {})
    date_range = raw.get("date_range",      {})
    wp         = raw.get("working_pattern", {})

    return {
        "total_commits":          raw.get("total_commits_analyzed", 0),
        "active_days":            raw.get("active_days",            0),
        "days_since_last_commit": date_range.get("days_since_last_commit", 0) if date_range else 0,
        "current_streak":         streak.get("current", 0),
        "longest_streak":         streak.get("longest", 0),
        "consistency_score":      raw.get("consistency_score",      0),
        "working_pattern_type":   wp.get("type", "Unknown"),
        "active_years":           raw.get("active_years",           []),
        "top_contributors":       list(raw.get("author_contributions", {}).keys())[:3],
    }