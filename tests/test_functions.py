#!/usr/bin/env python3
"""
Test script for The Catalyst function calling system
"""

import contextlib
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_backend_modules() -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    """Reload backend modules so they pick up the current DATABASE_URL."""

    import backend.config as config_module
    import backend.database as database_module
    import backend.functions as functions_module
    import backend.models as models_module

    config_module = importlib.reload(config_module)
    database_module = importlib.reload(database_module)
    models_module = importlib.reload(models_module)
    functions_module = importlib.reload(functions_module)

    return config_module, database_module, models_module, functions_module


def _cleanup_test_database(
    temp_dir: Path,
    temp_db_path: Path,
    original_db_url: str | None,
    database_module: ModuleType | None,
) -> None:
    """Remove the temporary database and restore the original configuration."""

    if database_module is not None:
        with contextlib.suppress(Exception):
            database_module.SessionLocal.remove()
        with contextlib.suppress(Exception):
            database_module.engine.dispose()

    with contextlib.suppress(FileNotFoundError):
        temp_db_path.unlink()
    shutil.rmtree(temp_dir, ignore_errors=True)

    if original_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = original_db_url

    with contextlib.suppress(Exception):
        _reload_backend_modules()


def test_function_calling():
    """Test the function calling system."""

    temp_dir = Path(tempfile.mkdtemp(prefix="catalyst-test-db-"))
    temp_db_path = temp_dir / "catalyst_test.db"
    original_db_url = os.environ.get("DATABASE_URL")
    database_module: ModuleType | None = None

    try:
        os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_path.as_posix()}"

        _, database_module, _, functions_module = _reload_backend_modules()
        init_database = database_module.init_database
        catalyst_functions = functions_module.catalyst_functions

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
            summary_text=(
                "User is setting up The Catalyst system. Shows attention to detail and "
                "persistence. Working on a personal growth project."
            ),
            patterns="Technical problem-solving approach",
            current_state="In setup phase, eager to begin using the system",
        )
        print(f"   Result: {result}")
        print()

        # Test extract_insights
        print("5. Testing extract_insights...")
        result = catalyst_functions["extract_insights"](
            conversation_text=(
                "I realized that having a structured approach to goal achievement is key. "
                "This breakthrough moment showed me the importance of daily rituals."
            ),
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
    finally:
        _cleanup_test_database(temp_dir, temp_db_path, original_db_url, database_module)


if __name__ == "__main__":
    test_function_calling()
