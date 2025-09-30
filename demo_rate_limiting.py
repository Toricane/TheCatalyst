"""Demonstration script showing rate limiting in action."""

import asyncio
import time
from typing import Any, Dict

from backend.rate_limiter import estimate_tokens, rate_limiter


async def demonstrate_rate_limiting():
    """Show rate limiting behavior with example usage patterns."""
    print("🚀 Rate Limiting Demonstration")
    print("=" * 50)

    # Show current configuration
    print("\n📊 Current Rate Limits:")
    for model, limits in rate_limiter._limits.items():
        print(f"  {model}:")
        print(f"    • {limits.get('rpm', 'unlimited')} requests/minute")
        print(f"    • {limits.get('tpm', 'unlimited')} tokens/minute")
        print(f"    • {limits.get('rpd', 'unlimited')} requests/day")

    # Test token estimation
    print("\n🔢 Token Estimation Examples:")
    examples = [
        "Hello, how are you?",
        "Write a detailed analysis of artificial intelligence developments in 2024.",
        "",  # Empty string
        None,  # None value
    ]

    for example in examples:
        tokens = estimate_tokens(example)
        display = f"'{example}'" if example else str(example)
        print(f"  {display} → {tokens} tokens")

    # Demonstrate rate limiting in action
    print("\n⏱️  Testing Rate Limiting (this may take a moment):")

    model = "gemini-2.5-pro"  # Use the more restrictive model for demonstration

    # Make several requests quickly
    print(f"\n🔄 Making 3 quick requests to {model}...")
    start_time = time.monotonic()

    for i in range(3):
        print(f"  Request {i + 1}... ", end="", flush=True)
        request_start = time.monotonic()

        await rate_limiter.wait_for_request(model, 100)  # Small token reservation
        await rate_limiter.record_usage(model, 150)  # Simulate actual usage

        elapsed = time.monotonic() - request_start
        print(f"took {elapsed:.2f}s")

    total_elapsed = time.monotonic() - start_time
    print(f"  Total time: {total_elapsed:.2f}s")

    # Now try to hit the rate limit
    print(f"\n🚦 Testing rate limit enforcement...")
    print(f"  Making requests to approach the limit...")

    # Get current limits for the model
    limits = rate_limiter._limits.get(model, {})
    rpm = limits.get("rpm", 0)

    if rpm:
        print(f"  (Model has {rpm} requests/minute limit)")

        # Make requests up to the limit
        for i in range(rpm):
            await rate_limiter.wait_for_request(model, 50)
            print(".", end="", flush=True)

        print(f"\n  Made {rpm} requests. Next request should be delayed...")

        # This should trigger rate limiting
        delay_start = time.monotonic()
        await rate_limiter.wait_for_request(model, 50)
        delay_time = time.monotonic() - delay_start

        if delay_time > 0.1:  # More than 100ms suggests rate limiting kicked in
            print(f"  ✅ Rate limiting worked! Delayed by {delay_time:.2f}s")
        else:
            print(
                f"  ⚠️  No significant delay ({delay_time:.2f}s) - may need adjustment"
            )
    else:
        print(f"  ⚠️  No RPM limit configured for {model}")

    print("\n✨ Rate limiting demonstration complete!")
    print("\nKey points:")
    print("• Rate limits are enforced per model")
    print("• Requests are queued when limits are approached")
    print("• Token usage is tracked and limited")
    print("• The system gracefully handles quota exhaustion")


async def simulate_heavy_usage():
    """Simulate a heavy usage scenario to test rate limiting."""
    print("\n🔥 Heavy Usage Simulation")
    print("=" * 30)

    model = "gemini-2.5-flash"  # Use the faster model
    num_requests = 15

    print(f"Simulating {num_requests} concurrent requests to {model}...")

    async def make_request(request_id: int) -> Dict[str, Any]:
        start_time = time.monotonic()

        # Estimate tokens for a typical conversation
        estimated = estimate_tokens(
            "You are a helpful AI assistant",
            f"This is request number {request_id}. Please provide a helpful response.",
        )

        await rate_limiter.wait_for_request(model, estimated)
        wait_time = time.monotonic() - start_time

        # Simulate actual API response
        await asyncio.sleep(0.1)  # Simulate network delay

        # Record actual usage (simulate response tokens)
        response_tokens = estimate_tokens(
            f"This is a simulated response for request {request_id}"
        )
        await rate_limiter.record_usage(model, response_tokens)

        total_time = time.monotonic() - start_time

        return {
            "request_id": request_id,
            "wait_time": wait_time,
            "total_time": total_time,
            "estimated_tokens": estimated,
            "response_tokens": response_tokens,
        }

    # Launch all requests concurrently
    tasks = [make_request(i) for i in range(num_requests)]
    results = await asyncio.gather(*tasks)

    # Analyze results
    total_wait = sum(r["wait_time"] for r in results)
    avg_wait = total_wait / len(results)
    max_wait = max(r["wait_time"] for r in results)

    print(f"\n📈 Results:")
    print(f"  • Average wait time: {avg_wait:.2f}s")
    print(f"  • Maximum wait time: {max_wait:.2f}s")
    print(f"  • Total requests: {len(results)}")
    print(
        f"  • Rate limiting effectiveness: {'Good' if max_wait > 1.0 else 'Moderate' if avg_wait > 0.1 else 'Minimal'}"
    )

    # Show timeline
    print(f"\n⏱️  Request Timeline:")
    for result in results[:5]:  # Show first 5 for brevity
        print(
            f"  Request {result['request_id']:2d}: waited {result['wait_time']:.2f}s, total {result['total_time']:.2f}s"
        )
    if len(results) > 5:
        print(f"  ... and {len(results) - 5} more requests")


if __name__ == "__main__":
    asyncio.run(demonstrate_rate_limiting())
    asyncio.run(simulate_heavy_usage())
