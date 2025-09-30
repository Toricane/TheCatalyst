"""Tests for rate limiting functionality."""

import asyncio
import time

import pytest

from backend.rate_limiter import RateLimiter, estimate_tokens


@pytest.fixture
def rate_limiter():
    """Create a rate limiter with test limits."""
    return RateLimiter(
        {
            "test-model": {"rpm": 5, "tpm": 1000, "rpd": 100},
            "fast-model": {"rpm": 10, "tpm": 2000, "rpd": 200},
        }
    )


@pytest.mark.asyncio
async def test_basic_rate_limiting(rate_limiter):
    """Test basic rate limiting functionality."""
    # Should allow requests up to the limit
    for _ in range(5):
        await rate_limiter.wait_for_request("test-model")

    # Next request should be delayed
    start_time = time.monotonic()
    await rate_limiter.wait_for_request("test-model")
    elapsed = time.monotonic() - start_time
    assert elapsed > 0.05  # Should have waited


@pytest.mark.asyncio
async def test_token_limiting(rate_limiter):
    """Test token-based rate limiting."""
    # Use up most of the token limit
    await rate_limiter.wait_for_request("test-model", 900)
    await rate_limiter.record_usage("test-model", 900)

    # Should still allow small requests
    await rate_limiter.wait_for_request("test-model", 50)

    # But not large ones
    start_time = time.monotonic()
    await rate_limiter.wait_for_request("test-model", 200)
    elapsed = time.monotonic() - start_time
    assert elapsed > 0.05  # Should have waited


@pytest.mark.asyncio
async def test_different_models_independent(rate_limiter):
    """Test that different models have independent limits."""
    # Max out one model
    for _ in range(5):
        await rate_limiter.wait_for_request("test-model")

    # Other model should still work immediately
    start_time = time.monotonic()
    await rate_limiter.wait_for_request("fast-model")
    elapsed = time.monotonic() - start_time
    assert elapsed < 0.01  # Should be immediate


def test_token_estimation():
    """Test token estimation heuristics."""
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0
    assert estimate_tokens("Hello world") > 0
    assert estimate_tokens("Long text", "More text") > estimate_tokens("Short")


@pytest.mark.asyncio
async def test_no_limits_for_unknown_model(rate_limiter):
    """Test that unknown models have no limits."""
    start_time = time.monotonic()
    for _ in range(20):  # Well over any limit
        await rate_limiter.wait_for_request("unknown-model")
    elapsed = time.monotonic() - start_time
    assert elapsed < 0.1  # Should be very fast


@pytest.mark.asyncio
async def test_concurrent_requests(rate_limiter):
    """Test concurrent requests are handled correctly."""

    async def make_request():
        await rate_limiter.wait_for_request("test-model")
        return time.monotonic()

    # Start many concurrent requests
    tasks = [make_request() for _ in range(10)]
    times = await asyncio.gather(*tasks)

    # Times should be spread out due to rate limiting
    time_diffs = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    # Some requests should have been delayed
    assert any(diff > 0.05 for diff in time_diffs)


@pytest.mark.asyncio
async def test_get_wait_time(rate_limiter):
    """Ensure get_wait_time reflects current quota availability."""

    # Consume the per-minute quota for the test model
    for _ in range(5):
        await rate_limiter.wait_for_request("test-model")

    wait_time = await rate_limiter.get_wait_time("test-model")
    assert wait_time > 0

    # Another model should still be immediately available
    wait_time_fast = await rate_limiter.get_wait_time("fast-model")
    assert wait_time_fast == 0


if __name__ == "__main__":
    pytest.main([__file__])
