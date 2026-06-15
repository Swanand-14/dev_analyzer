from datetime import datetime
from typing import Any
 
 
class MongoDBSanitizer:
    """
    Ensures all data is compatible with MongoDB storage.
 
    Two rules:
      1. All dict keys must be strings (MongoDB rejects numeric keys)
      2. Datetime objects must have microseconds stripped
    """
 
    @staticmethod
    def sanitize(data: Any) -> Any:
        """
        Recursively sanitizes data for MongoDB storage.
        Safe to call on any nested structure.
        """
        if isinstance(data, dict):
            return {
                str(k): MongoDBSanitizer.sanitize(v)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [MongoDBSanitizer.sanitize(item) for item in data]
        if isinstance(data, datetime):
            return data.replace(microsecond=0)
        return data