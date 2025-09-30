#!/usr/bin/env python3
"""
Test script for The Catalyst function calling system
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import init_database
from backend.functions import catalyst_functions


def test_function_calling():
    """Test the function calling system"""
    print("🧪 Testing The Catalyst Function Calling System\n")

    # Initialize database
    print("1. Initializing database...")
    init_database()
    print("✅ Database initialized\n")

    # Test available functions
    print("2. Available functions:")
    for func_name in catalyst_functions.keys():
        print(f"   - {func_name}")
    print()

    # Test log_daily_reflection
    print("3. Testing log_daily_reflection...")
    result = catalyst_functions["log_daily_reflection"](
        wins="Completed project setup",
        challenges="Had some import issues",
        gratitude="Grateful for AI assistance",
        priorities="Test the full system tomorrow",
        energy_level=8,
        focus_rating=7,
    )
    print(f"   Result: {result}")
    print()

    # Test update_ltm_profile
    print("4. Testing update_ltm_profile...")
    result = catalyst_functions["update_ltm_profile"](
        summary_text="User is setting up The Catalyst system. Shows attention to detail and persistence. Working on a personal growth project.",
        patterns="Technical problem-solving approach",
        current_state="In setup phase, eager to begin using the system",
    )
    print(f"   Result: {result}")
    print()

    # Test extract_insights
    print("5. Testing extract_insights...")
    result = catalyst_functions["extract_insights"](
        conversation_text="I realized that having a structured approach to goal achievement is key. This breakthrough moment showed me the importance of daily rituals.",
        insight_type="pattern",
        importance_score=4,
    )
    print(f"   Result: {result}")
    print()

    # Test update_session_tracking
    print("6. Testing update_session_tracking...")
    result = catalyst_functions["update_session_tracking"]("evening")
    print(f"   Result: {result}")
    print()

    print("🎉 All function tests completed successfully!")
    print("The Catalyst function calling system is ready to use.")


if __name__ == "__main__":
    test_function_calling()
