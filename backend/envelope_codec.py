"""Structured model output: TOON-first envelope parsing and prompt instructions."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Tuple

import toons

from .config import ENVELOPE_FORMAT
from .functions import _strip_code_fences

OUTPUT_INSTRUCTIONS_JSON = """
## Response Format (CRITICAL)

Respond with a single JSON object only. No markdown fences, no text outside the JSON.

Schema:
{
  "reply": "<user-facing message — always required>",
  "daily_log": null OR {
    "wins": "...", "challenges": "...", "gratitude": "...", "priorities": "...",
    "energy_level": 1-10, "focus_rating": 1-10
  },
  "memory_update": null OR {
    "should_update": true/false,
    "summary_text": "<full updated LTM markdown profile with ## headings>"
  },
  "insights": null OR [
    {"insight_type": "pattern|breakthrough|challenge", "description": "...", "importance_score": 1-5}
  ]
}

Rules:
- "reply" is the only text the user sees. Always include it.
- Include daily_log only during evening sessions when the user shared reflection content.
- Include memory_update when meaningful profile changes emerged (typically evening). Set should_update false otherwise.
- Include insights only for notable patterns or breakthroughs worth storing long-term.
- Session tracking is handled server-side — never include it in the JSON.
- When updating memory, maintain sections: Overview & North Star, Key Patterns, Recurring Challenges,
  Breakthroughs & Wins, Personality Traits, Current State & Momentum (use ## headings).
"""

OUTPUT_INSTRUCTIONS_TOON = """
## Response Format (CRITICAL)

Respond with TOON only. No markdown fences, no text outside the TOON block.

Example (replace values; use null when a section does not apply):

reply: <user-facing message — always required>
daily_log: null
memory_update: null
insights: null

When daily_log applies:
daily_log:
  wins: "..."
  challenges: "..."
  gratitude: "..."
  priorities: "..."
  energy_level: 7
  focus_rating: 8

When memory_update applies:
memory_update:
  should_update: true
  summary_text: "## Overview & North Star\\n...full profile with ## headings..."

When insights apply:
insights[N]{insight_type,description,importance_score}:
  pattern,Notable pattern description,4

Rules:
- reply is the only text the user sees. Always include it.
- Include daily_log only during evening sessions when the user shared reflection content.
- Include memory_update when meaningful profile changes emerged (typically evening). Set should_update false otherwise.
- Include insights only for notable patterns or breakthroughs worth storing long-term.
- Session tracking is handled server-side — never include it.
- When updating memory, maintain sections: Overview & North Star, Key Patterns, Recurring Challenges,
  Breakthroughs & Wins, Personality Traits, Current State & Momentum (use ## headings).
"""

GREETING_OUTPUT_INSTRUCTIONS = """
## Response Format

Respond with plain text only — a warm, concise greeting. Do NOT use TOON or JSON. Do NOT describe database actions.
"""


def format_output_instructions() -> str:
    if ENVELOPE_FORMAT == "json":
        return OUTPUT_INSTRUCTIONS_JSON
    return OUTPUT_INSTRUCTIONS_TOON


def _strip_envelope_fences(raw_text: str) -> str:
    text = (raw_text or "").strip()
    fence_match = re.match(
        r"^```(?:toon|json)?\s*\n?(.*?)\n?```\s*$",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fence_match:
        return fence_match.group(1).strip()
    return _strip_code_fences(text)


def normalize_envelope(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure envelope dict uses canonical keys for apply_envelope_actions."""

    normalized = dict(data)
    if "reply" not in normalized and "response" in normalized:
        normalized["reply"] = normalized.get("response")
    return normalized


def _parse_json_envelope(text: str) -> Dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return normalize_envelope(data)
    return None


def _parse_toon_envelope(text: str) -> Dict[str, Any] | None:
    try:
        data = toons.loads(text)
    except Exception:
        return None
    if isinstance(data, dict):
        return normalize_envelope(data)
    return None


def parse_envelope(raw_text: str) -> Tuple[str, Dict[str, Any]]:
    """Parse a structured TOON or JSON response; fall back to plain text as reply."""

    text = _strip_envelope_fences(raw_text)

    parsers = (
        [_parse_json_envelope, _parse_toon_envelope]
        if ENVELOPE_FORMAT == "json"
        else [_parse_toon_envelope, _parse_json_envelope]
    )

    for parser in parsers:
        data = parser(text)
        if data is not None:
            reply = (data.get("reply") or "").strip()
            return reply or raw_text.strip(), data

    stripped = raw_text.strip()
    return stripped, {"reply": stripped}


# Backwards-compatible alias used in tests/imports
_parse_structured_envelope = parse_envelope
