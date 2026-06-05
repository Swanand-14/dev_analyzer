# app/analysis/stage1/signal_validator.py
#
# Signal validation and pre-cleanup for Stage-1 extraction.
#
# Two responsibilities:
#   1. validate_signal()  — checks a single signal has the right shape
#   2. clean_signals()    — filters a list of signals per chunk before aggregation

import re
from typing import Dict, List

from app.services.github.constants import (
    ALLOWED_CAPABILITIES,
    ALLOWED_SIGNAL_TYPES,
    NOISE_ACTIONS,
)


def validate_signal(signal: Dict) -> bool:
    """
    Returns True if a signal is structurally valid and safe to keep.

    Rules:
      - Must have all four required fields
      - capability must be one of ALLOWED_CAPABILITIES
      - type must be one of ALLOWED_SIGNAL_TYPES
      - evidence must be a non-empty string
      - action must be snake_case (lowercase letters, digits, underscores only)
    """
    required = {"capability", "type", "action", "evidence"}

    if not all(f in signal for f in required):
        return False

    if signal["capability"] not in ALLOWED_CAPABILITIES:
        return False

    if signal["type"] not in ALLOWED_SIGNAL_TYPES:
        return False

    if not signal["evidence"] or not str(signal["evidence"]).strip():
        return False

    if not re.match(r"^[a-z0-9_]+$", signal["action"]):
        return False

    return True


def clean_signals(signals: List[Dict], chunk_files: List[str]) -> List[Dict]:
    """
    Light pre-cleanup applied to each chunk's signals before aggregation.

    Steps:
      1. Drop known noise actions (boilerplate, README content, etc.)
      2. Validate signal shape — drop malformed signals
      3. Truncate evidence strings longer than 150 chars
    """
    cleaned = []

    for signal in signals:
        # Drop boilerplate actions
        if signal.get("action") in NOISE_ACTIONS:
            continue

        # Drop malformed signals
        if not validate_signal(signal):
            continue

        signal = signal.copy()

        # Truncate long evidence
        if len(str(signal["evidence"])) > 150:
            signal["evidence"] = str(signal["evidence"])[:147] + "..."

        cleaned.append(signal)

    return cleaned