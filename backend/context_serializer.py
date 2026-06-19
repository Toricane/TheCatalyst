"""Serialize user context for LLM system prompts (TOON or markdown)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import toons

from .config import CONTEXT_FORMAT
from .schemas import SessionType

INSIGHT_DESCRIPTION_LIMIT = 220
INSIGHT_MAX_COUNT = 4
RECENT_USER_CHAR_LIMIT = 160
RECENT_CATALYST_CHAR_LIMIT = 200

_CONTEXT_FORMAT_VERSION = "toon/v1"


def _trim_text(value: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _prompt_goals(goals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for goal in goals or []:
        rows.append(
            {
                "rank": goal.get("rank"),
                "description": (goal.get("description") or "").strip(),
                "metric": (goal.get("metric") or "").strip(),
                "timeline": (goal.get("timeline") or "").strip(),
            }
        )
    return rows


def _insight_cluster_key(insight: Dict[str, Any]) -> tuple[str, str]:
    return (
        str(insight.get("date_identified") or ""),
        str(insight.get("insight_type") or ""),
    )


def _overlaps_ltm(description: str, ltm_text: str) -> bool:
    desc = (description or "").strip().lower()
    ltm = (ltm_text or "").strip().lower()
    if not desc or not ltm:
        return False
    if len(desc) >= 20 and desc[:80] in ltm:
        return True
    snippet = desc[:40]
    if len(snippet) >= 15 and snippet in ltm:
        return True
    if ":" in desc:
        label = desc.split(":", 1)[0].strip()
        if len(label) >= 8 and label in ltm:
            return True
    words = re.sub(r"[*_]", "", desc).split()
    for length in (4, 3, 2):
        if len(words) >= length:
            phrase = " ".join(words[:length])
            if len(phrase) >= 12 and phrase in ltm:
                return True
    return False


def dedupe_insights(
    insights: List[Dict[str, Any]],
    ltm_text: str,
    *,
    max_count: int = INSIGHT_MAX_COUNT,
) -> List[Dict[str, Any]]:
    """Collapse duplicate insight clusters and drop items already covered by LTM."""

    if not insights:
        return []

    ranked = sorted(
        insights,
        key=lambda item: (
            -(item.get("importance_score") or 0),
            str(item.get("date_identified") or ""),
        ),
    )

    clusters: Dict[tuple[str, str], Dict[str, Any]] = {}
    for insight in ranked:
        key = _insight_cluster_key(insight)
        existing = clusters.get(key)
        if existing is None:
            clusters[key] = insight
            continue
        if (insight.get("importance_score") or 0) > (
            existing.get("importance_score") or 0
        ):
            clusters[key] = insight

    deduped = sorted(
        clusters.values(),
        key=lambda item: (
            -(item.get("importance_score") or 0),
            str(item.get("date_identified") or ""),
        ),
    )

    selected: List[Dict[str, Any]] = []
    for insight in deduped:
        description = (insight.get("description") or "").strip()
        if _overlaps_ltm(description, ltm_text):
            continue
        selected.append(insight)
        if len(selected) >= max_count:
            break
    return selected


def _insight_rows(insights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for insight in insights:
        rows.append(
            {
                "date": insight.get("date_identified") or "",
                "type": insight.get("insight_type") or "general",
                "description": _trim_text(
                    (insight.get("description") or "").strip(),
                    INSIGHT_DESCRIPTION_LIMIT,
                ),
            }
        )
    return rows


def format_goals(goals: List[Dict[str, Any]], *, context_format: str) -> str:
    rows = _prompt_goals(goals)
    if not rows:
        return "No active goals."

    if context_format == "markdown":
        return json.dumps(rows, indent=2)

    payload = {"goals": rows}
    return toons.dumps(payload).strip()


def format_ltm(ltm_profile: Dict[str, Any]) -> str:
    return (ltm_profile.get("full_text") or "").strip() or "No long-term profile yet."


def format_insights(
    insights: List[Dict[str, Any]],
    ltm_text: str,
    *,
    context_format: str,
) -> str:
    selected = dedupe_insights(insights, ltm_text)
    if not selected:
        return "No supplemental insights (LTM already covers recent themes)."

    if context_format == "markdown":
        lines: List[str] = []
        for insight in selected:
            date = insight.get("date_identified") or "unknown"
            insight_type = insight.get("insight_type") or "general"
            description = _trim_text(
                (insight.get("description") or "").strip(),
                INSIGHT_DESCRIPTION_LIMIT,
            )
            lines.append(f"- [{insight_type}] ({date}) {description}")
        return "\n".join(lines)

    payload = {"insights": _insight_rows(selected)}
    return toons.dumps(payload).strip()


def format_recent_conversations(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return ""

    excerpts: List[str] = []
    for entry in entries[-5:]:
        timestamp = entry.get("timestamp") or "Recent"
        user_text = _trim_text((entry.get("user") or "").strip(), RECENT_USER_CHAR_LIMIT)
        catalyst_text = _trim_text(
            (entry.get("catalyst") or "").strip(),
            RECENT_CATALYST_CHAR_LIMIT,
        )
        excerpts.append(
            f'- {timestamp}: User → "{user_text or "…"}" | Catalyst → "{catalyst_text or "…"}"'
        )

    return "### Recent Conversation Highlights:\n" + "\n".join(excerpts) + "\n\n"


def format_session_meta(
    session_type: SessionType,
    generated_at: datetime,
    missed_sessions: List[str],
    *,
    context_format: str,
) -> str:
    date_str = generated_at.strftime("%Y-%m-%d")
    missed = ",".join(missed_sessions) if missed_sessions else "none"

    if context_format == "markdown":
        return (
            f"- Session Type: {session_type.value}\n"
            f"- Current Date: {date_str}\n"
            f"- Missed Sessions: {list(missed_sessions)}"
        )

    payload = {
        "session": session_type.value,
        "date": date_str,
        "missed": missed,
    }
    return toons.dumps(payload).strip()


def build_context_block(
    context: Dict[str, Any],
    session_type: SessionType,
    generated_at: datetime,
    *,
    context_format: Optional[str] = None,
) -> str:
    """Assemble the ## Current Context section for the system prompt."""

    fmt = (context_format or CONTEXT_FORMAT).lower()
    ltm_profile = context.get("ltm_profile") or {}
    ltm_text = ltm_profile.get("full_text") or ""

    goals_block = format_goals(context.get("goals") or [], context_format=fmt)
    ltm_block = format_ltm(ltm_profile)
    insights_block = format_insights(
        context.get("insights") or [],
        ltm_text,
        context_format=fmt,
    )
    recent_block = format_recent_conversations(context.get("recent_conversations") or [])
    session_block = format_session_meta(
        session_type,
        generated_at,
        context.get("missed_sessions") or [],
        context_format=fmt,
    )

    parts = [
        "## Current Context",
        "",
        "### User's Goal Hierarchy:",
        goals_block,
        "",
        "### User's Long-Term Memory Profile:",
        ltm_block,
        "",
        "### Key Insights:",
        insights_block,
        "",
    ]
    if recent_block:
        parts.append(recent_block.rstrip())
        parts.append("")
    parts.extend(
        [
            "### Session Information:",
            session_block,
            "",
        ]
    )
    return "\n".join(parts).rstrip()


def context_format_metadata(context_block: str) -> Dict[str, Any]:
    from .rate_limiter import estimate_tokens

    fmt = CONTEXT_FORMAT.lower()
    return {
        "context_format": _CONTEXT_FORMAT_VERSION if fmt == "toon" else "markdown/v1",
        "context_chars": len(context_block),
        "estimated_context_tokens": estimate_tokens(context_block),
    }
