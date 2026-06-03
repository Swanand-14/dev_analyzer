import json
from datetime import datetime
from typing import Any, Dict, List, Optional
 
import requests

_PROFILE_QUERY = """
query getUserProfile($username: String!) {
    matchedUser(username: $username) {
        username
        profile {
            realName ranking reputation countryName
            company school skillTags aboutMe
        }
        submitStats {
            acSubmissionNum { difficulty count }
            totalSubmissionNum { difficulty count }
        }
        userCalendar {
            activeYears streak totalActiveDays submissionCalendar
        }
    }
}"""
 
_SKILLS_QUERY = """
query skillStats($username: String!) {
    matchedUser(username: $username) {
        tagProblemCounts {
            advanced     { tagName tagSlug problemsSolved }
            intermediate { tagName tagSlug problemsSolved }
            fundamental  { tagName tagSlug problemsSolved }
        }
    }
}"""
 
_LANGUAGE_QUERY = """
query languageStats($username: String!) {
    matchedUser(username: $username) {
        languageProblemCount { languageName problemsSolved }
    }
}"""
 
_BADGE_QUERY = """
query userBadges($username: String!) {
    matchedUser(username: $username) {
        badges { id displayName icon creationDate }
    }
}"""

class LeetCodeClient:
    """
    Fetches a LeetCode user's profile, stats, skills, languages, and badges
    via LeetCode's public GraphQL endpoint.
 
    All four queries run in sequence. If the user doesn't exist,
    returns {"error": "User not found"}.
    """
 
    GRAPHQL_URL = "https://leetcode.com/graphql"
    HEADERS     = {
        "Content-Type": "application/json",
        "User-Agent":   "Mozilla/5.0",
    }
    TIMEOUT = 10  # seconds per request
 
    # ──────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────
 
    @classmethod
    def fetch_user_data(cls, username: str) -> Dict[str, Any]:
        """
        Fetches all available data for a LeetCode user.
 
        Returns a structured dict on success:
            {
                username, profile, problem_stats,
                activity, languages, badges,
                skills_breakdown, fetched_at
            }
 
        Returns {"error": "..."} on failure.
        """
        try:
            profile_data  = cls._run_query(_PROFILE_QUERY,  username)
            skills_data   = cls._run_query(_SKILLS_QUERY,   username)
            language_data = cls._run_query(_LANGUAGE_QUERY, username)
            badge_data    = cls._run_query(_BADGE_QUERY,    username)
 
            # Validate user exists
            if not profile_data.get("data", {}).get("matchedUser"):
                return {"error": "User not found"}
 
            user = profile_data["data"]["matchedUser"]
 
            return {
                "username":        user["username"],
                "profile":         cls._parse_profile(user),
                "problem_stats":   cls._parse_problem_stats(user),
                "activity":        cls._parse_activity(user),
                "languages":       cls._parse_languages(language_data),
                "badges":          cls._parse_badges(badge_data),
                "skills_breakdown":cls._parse_skills(skills_data),
                "fetched_at":      datetime.utcnow().isoformat(),
            }
 
        except Exception as e:
            print(f"   ❌ LeetCode fetch error for {username}: {e}")
            return {"error": str(e)}
        
    @classmethod
    def _run_query(cls, query: str, username: str) -> Dict[str, Any]:
        """Executes a single GraphQL query and returns the JSON response."""
        response = requests.post(
            cls.GRAPHQL_URL,
            json={"query": query, "variables": {"username": username}},
            headers=cls.HEADERS,
            timeout=cls.TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    
    @staticmethod
    def _parse_profile(user: Dict) -> Dict[str, Any]:
        p = user.get("profile", {})
        return {
            "real_name":  p.get("realName"),
            "ranking":    p.get("ranking"),
            "reputation": p.get("reputation"),
            "country":    p.get("countryName"),
            "company":    p.get("company"),
            "school":     p.get("school"),
            "skills":     p.get("skillTags", []),
            "about":      p.get("aboutMe"),
        }
 
    @staticmethod
    def _parse_problem_stats(user: Dict) -> Dict[str, int]:
        ac_stats = {
            item["difficulty"]: item["count"]
            for item in user["submitStats"]["acSubmissionNum"]
        }
        return {
            "total_solved":  ac_stats.get("All",    0),
            "easy_solved":   ac_stats.get("Easy",   0),
            "medium_solved": ac_stats.get("Medium", 0),
            "hard_solved":   ac_stats.get("Hard",   0),
        }
 
    @staticmethod
    def _parse_activity(user: Dict) -> Dict[str, Any]:
        calendar = user.get("userCalendar", {})
 
        # Convert Unix timestamps → date strings for the submission calendar
        submission_calendar: Dict[str, int] = {}
        raw_calendar = calendar.get("submissionCalendar")
        if raw_calendar:
            for ts, count in json.loads(raw_calendar).items():
                date_str = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
                submission_calendar[date_str] = count
 
        return {
            "active_days":          calendar.get("totalActiveDays", 0),
            "streak":               calendar.get("streak",          0),
            "active_years":         calendar.get("activeYears",     []),
            "submission_calendar":  submission_calendar,
        }
 
    @staticmethod
    def _parse_languages(language_data: Dict) -> List[Dict[str, Any]]:
        raw = (
            language_data.get("data", {})
            .get("matchedUser", {})
            .get("languageProblemCount", [])
        )
        return [
            {"language": l["languageName"], "problems_solved": l["problemsSolved"]}
            for l in raw
        ]
 
    @staticmethod
    def _parse_badges(badge_data: Dict) -> List[Dict[str, Any]]:
        raw = (
            badge_data.get("data", {})
            .get("matchedUser", {})
            .get("badges", [])
        )
        return [
            {
                "name": b["displayName"],
                "date": b.get("creationDate"),
                "icon": b.get("icon"),
            }
            for b in raw
        ]
 
    @staticmethod
    def _parse_skills(skills_data: Dict) -> Dict[str, List[Dict]]:
        tag_counts = (
            skills_data.get("data", {})
            .get("matchedUser", {})
            .get("tagProblemCounts", {})
        )
 
        breakdown: Dict[str, List[Dict]] = {
            "advanced":     [],
            "intermediate": [],
            "fundamental":  [],
        }
 
        if not tag_counts:
            return breakdown
 
        for level in breakdown:
            breakdown[level] = sorted(
                [
                    {
                        "name":           s["tagName"],
                        "slug":           s["tagSlug"],
                        "problems_solved":s["problemsSolved"],
                    }
                    for s in tag_counts.get(level, [])
                    if s["problemsSolved"] > 0
                ],
                key=lambda x: x["problems_solved"],
                reverse=True,
            )
 
        return breakdown
 