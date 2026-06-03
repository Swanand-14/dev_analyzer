# app/services/github/__init__.py
#
# Public interface for the github service package.
# Import from here — not from submodules directly.

from app.services.github.chunker import ChunkingAnalyzer
from app.services.github.rate_limiter import AdaptiveRateLimiter
from app.services.github.file_utils import (
    should_include_file,
    is_boilerplate,
    is_high_priority,
    extract_code_metadata,
    calculate_feature_score,
)

__all__ = [
    "ChunkingAnalyzer",
    "AdaptiveRateLimiter",
    "should_include_file",
    "is_boilerplate",
    "is_high_priority",
    "extract_code_metadata",
    "calculate_feature_score",
]