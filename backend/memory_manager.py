"""Memory management utilities for The Catalyst."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from sqlalchemy import desc
from sqlalchemy.orm import Session

from .config import CATCH_UP_THRESHOLD_HOURS
from .models import Goal, LTMProfile, SessionTracking
from .time_utils import ensure_utc, to_local, utc_now


def compress_old_memories(text: str, age_days: int) -> str:
    """Compress memories based on age."""
    if age_days < 30:
        return text
    if age_days < 90:
        lines = text.split("\n")
        keywords = {
            "breakthrough",
            "pattern",
            "realized",
            "key",
            "important",
            "shift",
        }
        key_lines = [
            line for line in lines if any(word in line.lower() for word in keywords)
        ]
        return "\n".join(key_lines[:10])
    return f"{text[:200]}..." if len(text) > 200 else text


def get_current_ltm_profile(session: Session) -> Dict[str, str]:
    """Retrieve the latest long-term memory profile."""
    profile = session.query(LTMProfile).order_by(desc(LTMProfile.version)).first()
    if not profile:
        return {
            "full_text": "",
            "patterns": "",
            "challenges": "",
            "breakthroughs": "",
            "personality": "",
            "current_state": "",
        }

    return {
        "full_text": profile.summary_text or "",
        "patterns": profile.patterns_section or "",
        "challenges": profile.challenges_section or "",
        "breakthroughs": profile.breakthroughs_section or "",
        "personality": profile.personality_section or "",
        "current_state": profile.current_state_section or "",
    }


def get_goals_hierarchy(session: Session) -> List[Dict[str, Any]]:
    """Return all active goals ordered by rank and recency."""
    goals = (
        session.query(Goal)
        .filter(Goal.is_active.is_(True))
        .order_by(Goal.rank.asc(), Goal.created_at.desc())
        .all()
    )
    return [
        {
            "id": goal.id,
            "description": goal.description,
            "metric": goal.metric,
            "timeline": goal.timeline,
            "rank": goal.rank,
            "created_at": (
                to_local(goal.created_at).isoformat() if goal.created_at else None
            ),
        }
        for goal in goals
    ]


def check_for_missed_sessions(session: Session) -> Dict[str, Any]:
    """Determine whether the user has missed morning or evening sessions."""
    tracking = session.query(SessionTracking).order_by(desc(SessionTracking.id)).first()
    if not tracking:
        return {"needs_catchup": False, "missed_sessions": []}

    now = utc_now()
    missed_sessions: List[str] = []

    if tracking.last_morning_session:
        last_morning = ensure_utc(tracking.last_morning_session)
        delta = now - last_morning
        if delta.total_seconds() > CATCH_UP_THRESHOLD_HOURS * 3600:
            missed_sessions.append("morning")

    if tracking.last_evening_session:
        last_evening = ensure_utc(tracking.last_evening_session)
        delta = now - last_evening
        if delta.total_seconds() > CATCH_UP_THRESHOLD_HOURS * 3600:
            missed_sessions.append("evening")

    last_check_source = tracking.last_morning_session or tracking.last_evening_session
    last_check_in_local = to_local(last_check_source) if last_check_source else None

    return {
        "needs_catchup": bool(missed_sessions),
        "missed_sessions": missed_sessions,
        "last_check_in": last_check_in_local.isoformat()
        if last_check_in_local
        else None,
    }


def extract_section(text: str, section_name: str) -> str:
    """Extract a block of text belonging to a section heading."""
    lines = text.split("\n")
    section_lines: List[str] = []
    in_section = False
    target = section_name.lower().strip()

    heading_patterns = [
        re.compile(r"^\s*#{1,6}\s+.+"),
        re.compile(r"^\s*\*\*.+?\*\*\s*:?.*$"),
        re.compile(r"^\s*[A-Za-z][\w\s&'\-\/]+\s*:\s*$"),
    ]

    def _is_heading(candidate: str) -> bool:
        return any(pattern.match(candidate) for pattern in heading_patterns)

    for line in lines:
        stripped = line.strip()

        if not in_section:
            if stripped and target in stripped.lower() and _is_heading(stripped):
                in_section = True
            continue

        if _is_heading(stripped) and target not in stripped.lower():
            break

        if stripped or section_lines:
            section_lines.append(line)

    return "\n".join(section_lines[:10]).strip()
