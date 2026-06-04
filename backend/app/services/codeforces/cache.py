from datetime import datetime
from typing import Any, Dict, Optional
 
from pymongo.database import Database
 
from app.services.codeforces.client import CodeforcesClient
 
CACHE_TTL_SECONDS = 3600  # 1 hour
 
 
class CodeforcesCache:
    """
    Wraps CodeforcesClient with a MongoDB cache layer.
 
    Usage:
        data = CodeforcesCache.get(db, username)
        data = CodeforcesCache.get(db, username, force_refresh=True)
    """
 
    @staticmethod
    def get(
        db: Database,
        username: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Returns Codeforces data for a user.
 
        Flow:
          1. Check MongoDB cache — return if fresh (< 1hr old)
          2. Fetch fresh from Codeforces API
          3. Store in cache and return
 
        Returns {"error": "..."} if fetch fails.
        """
        if not force_refresh:
            cached = CodeforcesCache._read(db, username)
            if cached:
                print(f"   ✓ Codeforces cache hit: {username}")
                return cached
 
        print(f"   🔄 Fetching fresh Codeforces data: {username}")
        data = CodeforcesClient.fetch_user_data(username)
 
        if data.get("error"):
            return data
 
        CodeforcesCache._write(db, username, data)
        return data
    @staticmethod
    def _read(db: Database, username: str) -> Optional[Dict[str, Any]]:
        """Returns cached data if it exists and is within TTL, else None."""
        doc = db.codeforces_cache.find_one({"username": username})
        if not doc:
            return None
 
        age = (datetime.utcnow() - doc["fetched_at"]).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
 
        return doc["data"]
 
    @staticmethod
    def _write(db: Database, username: str, data: Dict[str, Any]) -> None:
        """Upserts data into the cache with current timestamp."""
        db.codeforces_cache.update_one(
            {"username": username},
            {"$set": {
                "data":       data,
                "fetched_at": datetime.utcnow().replace(microsecond=0),
            }},
            upsert=True,
        )
        print(f"   ✅ Codeforces cache updated: {username}")
 