from typing import Dict, List
 
 

 
# 25 core topics FAANG interviewers care about.
# target   = minimum problems to be considered "ready"
# priority = importance weight (10 = critical, 5 = nice-to-have)
# tags     = LeetCode slug variants that map to this topic
CORE_TOPICS: Dict[str, Dict] = {
    "Array":                {"target": 20, "priority": 10, "tags": ["array", "arrays"]},
    "String":               {"target": 15, "priority":  9, "tags": ["string", "strings"]},
    "Hash Table":           {"target": 15, "priority": 10, "tags": ["hash-table", "hash table", "hashmap", "hash map"]},
    "Dynamic Programming":  {"target": 20, "priority": 10, "tags": ["dynamic-programming", "dp"]},
    "Math":                 {"target": 10, "priority":  6, "tags": ["math", "mathematics"]},
    "Sorting":              {"target": 10, "priority":  7, "tags": ["sorting", "sort"]},
    "Greedy":               {"target": 10, "priority":  8, "tags": ["greedy"]},
    "Depth-First Search":   {"target": 15, "priority": 10, "tags": ["depth-first-search", "dfs"]},
    "Binary Search":        {"target": 12, "priority":  9, "tags": ["binary-search"]},
    "Database":             {"target":  5, "priority":  5, "tags": ["database", "sql"]},
    "Breadth-First Search": {"target": 12, "priority":  9, "tags": ["breadth-first-search", "bfs"]},
    "Tree":                 {"target": 15, "priority": 10, "tags": ["tree", "binary-tree"]},
    "Matrix":               {"target": 10, "priority":  7, "tags": ["matrix"]},
    "Two Pointers":         {"target": 12, "priority":  9, "tags": ["two-pointers"]},
    "Bit Manipulation":     {"target":  8, "priority":  6, "tags": ["bit-manipulation", "bitwise"]},
    "Heap (Priority Queue)":{"target": 10, "priority":  8, "tags": ["heap", "priority-queue"]},
    "Stack":                {"target": 12, "priority":  8, "tags": ["stack"]},
    "Binary Search Tree":   {"target": 10, "priority":  8, "tags": ["binary-search-tree", "bst"]},
    "Graph":                {"target": 12, "priority":  9, "tags": ["graph"]},
    "Design":               {"target":  8, "priority":  7, "tags": ["design", "system-design"]},
    "Simulation":           {"target":  8, "priority":  5, "tags": ["simulation"]},
    "Backtracking":         {"target": 10, "priority":  8, "tags": ["backtracking"]},
    "Sliding Window":       {"target": 10, "priority":  9, "tags": ["sliding-window"]},
    "Linked List":          {"target": 12, "priority":  9, "tags": ["linked-list"]},
    "Union Find":           {"target":  6, "priority":  7, "tags": ["union-find", "disjoint-set"]},
}

class LeetCodeTopicHeatmap:
    """
    Transforms raw LeetCode skills_breakdown data into a topic coverage heatmap.
 
    Call generate_heatmap() with the dict returned by LeetCodeClient.fetch_user_data().
    The output shape is consumed directly by create_unified_analysis() in Stage-2.
    """
 
    @staticmethod
    def generate_heatmap(leetcode_data: Dict) -> Dict:
        """
        Main entry point. Returns a full heatmap dict or an empty heatmap
        if the input is missing or contains an error.
        """
        if not leetcode_data or leetcode_data.get("error"):
            return LeetCodeTopicHeatmap._empty_heatmap()
 
        topic_coverage = LeetCodeTopicHeatmap._build_topic_coverage(
            leetcode_data.get("skills_breakdown", {})
        )
 
        overall_metrics  = LeetCodeTopicHeatmap._compute_overall_metrics(topic_coverage)
        
        top_strengths, critical_gaps = LeetCodeTopicHeatmap._find_strengths_and_gaps(topic_coverage)
        
 
        return {
            "topic_coverage":       topic_coverage,
            "overall_metrics":      overall_metrics,
            
            "top_strengths":        top_strengths,
            "critical_gaps":        critical_gaps,
            
        }
    
    @staticmethod
    def _build_topic_coverage(skills_breakdown: Dict) -> Dict[str, Dict]:
        """
        Maps raw LeetCode skill tags → CORE_TOPICS entries.
        Estimates difficulty distribution from skill level (advanced/intermediate/fundamental).
        """
        topic_coverage: Dict[str, Dict] = {}
 
        for topic_name, topic_info in CORE_TOPICS.items():
            problems_solved = 0
            difficulty: Dict[str, int] = {"easy": 0, "medium": 0, "hard": 0}
 
            for level in ["advanced", "intermediate", "fundamental"]:
                for skill in skills_breakdown.get(level, []):
                    name_lower = skill["name"].lower()
                    slug_lower = skill["slug"].lower()
 
                    if any(tag in name_lower or tag in slug_lower for tag in topic_info["tags"]):
                        count = skill["problems_solved"]
                        problems_solved += count
 
                        # Heuristic: estimate difficulty split from skill level
                        if level == "advanced":
                            difficulty["hard"]   += count // 2
                            difficulty["medium"] += count // 2
                        elif level == "intermediate":
                            difficulty["medium"] += count
                        else:
                            difficulty["easy"] += count
 
            target           = topic_info["target"]
            coverage_pct     = min(100.0, (problems_solved / target) * 100)
            readiness_score  = min(10.0,  (problems_solved / target) * 10)
 
            topic_coverage[topic_name] = {
                "problems_solved":    problems_solved,
                "target":             target,
                "coverage_percent":   round(coverage_pct, 1),
                "proficiency":        _proficiency_label(problems_solved, target),
                "interview_readiness":round(readiness_score, 1),
                "priority":           topic_info["priority"],
                "difficulty_breakdown": difficulty,
                "status":             _status_label(problems_solved, target),
            }
 
        return topic_coverage
    
    @staticmethod
    def _compute_overall_metrics(topic_coverage: Dict[str, Dict]) -> Dict[str, float]:
        total_target = sum(CORE_TOPICS[t]["target"] for t in CORE_TOPICS)
        total_solved = sum(v["problems_solved"] for v in topic_coverage.values())
 
        return {
            "overall_coverage_percent": round((total_solved / total_target) * 100, 1),
            "topics_ready":             sum(1 for v in topic_coverage.values() if "Ready"       in v["status"]),
            "topics_needs_work":        sum(1 for v in topic_coverage.values() if "Needs Work"  in v["status"]),
            "topics_not_started":       sum(1 for v in topic_coverage.values() if "Not Started" in v["status"]),
        }
    
    @staticmethod
    def _find_strengths_and_gaps(topic_coverage: Dict[str, Dict]):
        sorted_topics = sorted(
            topic_coverage.items(),
            key=lambda x: x[1]["problems_solved"],
            reverse=True,
        )
        top_strengths = [k for k, v in sorted_topics[:3] if v["problems_solved"] > 0]
        critical_gaps = [k for k, v in sorted_topics[-3:] if v["problems_solved"] < v["target"] * 0.3]
        return top_strengths, critical_gaps
    

    

def _proficiency_label(solved: int, target: int) -> str:
    ratio = solved / target
    if ratio >= 1.0:   return "Expert"
    if ratio >= 0.7:   return "Advanced"
    if ratio >= 0.4:   return "Intermediate"
    if ratio >= 0.2:   return "Beginner"
    return "Novice"
 
 
def _status_label(solved: int, target: int) -> str:
    if solved >= target * 0.6: return "✅ Ready"
    if solved > 0:             return "⚠️ Needs Work"
    return "❌ Not Started"