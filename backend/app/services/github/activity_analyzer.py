from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List
import statistics

class GitHubActivityAnalyzer:
    """Analyze GitHub commit activity patterns."""
    @staticmethod
    def analyze_commit_patterns(repo, branch: str = "main") -> Dict:
        try:
            commits = list(repo.get_commits(sha=branch))[:500]
        except Exception:
            try:
                commits = list(repo.get_commits(sha="master"))[:500]
            except Exception:
                return GitHubActivityAnalyzer._empty_activity()
            
        if not commits:
            return GitHubActivityAnalyzer._empty_activity()
        
        daily_commits       = defaultdict(int)
        hourly_distribution = defaultdict(int)
        weekday_distribution= defaultdict(int)
        monthly_commits     = defaultdict(int)
        yearly_commits      = defaultdict(int)
        author_contributions= defaultdict(int)
        commit_sizes        = []

        weekday_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
 
        for commit in commits:
            commit_date = commit.commit.author.date
            daily_commits[commit_date.strftime("%Y-%m-%d")]  += 1
            hourly_distribution[commit_date.hour]            += 1
            weekday_distribution[weekday_names[commit_date.weekday()]] += 1
            monthly_commits[commit_date.strftime("%Y-%m")]   += 1
            yearly_commits[commit_date.strftime("%Y")]       += 1
            author_contributions[commit.commit.author.name]  += 1
            try:
                commit_sizes.append(commit.stats.total)
            except Exception:
                pass
 
        streak_info       = GitHubActivityAnalyzer._calculate_streaks(daily_commits)
        consistency_score = GitHubActivityAnalyzer._calculate_consistency(daily_commits, monthly_commits)
        
 
        most_recent        = max(commits, key=lambda c: c.commit.author.date)
        days_since_last    = (datetime.now(most_recent.commit.author.date.tzinfo) - most_recent.commit.author.date).days
        recency_score      = round(max(0, 10 - (days_since_last / 7)), 1)
 
        return {
            "total_commits_analyzed": len(commits),
            "date_range": {
                "earliest":              min(commits, key=lambda c: c.commit.author.date).commit.author.date.isoformat(),
                "latest":                most_recent.commit.author.date.isoformat(),
                "days_since_last_commit":days_since_last,
            },
            "heatmap_data":          dict(daily_commits),
            "active_days":           len(daily_commits),
            "streak":                streak_info,
            "hourly_distribution":   dict(hourly_distribution),
            "weekday_distribution":  dict(weekday_distribution),
            "monthly_commits":       dict(monthly_commits),
            "yearly_commits":        dict(yearly_commits),
            "active_years":          sorted(yearly_commits.keys()),
            "consistency_score":     consistency_score,
            "recency_score":         recency_score,
            "author_contributions":  dict(sorted(author_contributions.items(), key=lambda x: x[1], reverse=True)[:5]),
            "commit_size_stats": {
                "average_lines_changed_per_commit": round(statistics.mean(commit_sizes),   1) if commit_sizes else 0,
                "median_lines_changed_per_commit":  round(statistics.median(commit_sizes), 1) if commit_sizes else 0,
                "max_lines_changed_in_commit":      max(commit_sizes) if commit_sizes else 0,
            },
        }
    
    @staticmethod
    def _calculate_streaks(daily_commits: Dict[str, int]) -> Dict:
        if not daily_commits:
            return {"current": 0, "longest": 0}
 
        dates    = sorted(daily_commits.keys())
        date_set = set(dates)
        today    = datetime.now().date()
 
        current_streak = 0
        check_date = today
        while check_date.isoformat() in date_set:
            current_streak += 1
            check_date -= timedelta(days=1)
 
        if current_streak == 0:
            check_date = today - timedelta(days=1)
            while check_date.isoformat() in date_set:
                current_streak += 1
                check_date -= timedelta(days=1)
 
        longest_streak = temp = 0
        current_date   = datetime.fromisoformat(dates[0]).date()
        end_date       = datetime.fromisoformat(dates[-1]).date()
 
        while current_date <= end_date:
            if current_date.isoformat() in date_set:
                temp += 1
                longest_streak = max(longest_streak, temp)
            else:
                temp = 0
            current_date += timedelta(days=1)
 
        return {"current": current_streak, "longest": longest_streak}
 
    @staticmethod
    def _calculate_consistency(daily_commits: Dict, monthly_commits: Dict) -> float:
        if not monthly_commits:
            return 0.0
 
        values = list(monthly_commits.values())
        if len(values) > 1:
            mean = statistics.mean(values)
            cv   = (statistics.stdev(values) / mean) if mean > 0 else 10
        else:
            cv = 0
 
        base = max(0, 10 - cv)
        if len(monthly_commits) >= 12:  base += 2
        elif len(monthly_commits) >= 6: base += 1
 
        return min(10, round(base, 1))
    

    @staticmethod
    def _empty_activity() -> Dict:
        return {
            "total_commits_analyzed": 0,
            "date_range":             None,
            "heatmap_data":           {},
            "active_days":            0,
            "streak":                 {"current": 0, "longest": 0},
            "hourly_distribution":    {},
            "weekday_distribution":   {},
            "monthly_commits":        {},
            "yearly_commits":         {},
            "active_years":           [],
            "author_contributions":   {},
            "commit_size_stats":      {},
        }
    
