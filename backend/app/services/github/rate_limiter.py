# app/services/github/rate_limiter.py
#
# Adaptive rate limiter for Gemini API calls during repo analysis.
# Adjusts request limits dynamically based on repo size to avoid
# hitting Gemini's per-minute quota.

import time
from typing import List


class AdaptiveRateLimiter:
    """
    Tracks outgoing Gemini API requests and throttles when needed.

    Strategy:
      - Smaller repos (fewer files) → higher request rate allowed
      - Larger repos → lower rate to stay within quota
      - Enforces a minimum delay between consecutive requests
      - Sleeps when the per-minute limit is reached, then resets
    """

    def __init__(self) -> None:
        self._requests: List[float] = []   # timestamps of recent requests
        self._current_limit: int = 3       # max requests per minute (default conservative)
        self._min_delay: float = 5.0       # minimum seconds between any two requests

    # ──────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────

    def set_limit_based_on_files(self, file_count: int) -> None:
        """
        Call this once per repo before the analysis loop starts.
        Sets the per-minute request cap based on how many files
        the repo has — fewer files = less work per request = higher rate.
        """
        if file_count <= 30:
            self._current_limit = 9
        elif file_count <= 50:
            self._current_limit = 6
        elif file_count <= 100:
            self._current_limit = 4
        else:
            self._current_limit = 3

        print(f"   ⚙️  Rate limit set to {self._current_limit} req/min for {file_count} files")

    def wait_if_needed(self) -> None:
        """
        Call this immediately before every Gemini API request.
        Blocks the current thread if:
          - the last request was too recent (min delay not elapsed), or
          - the per-minute cap has been reached (waits for the window to reset)
        """
        now = time.time()

        # Drop timestamps older than 60 seconds — outside the current window
        self._requests = [t for t in self._requests if now - t < 60]

        # Enforce minimum gap between consecutive requests
        if self._requests:
            elapsed_since_last = now - self._requests[-1]
            if elapsed_since_last < self._min_delay:
                time.sleep(self._min_delay - elapsed_since_last)

        # Enforce per-minute cap — sleep until the oldest request falls out of window
        if len(self._requests) >= self._current_limit:
            sleep_time = 60 - (now - self._requests[0]) + 2   # +2s safety buffer
            print(f"   ⏳ Rate limit reached. Waiting {int(sleep_time)}s...")
            time.sleep(sleep_time)
            self._requests = []   # reset after sleeping

        # Record this request
        self._requests.append(time.time())