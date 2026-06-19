"""Application configuration and constants for The Catalyst backend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Final

from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Directories
BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent
DATA_DIR: Final[Path] = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database configuration
DEFAULT_DATABASE_URL = f"sqlite:///{(DATA_DIR / 'catalyst.db').as_posix()}"
DATABASE_URL: Final[str] = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

# AI configuration — CLOD primary, Gemini fallback
CLOD_API_KEY: Final[str] = os.getenv("CLOD_API_KEY", "")
CLOD_API_BASE: Final[str] = os.getenv("CLOD_API_BASE", "https://api.clod.io/v1")
MODEL_NAME: Final[str] = os.getenv("MODEL_NAME", "GPT OSS 120B")
ALT_MODEL_NAME: Final[str] = os.getenv("ALT_MODEL_NAME", "gemini-2.5-flash")
GEMINI_API_KEY: Final[str] = os.getenv("GEMINI_API_KEY", "")
SHOW_THINKING: Final[bool] = os.getenv("SHOW_THINKING", "false").lower() == "true"


def _env_prefix(model: str) -> str:
    """Convert a model name into an uppercase env prefix."""

    return (
        model.upper()
        .replace("-", "_")
        .replace(".", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )


_DEFAULT_RATE_LIMITS: Final[Dict[str, Dict[str, int]]] = {
    # CLOD free tier: 100 RPD documented; RPM/TPM not published — disabled client-side
    "GPT OSS 120B": {"rpm": 0, "tpm": 0, "rpd": 100},
    "gemini-2.5-flash": {"rpm": 10, "tpm": 250_000, "rpd": 250},
}


def _load_rate_limit(model: str, defaults: Dict[str, int]) -> Dict[str, int]:
    prefix = _env_prefix(model)
    return {
        "rpm": int(os.getenv(f"{prefix}_RPM", str(defaults.get("rpm", 0)))),
        "tpm": int(os.getenv(f"{prefix}_TPM", str(defaults.get("tpm", 0)))),
        "rpd": int(os.getenv(f"{prefix}_RPD", str(defaults.get("rpd", 0)))),
    }


MODEL_RATE_LIMITS: Final[Dict[str, Dict[str, int]]] = {
    model: _load_rate_limit(model, limits)
    for model, limits in _DEFAULT_RATE_LIMITS.items()
}

# Memory management constants
LTM_TOKEN_LIMIT: Final[int] = int(os.getenv("LTM_TOKEN_LIMIT", 2000))
CATCH_UP_THRESHOLD_HOURS: Final[int] = int(os.getenv("CATCH_UP_THRESHOLD", 36))

# Prompt files
PROMPTS_DIR: Final[Path] = BASE_DIR / "prompts"
SYSTEM_PROMPT_PATH: Final[Path] = PROMPTS_DIR / "system_prompt.md"
