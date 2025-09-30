#!/usr/bin/env python3
"""Demonstration of retry logic behavior for overload scenarios."""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from backend.catalyst_ai import _is_retryable_error


class _MockModelInterface:
    """Helper to mimic the client.models interface used by the SDK."""

    def __init__(self, client: "MockOverloadedClient") -> None:
        self._client = client

    def generate_content(self, model, contents, config):
        return self._client._generate_content(model)


class MockOverloadedClient:
    """Mock client that simulates API overload scenarios."""

    def __init__(self, fail_attempts=2):
        self.fail_attempts = fail_attempts
        self.attempt_count = 0
        self.models = _MockModelInterface(self)

    def _generate_content(self, model: str):
        self.attempt_count += 1
        print(f"  📡 Mock API call attempt {self.attempt_count} to {model}")

        if self.attempt_count <= self.fail_attempts:
            # Simulate overload error
            raise Exception(
                "Error 503: The model is overloaded. Please try again later."
            )

        # Simulate success
        return MockResponse(f"Success after {self.attempt_count} attempts!")


class MockResponse:
    """Mock successful response."""

    def __init__(self, text):
        self.text = text
        self.candidates = [MockCandidate()]


class MockCandidate:
    """Mock response candidate."""

    def __init__(self):
        self.content = None


async def demonstrate_retry_scenarios():
    """Show different retry scenarios."""

    print("🎭 Demonstrating Retry Logic Scenarios")
    print("=" * 50)

    scenarios = [
        ("Immediate Success", 0),
        ("Success After 1 Retry", 1),
        ("Success After 2 Retries", 2),
        ("Complete Failure", 5),  # More failures than max retries
    ]

    from backend.catalyst_ai import MAX_RETRIES

    for scenario_name, fail_count in scenarios:
        print(f"\n🎬 Scenario: {scenario_name}")
        print("-" * 30)

        mock_client = MockOverloadedClient(fail_count)

        try:
            # This would normally call _make_api_call_with_retry, but we'll simulate it
            print(f"  🎯 Target: Fail first {fail_count} attempts, then succeed")

            if fail_count >= MAX_RETRIES:
                print(
                    f"  ⚠️  Expected outcome: Complete failure after {MAX_RETRIES} attempts"
                )
                # Simulate what would happen
                for attempt in range(MAX_RETRIES):
                    try:
                        mock_client.models.generate_content("test-model", [], None)
                    except Exception as e:
                        if attempt < MAX_RETRIES - 1:
                            print(f"  ❌ Attempt {attempt + 1} failed: {e}")
                        else:
                            print(f"  💥 Final attempt {attempt + 1} failed: {e}")
                            print("  🚫 Would return 503 error to user")
            else:
                print(f"  ✅ Expected outcome: Success after {fail_count + 1} attempts")
                # Simulate successful retry
                for attempt in range(fail_count + 1):
                    try:
                        result = mock_client.models.generate_content(
                            "test-model", [], None
                        )
                        print(f"  🎉 Success on attempt {attempt + 1}: {result.text}")
                        break
                    except Exception as e:
                        print(f"  ❌ Attempt {attempt + 1} failed: {e}")
                        if attempt < fail_count:
                            print("  ⏳ Would wait before retry...")

        except Exception as e:
            print(f"  💥 Unexpected error: {e}")


def demonstrate_error_classification():
    """Show how different errors are classified."""

    print("\n🔍 Error Classification Demo")
    print("=" * 30)

    test_errors = [
        ("503 Service Unavailable", True),
        ("The model is overloaded. Please try again later.", True),
        ("UNAVAILABLE: Service temporarily unavailable", True),
        ("Invalid API key", False),
        ("400 Bad Request: Invalid input", False),
        ("Rate limit exceeded", False),
        ("Authentication failed", False),
    ]

    for error_msg, expected_retryable in test_errors:
        error = Exception(error_msg)
        is_retryable = _is_retryable_error(error)
        status = "🔄 RETRY" if is_retryable else "❌ FAIL"
        check = "✅" if is_retryable == expected_retryable else "⚠️"

        print(f"  {check} {status}: {error_msg}")


if __name__ == "__main__":
    print("🚀 Starting Retry Logic Demonstration\n")

    try:
        demonstrate_error_classification()
        asyncio.run(demonstrate_retry_scenarios())

        print("\n" + "=" * 50)
        print("✨ Demonstration Complete!")
        print("\nKey Takeaways:")
        print("• Temporary overload errors trigger automatic retries")
        print("• Exponential backoff prevents overwhelming the service")
        print("• Model fallback provides additional resilience")
        print("• Non-retryable errors fail immediately to save time")
        print("• Detailed logging helps with debugging and monitoring")

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        sys.exit(1)
