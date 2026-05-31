import certifi
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.database import Database
from app.core.config import get_settings
 
_client: MongoClient | None = None
 
 
def connect_db() -> Database:
    global _client
    settings = get_settings()
    _client = MongoClient(
        settings.MONGODB_URI,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=5000,
    )
    _client.admin.command("ping")
    db = _client[settings.MONGODB_DB_NAME]
    _create_indexes(db)
    return db
 
 
def disconnect_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None

def _create_indexes(db: Database) -> None:
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.repositories.create_index([("analysis_id", ASCENDING)], unique=True)
    db.repositories.create_index([("user_id", ASCENDING)])
    db.repositories.create_index([("analyzed_at", DESCENDING)])
    db.leetcode_cache.create_index([("username", ASCENDING)], unique=True)
    db.codeforces_cache.create_index([("username", ASCENDING)], unique=True)