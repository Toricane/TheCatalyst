#!/usr/bin/env python3
"""Demonstration of retry error classification.

Run from project root:
    python scripts/demo_retry_logic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.catalyst_ai import (  # noqa: E402
    MAX_RETRIES,
    _calculate_retry_delay,
    _is_retryable_error,
)


def main() -> None:
    print("Retry logic demonstration\n")

    cases = [
        ("503 Service Unavailable", True),
        ("The model is overloaded. Please try again later.", True),
        ("Connection error to api.clod.io", True),
        ("Invalid API key", False),
        ("400 Bad Request", False),
    ]

    for message, expected in cases:
        result = _is_retryable_error(Exception(message))
        mark = "ok" if result == expected else "WARN"
        print(f"  [{mark}] retry={result}: {message}")

    print(f"\nMax retries: {MAX_RETRIES}")
    for attempt in range(MAX_RETRIES):
        print(f"  attempt {attempt + 1}: backoff ~{_calculate_retry_delay(attempt):.2f}s")


if __name__ == "__main__":
    main()
