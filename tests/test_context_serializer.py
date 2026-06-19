"""Tests for context serialization (TOON input path)."""

from datetime import datetime, timezone

import pytest

from backend.context_serializer import (
    build_context_block,
    dedupe_insights,
    format_goals,
)
from backend.schemas import SessionType


LTM_TEXT = """## Overview & North Star
North Star goal and overview.

## Key Patterns
* **Reflect or Bleed:** Active reflection stabilizes performance.

## Current State & Momentum
* **Momentum:** High."""


def _fixture_context():
    return {
        "goals": [
            {
                "id": 1,
                "description": "UBC Engineering Physics admission",
                "metric": "4.33 GPA target",
                "timeline": "Apr 2026",
                "rank": 1,
                "created_at": "2025-09-30T13:31:16-07:00",
            }
        ],
        "ltm_profile": {
            "full_text": LTM_TEXT,
            "patterns": "* **Reflect or Bleed:** duplicate",
            "current_state": "* **Momentum:** duplicate",
        },
        "insights": [
            {
                "id": 13,
                "insight_type": "pattern",
                "category": "conversation",
                "description": "Reflect or Bleed: skipped reflection after Physics 76%",
                "importance_score": 5,
                "date_identified": "2025-12-27",
            },
            {
                "id": 12,
                "insight_type": "pattern",
                "category": "conversation",
                "description": "Reflect or Bleed: failing to process the 76% Physics midterm",
                "importance_score": 5,
                "date_identified": "2025-12-27",
            },
            {
                "id": 10,
                "insight_type": "breakthrough",
                "category": "conversation",
                "description": "Accelerate squad call validation",
                "importance_score": 5,
                "date_identified": "2025-11-10",
            },
        ],
        "missed_sessions": ["morning", "evening"],
        "recent_conversations": [],
    }


def test_build_context_block_dedupes_ltm_sections():
    block = build_context_block(
        _fixture_context(),
        SessionType.CATCH_UP,
        datetime(2026, 6, 18, tzinfo=timezone.utc),
        context_format="toon",
    )
    assert "### Recent Patterns Identified" not in block
    assert "### Current State:" not in block or "### Current State & Momentum" in block
    assert block.count("Reflect or Bleed") == 1


def test_build_context_block_uses_toon_goals_without_db_fields():
    block = build_context_block(
        _fixture_context(),
        SessionType.CATCH_UP,
        datetime(2026, 6, 18, tzinfo=timezone.utc),
        context_format="toon",
    )
    assert "goals[" in block
    assert '"id"' not in block
    assert "created_at" not in block


def test_dedupe_insights_collapses_same_day_type_and_ltm_overlap():
    context = _fixture_context()
    selected = dedupe_insights(context["insights"], LTM_TEXT)
    assert len(selected) == 1
    assert selected[0]["insight_type"] == "breakthrough"


def test_toon_goals_shorter_than_pretty_json(monkeypatch):
    goals = _fixture_context()["goals"]
    monkeypatch.setattr("backend.context_serializer.CONTEXT_FORMAT", "toon")
    toon_text = format_goals(goals, context_format="toon")
    markdown_text = format_goals(goals, context_format="markdown")
    assert len(toon_text) < len(markdown_text)


def test_build_context_block_smaller_than_legacy_layout():
    context = _fixture_context()
    generated_at = datetime(2026, 6, 18, tzinfo=timezone.utc)

    new_block = build_context_block(
        context, SessionType.CATCH_UP, generated_at, context_format="toon"
    )

    legacy_insights = "\n".join(
        f"- [pattern] ({i['date_identified']}) {i['description']}"
        for i in context["insights"][:6]
    )
    legacy = (
        "## Current Context\n\n"
        f"### User's Goal Hierarchy:\n{__import__('json').dumps(context['goals'], indent=2)}\n\n"
        f"### User's Long-Term Memory Profile:\n{context['ltm_profile']['full_text']}\n\n"
        f"### Recent Patterns Identified:\n{context['ltm_profile']['patterns']}\n\n"
        f"### Current State:\n{context['ltm_profile']['current_state']}\n\n"
        f"### Key Insights:\n{legacy_insights}\n\n"
        "### Session Information:\n- Session Type: catch_up\n"
        "- Current Date: 2026-06-18\n"
        "- Missed Sessions: ['morning', 'evening']\n"
    )

    assert len(new_block) < len(legacy)
