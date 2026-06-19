#!/usr/bin/env python3
"""Test script to verify retry logic for overload and quota errors."""

import sys

from backend.catalyst_ai import (
    _calculate_retry_delay,
    _is_retryable_error,
    _parse_quota_error,
)


class _MockQuotaError(Exception):
    def __init__(self, status_code: int, response: dict) -> None:
        self.status_code = status_code
        self.response = response
        super().__init__(response.get("error", {}).get("message", "quota error"))


def test_error_detection():
    """Test that we correctly identify retryable errors."""
    print("🧪 Testing error detection...")

    retryable_errors = [
        Exception("Error 503: Service unavailable"),
        Exception("The model is overloaded. Please try again later."),
        Exception("UNAVAILABLE: Service temporarily unavailable"),
        Exception("503 error occurred"),
    ]

    non_retryable_errors = [
        Exception("Invalid API key"),
        Exception("400 Bad Request"),
        Exception("Rate limit exceeded"),
        Exception("Authentication failed"),
    ]

    print("  ✅ Testing retryable errors:")
    for error in retryable_errors:
        result = _is_retryable_error(error)
        print(f"    • '{error}' → {result}")
        assert result, f"Should be retryable: {error}"

    print("  ✅ Testing non-retryable errors:")
    for error in non_retryable_errors:
        result = _is_retryable_error(error)
        print(f"    • '{error}' → {result}")
        assert not result, f"Should not be retryable: {error}"


def test_retry_delays():
    """Test exponential backoff calculation."""
    print("\n🧪 Testing retry delay calculation...")

    for attempt in range(5):
        delay = _calculate_retry_delay(attempt)
        expected_base = min(1.0 * (2**attempt), 60.0)
        print(f"  • Attempt {attempt + 1}: {delay:.2f}s (base: {expected_base:.2f}s)")

        assert 0.1 <= delay <= 65.0, f"Delay out of range: {delay}"


def test_mock_scenario():
    """Simulate a retry scenario."""
    print("\n🧪 Simulating retry scenario...")

    max_retries = 3
    for attempt in range(max_retries):
        delay = _calculate_retry_delay(attempt)
        print(f"  • Attempt {attempt + 1}/{max_retries}: would wait {delay:.2f}s")

        if attempt == max_retries - 1:
            print("    → Would switch to fallback model")

    print("  ✅ Retry simulation complete")


def test_parse_quota_error():
    """Ensure quota errors are parsed for retry guidance."""

    payload = {
        "error": {
            "code": 429,
            "message": "Quota exceeded. Please retry in 24s.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "24s",
                }
            ],
        }
    }

    error = _MockQuotaError(429, payload)
    info = _parse_quota_error(error)

    assert info is not None
    assert info.status_code == 429
    assert info.retry_after == 24.0
    assert "Quota" in info.message or "quota" in info.message


if __name__ == "__main__":
    print("🚀 Starting retry logic tests...\n")

    try:
        test_error_detection()
        test_retry_delays()
        test_mock_scenario()
        test_parse_quota_error()

        print("\n✅ All tests passed! Retry logic is working correctly.")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
