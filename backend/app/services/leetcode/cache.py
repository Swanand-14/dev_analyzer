from datetime import datetime, timedelta
from typing import Any, Dict, Optional
 
from pymongo.database import Database
 
from app.services.leetcode.client import LeetCodeClient
from app.services.leetcode.heatmap import LeetCodeTopicHeatmap
 
CACHE_TTL_SECONDS = 3600  # 1 hour
 
 
class LeetCodeCache:
    """
    Wraps LeetCodeClient with a MongoDB cache layer.
 
    Usage:
        data = LeetCodeCache.get(db, username)
        data = LeetCodeCache.get(db, username, force_refresh=True)
    """
 
    @staticmethod
    def get(
        db: Database,
        username: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Returns LeetCode data for a user.
 
        Flow:
          1. Check MongoDB cache — return if fresh (< 1hr old)
          2. Fetch fresh from LeetCode API
          3. Generate heatmap on fresh data
          4. Store in cache and return
 
        Returns {"error": "..."} if fetch fails.
        """
        if not force_refresh:
            cached = LeetCodeCache._read(db, username)
            if cached:
                print(f"   ✓ LeetCode cache hit: {username}")
                return cached
 
        print(f"   🔄 Fetching fresh LeetCode data: {username}")
        data = LeetCodeClient.fetch_user_data(username)
 
        if data.get("error"):
            return data
 
        # Attach heatmap before storing
        data["topic_heatmap"] = LeetCodeTopicHeatmap.generate_heatmap(data)
 
        LeetCodeCache._write(db, username, data)
        return data
 
   
 
    @staticmethod
    def _read(db: Database, username: str) -> Optional[Dict[str, Any]]:
        """Returns cached data if it exists and is within TTL, else None."""
        doc = db.leetcode_cache.find_one({"username": username})
        if not doc:
            return None
 
        age = (datetime.utcnow() - doc["fetched_at"]).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
 
        return doc["data"]
 
    @staticmethod
    def _write(db: Database, username: str, data: Dict[str, Any]) -> None:
        """Upserts data into the cache with current timestamp."""
        db.leetcode_cache.update_one(
            {"username": username},
            {"$set": {
                "data":       data,
                "fetched_at": datetime.utcnow().replace(microsecond=0),
            }},
            upsert=True,
        )
        print(f"    LeetCode cache updated: {username}")
 