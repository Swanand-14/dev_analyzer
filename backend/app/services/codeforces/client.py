import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional
 
import requests

class CodeforcesClient:
    """
    Fetches profile, submissions, and rating history for a Codeforces user.
 
    Returns structured factual data or {"error": "..."} on failure.
    """
 
    BASE_URL = "https://codeforces.com/api"
    TIMEOUT  = 15
 
    # Problem rating tier boundaries — used for difficulty bucketing
    RATING_TIERS = {
        "Beginner":             (0,    1199),
        "Pupil":                (1200, 1399),
        "Specialist":           (1400, 1599),
        "Expert":               (1600, 1899),
        "Candidate Master":     (1900, 2099),
        "Master":               (2100, 2299),
        "International Master": (2300, 2399),
        "Grandmaster":          (2400, float("inf")),
    }
 
    # ──────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────
 
    @classmethod
    def fetch_user_data(cls, username: str) -> Dict[str, Any]:
        """
        Fetches all available data for a Codeforces user.
 
        Returns:
            {
                username, profile, problem_analysis,
                difficulty_distribution, rating_progression,
                recency_analysis, skill_assessment, fetched_at
            }
 
        Returns {"error": "..."} on failure.
        """
        try:
            user_data        = cls._get("user.info",   {"handles": username})
            submissions_data = cls._get("user.status", {"handle": username, "from": 1, "count": 10000})
            rating_data      = cls._get("user.rating", {"handle": username})
 
            if user_data["status"] != "OK":
                return {"error": "User not found"}
 
            user             = user_data["result"][0]
            problem_analysis = cls._analyze_submissions(submissions_data)
            difficulty_dist  = cls._analyze_difficulty(problem_analysis["problems"])
            rating_prog      = cls._analyze_rating_progression(rating_data, user)
            recency          = cls._analyze_recency(submissions_data, rating_data)
            skill_assessment = cls._assess_skills(problem_analysis, difficulty_dist)
 
            return {
                "username":              user["handle"],
                "profile":               cls._parse_profile(user),
                "problem_analysis":      problem_analysis,
                "difficulty_distribution": difficulty_dist,
                "rating_progression":    rating_prog,
                "recency_analysis":      recency,
                "skill_assessment":      skill_assessment,
                "fetched_at":            datetime.utcnow().isoformat(),
            }
 
        except Exception as e:
            print(f"   ❌ Codeforces fetch error for {username}: {e}")
            return {"error": str(e)}
        
    @classmethod
    def _get(cls, endpoint: str, params: Dict) -> Dict:
        response = requests.get(
            f"{cls.BASE_URL}/{endpoint}",
            params=params,
            timeout=cls.TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    
    @staticmethod
    def _parse_profile(user: Dict) -> Dict[str, Any]:
        return {
            "rank":         user.get("rank"),
            "max_rank":     user.get("maxRank"),
            "rating":       user.get("rating"),
            "max_rating":   user.get("maxRating"),
            "country":      user.get("country"),
            "organization": user.get("organization"),
            "contribution": user.get("contribution"),
            "friend_count": user.get("friendOfCount", 0),
        }
    
    def _analyze_submissions(submissions_data: Dict) -> Dict[str, Any]:
        """
        Parses all submissions. Counts unique AC problems, tags, languages.
        All dict keys are strings for MongoDB compatibility.
        """
        if submissions_data["status"] != "OK":
            return {
                "problems": [], "total_unique_solved": 0,
                "total_submissions": 0, "tags": {},
                "languages": {}, "rating_distribution": {},
                "acceptance_rate": 0,
            }
 
        submissions  = submissions_data["result"]
        problems     = []
        problem_tags = Counter()
        languages    = Counter()
        seen         = set()
 
        for sub in submissions:
            problem    = sub["problem"]
            problem_id = f"{problem['contestId']}{problem['index']}"
            languages[sub["programmingLanguage"]] += 1
 
            if sub["verdict"] == "OK" and problem_id not in seen:
                seen.add(problem_id)
                problems.append({
                    "id":         problem_id,
                    "name":       problem.get("name"),
                    "rating":     problem.get("rating"),
                    "tags":       problem.get("tags", []),
                    "contest_id": problem["contestId"],
                    "index":      problem["index"],
                })
                for tag in problem.get("tags", []):
                    problem_tags[tag] += 1
 
        # Rating distribution — string keys for MongoDB
        rating_dist: Dict[str, int] = defaultdict(int)
        for prob in problems:
            if prob.get("rating"):
                bucket = str((prob["rating"] // 100) * 100)
                rating_dist[bucket] += 1
 
        return {
            "problems":            problems,
            "total_unique_solved": len(problems),
            "total_submissions":   len(submissions),
            "tags":                dict(problem_tags.most_common(20)),
            "languages":           dict(languages.most_common(5)),
            "rating_distribution": dict(sorted(rating_dist.items())),
            "acceptance_rate":     round(len(problems) / len(submissions) * 100, 1) if submissions else 0,
        }
    
    @classmethod
    def _analyze_difficulty(cls, problems: List[Dict]) -> Dict[str, Any]:
        """Breaks down solved problems by tier and rating."""
        by_tier:   Dict[str, int] = defaultdict(int)
        by_rating: Dict[str, int] = defaultdict(int)
        unrated = 0
 
        for prob in problems:
            rating = prob.get("rating")
            if not rating:
                unrated += 1
                continue
 
            by_rating[str(rating)] = by_rating.get(str(rating), 0) + 1
 
            for tier, (low, high) in cls.RATING_TIERS.items():
                if low <= rating <= high:
                    by_tier[tier] += 1
                    break
 
        rated = [p["rating"] for p in problems if p.get("rating")]
        percentiles = {}
        if rated:
            s = sorted(rated)
            percentiles = {
                "25th": s[len(s) // 4],
                "50th": s[len(s) // 2],
                "75th": s[3 * len(s) // 4],
            }
 
        return {
            "by_tier":               dict(by_tier),
            "by_rating":             dict(sorted(by_rating.items())),
            "unrated_problems":      unrated,
            "percentiles":           percentiles,
            "highest_rating_solved": max(rated) if rated else 0,
            "average_rating_solved": round(sum(rated) / len(rated), 1) if rated else 0,
        }
    
    @staticmethod
    def _analyze_rating_progression(rating_data: Dict, user: Dict) -> Dict[str, Any]:
        """Extracts contest history and rating trend. No labels — raw numbers only."""
        if rating_data["status"] != "OK" or not rating_data["result"]:
            return {
                "trend":          "no_data",
                "trend_delta":    0,
                "volatility":     0,
                "total_contests": 0,
                "peak_rating":    user.get("maxRating", 0),
                "current_rating": user.get("rating", 0),
            }
 
        contests     = rating_data["result"]
        recent       = contests[-10:] if len(contests) >= 10 else contests
        trend_delta  = 0
        trend        = "no_data"
 
        if len(recent) >= 2:
            trend_delta = recent[-1]["newRating"] - recent[0]["newRating"]
            if trend_delta > 100:   trend = "strong_up"
            elif trend_delta > 0:   trend = "improving"
            elif trend_delta > -100:trend = "slight_down"
            else:                   trend = "declining"
 
        changes    = [c["newRating"] - c["oldRating"] for c in contests]
        volatility = round(statistics.stdev(changes), 1) if len(changes) > 1 else 0
 
        best  = max(contests, key=lambda c: c["newRating"] - c["oldRating"])
        worst = min(contests, key=lambda c: c["newRating"] - c["oldRating"])
 
        return {
            "trend":          trend,
            "trend_delta":    trend_delta,
            "volatility":     volatility,
            "total_contests": len(contests),
            "peak_rating":    user.get("maxRating", 0),
            "current_rating": user.get("rating", 0),
            "best_performance": {
                "contest":     best["contestName"],
                "rating_gain": best["newRating"] - best["oldRating"],
                "rank":        best["rank"],
            },
            "worst_performance": {
                "contest":     worst["contestName"],
                "rating_loss": worst["newRating"] - worst["oldRating"],
                "rank":        worst["rank"],
            },
        }
 
    @staticmethod
    def _analyze_recency(submissions_data: Dict, rating_data: Dict) -> Dict[str, Any]:
        """Returns raw recency numbers — no emoji labels, no verdicts."""
        now = datetime.utcnow()
 
        days_since_sub     = 999
        days_since_contest = 999
 
        if submissions_data["status"] == "OK" and submissions_data["result"]:
            ts = submissions_data["result"][0]["creationTimeSeconds"]
            days_since_sub = (now - datetime.utcfromtimestamp(ts)).days
 
        if rating_data["status"] == "OK" and rating_data["result"]:
            ts = rating_data["result"][-1]["ratingUpdateTimeSeconds"]
            days_since_contest = (now - datetime.utcfromtimestamp(ts)).days
 
        # Recency score 0–10 based on submission gap
        if   days_since_sub <=   7: recency_score = 10
        elif days_since_sub <=  30: recency_score = 8
        elif days_since_sub <=  90: recency_score = 6
        elif days_since_sub <= 180: recency_score = 4
        elif days_since_sub <= 365: recency_score = 2
        else:                       recency_score = 0
 
        return {
            "days_since_last_submission": days_since_sub,
            "days_since_last_contest":    days_since_contest,
            "recency_score":              recency_score,
        }
 
    @staticmethod
    def _assess_skills(analysis: Dict, difficulty: Dict) -> Dict[str, Any]:
        """Returns factual skill indicators — no labels or verdicts."""
        tags         = analysis.get("tags", {})
        top_tags     = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:5]
        top_strengths = [tag for tag, count in top_tags if count >= 10]
 
        return {
            "tag_diversity":          len(tags),
            "top_strengths":          top_strengths,
            "can_solve_hard_problems":difficulty.get("highest_rating_solved", 0) >= 2000,
        }