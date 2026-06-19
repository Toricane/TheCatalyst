"""Demonstration script showing rate limiting in action.

Run from project root:
    python scripts/demo_rate_limiting.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.rate_limiter import estimate_tokens, rate_limiter  # noqa: E402


async def demonstrate_rate_limiting() -> None:
    print("Rate Limiting Demonstration")
    print("=" * 50)

    print("\nCurrent Rate Limits:")
    for model, limits in rate_limiter._limits.items():
        print(f"  {model}:")
        print(f"    rpm={limits.get('rpm', 0) or 'disabled'}")
        print(f"    tpm={limits.get('tpm', 0) or 'disabled'}")
        print(f"    rpd={limits.get('rpd', 0) or 'disabled'}")

    model = "gemini-2.5-flash"
    limits = rate_limiter._limits.get(model, {})
    rpm = limits.get("rpm", 0)

    if not rpm:
        print(f"\n{model} has no RPM limit configured; skipping enforcement demo.")
        return

    print(f"\nApproaching {rpm} RPM limit on {model}...")
    for _ in range(rpm):
        await rate_limiter.wait_for_request(model, 50)
        print(".", end="", flush=True)

    delay_start = time.monotonic()
    await rate_limiter.wait_for_request(model, 50)
    delay_time = time.monotonic() - delay_start
    print(f"\nNext request delayed by {delay_time:.2f}s")


if __name__ == "__main__":
    asyncio.run(demonstrate_rate_limiting())
