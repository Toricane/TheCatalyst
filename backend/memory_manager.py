"""Memory management utilities for The Catalyst."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import desc
from sqlalchemy.orm import Session

from .models import DailyLog, Goal, Insight, LTMProfile, SessionTracking
from .time_utils import ensure_utc, local_now, to_local


def serialize_ltm_profile(profile: Optional[LTMProfile]) -> Dict[str, Any]:
    """Serialize an ``LTMProfile`` row into the structure used by the AI context."""

    if not profile:
        return {
            "full_text": "",
            "patterns": "",
            "challenges": "",
            "breakthroughs": "",
            "personality": "",
            "current_state": "",
            "_meta": {
                "id": None,
                "version": None,
                "updated_at": None,
                "token_count": None,
            },
        }

    local_updated_at = to_local(profile.last_updated) if profile.last_updated else None

    return {
        "full_text": profile.summary_text or "",
        "patterns": profile.patterns_section or "",
        "challenges": profile.challenges_section or "",
        "breakthroughs": profile.breakthroughs_section or "",
        "personality": profile.personality_section or "",
        "current_state": profile.current_state_section or "",
        "_meta": {
            "id": profile.id,
            "version": profile.version,
            "updated_at": local_updated_at.isoformat() if local_updated_at else None,
            "token_count": profile.token_count,
        },
    }


def _serialize_insight_row(insight: Insight) -> Dict[str, Any]:
    return {
        "id": insight.id,
        "insight_type": insight.insight_type,
        "category": insight.category,
        "description": insight.description,
        "importance_score": insight.importance_score,
        "date_identified": insight.date_identified.isoformat()
        if insight.date_identified
        else None,
    }


def get_recent_insights(session: Session, limit: int = 8) -> List[Dict[str, Any]]:
    """Return the most relevant stored insights for contextual priming."""

    insights = (
        session.query(Insight)
        .order_by(
            Insight.importance_score.desc(),
            Insight.date_identified.desc(),
            Insight.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return [_serialize_insight_row(insight) for insight in insights]


def get_insights_by_ids(
    session: Session, insight_ids: Sequence[int]
) -> List[Dict[str, Any]]:
    """Fetch specific insights while preserving the requested order."""

    if not insight_ids:
        return []

    rows = session.query(Insight).filter(Insight.id.in_(list(insight_ids))).all()
    row_map = {row.id: row for row in rows}
    return [
        _serialize_insight_row(row_map[insight_id])
        for insight_id in insight_ids
        if insight_id in row_map
    ]


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


def get_current_ltm_profile(session: Session) -> Dict[str, Any]:
    """Retrieve the latest long-term memory profile."""
    profile = session.query(LTMProfile).order_by(desc(LTMProfile.version)).first()
    return serialize_ltm_profile(profile)


def get_ltm_profile_by_id(
    session: Session, profile_id: Optional[int]
) -> Dict[str, Any]:
    """Fetch a specific long-term memory profile by primary key."""
    if not profile_id:
        return serialize_ltm_profile(None)

    profile = (
        session.query(LTMProfile)
        .filter(LTMProfile.id == profile_id)
        .order_by(desc(LTMProfile.version))
        .first()
    )
    return serialize_ltm_profile(profile)


def get_ltm_profile_by_version(
    session: Session, version: Optional[int]
) -> Dict[str, Any]:
    """Fetch the most recent profile matching a given version number."""
    if not version:
        return serialize_ltm_profile(None)

    profile = (
        session.query(LTMProfile)
        .filter(LTMProfile.version == version)
        .order_by(desc(LTMProfile.last_updated))
        .first()
    )
    if profile:
        return serialize_ltm_profile(profile)
    return serialize_ltm_profile(None)


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


MORNING_WINDOW_START_HOUR = 4
MORNING_WINDOW_DEADLINE_HOUR = 12
EVENING_WINDOW_START_HOUR = 20
EVENING_WINDOW_DEADLINE_HOUR = 4


def _combine_local(date_: date, hour: int, tzinfo) -> datetime:
    """Return a timezone-aware datetime for the given local date and hour."""

    return datetime.combine(date_, time(hour=hour, tzinfo=tzinfo))


def check_for_missed_sessions(session: Session) -> Dict[str, Any]:
    """Determine whether the user has missed morning or evening sessions."""

    tracking = session.query(SessionTracking).order_by(desc(SessionTracking.id)).first()
    latest_log = (
        session.query(DailyLog).order_by(desc(DailyLog.date), desc(DailyLog.id)).first()
    )

    now_local = local_now()
    tzinfo = now_local.tzinfo or timezone.utc

    today = now_local.date()
    yesterday = today - timedelta(days=1)
    morning_window_start = _combine_local(today, MORNING_WINDOW_START_HOUR, tzinfo)
    morning_deadline = _combine_local(today, MORNING_WINDOW_DEADLINE_HOUR, tzinfo)
    if morning_deadline <= morning_window_start:
        morning_deadline = morning_deadline + timedelta(days=1)
    morning_window_closed = now_local >= morning_deadline

    previous_evening_start = _combine_local(
        yesterday, EVENING_WINDOW_START_HOUR, tzinfo
    )
    previous_evening_deadline = _combine_local(
        today, EVENING_WINDOW_DEADLINE_HOUR, tzinfo
    )
    if previous_evening_deadline <= previous_evening_start:
        previous_evening_deadline = previous_evening_deadline + timedelta(days=1)
    evening_window_closed = now_local >= previous_evening_deadline

    missed_sessions: List[str] = []
    last_check_in_local = None

    if tracking:
        last_morning_local = (
            to_local(tracking.last_morning_session)
            if tracking.last_morning_session
            else None
        )
        last_evening_local = (
            to_local(tracking.last_evening_session)
            if tracking.last_evening_session
            else None
        )

        if morning_window_closed and (
            not last_morning_local or last_morning_local < morning_window_start
        ):
            missed_sessions.append("morning")

        if evening_window_closed and (
            not last_evening_local or last_evening_local < previous_evening_start
        ):
            missed_sessions.append("evening")

        timestamps = [
            ensure_utc(value)
            for value in (tracking.last_morning_session, tracking.last_evening_session)
            if value
        ]
        if timestamps:
            last_check_in_local = to_local(max(timestamps))

    if not tracking and latest_log:
        if morning_window_closed and not latest_log.morning_completed:
            if "morning" not in missed_sessions:
                missed_sessions.append("morning")
        if evening_window_closed and not latest_log.evening_completed:
            if "evening" not in missed_sessions:
                missed_sessions.append("evening")

    needs_catchup = bool(missed_sessions)

    return {
        "needs_catchup": False,  # needs_catchup,
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
