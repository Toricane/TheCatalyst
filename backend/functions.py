"""Function calling registry used by the AI agent."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List

from google.genai import types
from sqlalchemy import func

from .database import get_session
from .models import DailyLog, Insight, LTMProfile, SessionTracking
from .time_utils import local_today, to_local, utc_now

catalyst_functions: Dict[str, Callable[..., Any]] = {}

_SECTION_ALIASES: Dict[str, List[str]] = {
    "patterns": ["key patterns", "patterns"],
    "challenges": ["recurring challenges", "challenges"],
    "breakthroughs": ["breakthroughs & wins", "breakthroughs", "wins"],
    "personality": ["personality traits", "personality"],
    "current_state": ["current state & momentum", "current state", "momentum"],
}


def _strip_code_fences(text: str | None) -> str:
    """Remove optional Markdown code fences from text."""

    if not text:
        return ""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[\w-]*\s*", "", stripped, count=1)
        if stripped.endswith("```"):
            stripped = stripped[: stripped.rfind("```")]

    return stripped.strip()


def _extract_profile_sections(text: str) -> Dict[str, str]:
    """Extract structured LTM sections from a markdown-formatted profile."""

    if not text:
        return {}

    heading_pattern = re.compile(r"^#{1,6}\s+(.*)$")
    current_heading: str | None = None
    buffer: List[str] = []
    collected: Dict[str, str] = {}

    def _flush_buffer(heading: str | None) -> None:
        if heading is None or not buffer:
            return
        heading_lower = heading.lower()
        content = "\n".join(buffer).strip()
        if not content:
            return
        for field, aliases in _SECTION_ALIASES.items():
            if any(alias in heading_lower for alias in aliases):
                collected[field] = content
                break

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading_match = heading_pattern.match(line.strip())
        if heading_match:
            _flush_buffer(current_heading)
            current_heading = heading_match.group(1).strip()
            buffer = []
            continue

        if current_heading is not None:
            buffer.append(raw_line)

    _flush_buffer(current_heading)
    return collected


def catalyst_function(
    name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a callable for AI function invocation."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        function_name = name or func.__name__
        catalyst_functions[function_name] = func
        return func

    return decorator


@catalyst_function("log_daily_reflection")
def log_daily_reflection(
    wins: str,
    challenges: str,
    gratitude: str,
    priorities: str,
    energy_level: int = 5,
    focus_rating: int = 5,
) -> Dict[str, Any]:
    """Log daily reflection data to the database."""
    with get_session() as session:
        log = (
            session.query(DailyLog).filter(DailyLog.date == local_today()).one_or_none()
        )

        if not log:
            log = DailyLog(date=local_today())
            session.add(log)

        log.wins = wins
        log.challenges = challenges
        log.gratitude = gratitude
        log.next_day_priorities = priorities
        log.energy_level = energy_level
        log.focus_rating = focus_rating

    return {"status": "success", "message": "Daily reflection logged successfully"}


@catalyst_function("update_ltm_profile")
def update_ltm_profile_function(
    summary_text: str | None = None,
    patterns: str = "",
    challenges: str = "",
    breakthroughs: str = "",
    personality: str = "",
    current_state: str = "",
    profile_content: str | None = None,
) -> Dict[str, Any]:
    """Update the long-term memory profile, auto-populating sections when possible."""

    source_text = summary_text or profile_content
    cleaned_summary = _strip_code_fences(source_text)

    if not cleaned_summary:
        raise ValueError(
            "update_ltm_profile requires either summary_text or profile_content"
        )

    derived_sections = _extract_profile_sections(cleaned_summary)

    def _finalize_section(value: str, key: str) -> str:
        candidate = value if value and value.strip() else derived_sections.get(key, "")
        return _strip_code_fences(candidate)

    final_patterns = _finalize_section(patterns, "patterns")
    final_challenges = _finalize_section(challenges, "challenges")
    final_breakthroughs = _finalize_section(breakthroughs, "breakthroughs")
    final_personality = _finalize_section(personality, "personality")
    final_current_state = _finalize_section(current_state, "current_state")

    token_estimate = int(len(cleaned_summary.split()) * 1.3)

    with get_session() as session:
        current_version = session.query(func.max(LTMProfile.version)).scalar() or 0
        new_version = current_version + 1

        profile = LTMProfile(
            summary_text=cleaned_summary,
            patterns_section=final_patterns,
            challenges_section=final_challenges,
            breakthroughs_section=final_breakthroughs,
            personality_section=final_personality,
            current_state_section=final_current_state,
            version=new_version,
            token_count=token_estimate,
        )
        session.add(profile)

    return {
        "status": "success",
        "message": f"LTM profile updated to version {new_version}",
    }


@catalyst_function("extract_insights")
def extract_insights(
    conversation_text: str, insight_type: str = "general", importance_score: int = 3
) -> Dict[str, Any]:
    """Extract and store insights from conversations."""
    key_phrases = {
        "realized",
        "learned",
        "breakthrough",
        "pattern",
        "important",
        "key insight",
        "discovered",
        "understood",
        "aha moment",
    }

    lines = conversation_text.split("\n")
    insights = [
        line.strip()
        for line in lines
        if any(phrase in line.lower() for phrase in key_phrases)
    ]

    with get_session() as session:
        for insight in insights[:3]:
            session.add(
                Insight(
                    insight_type=insight_type,
                    category="conversation",
                    description=insight,
                    importance_score=importance_score,
                )
            )

    return {"status": "success", "insights_extracted": len(insights)}


@catalyst_function("update_session_tracking")
def update_session_tracking(session_type: str) -> Dict[str, Any]:
    """Update session tracking information for morning/evening check-ins."""
    now_utc = utc_now()

    with get_session() as session:
        tracking = (
            session.query(SessionTracking).order_by(SessionTracking.id.desc()).first()
        )

        if not tracking:
            tracking = SessionTracking(streak_count=0, total_sessions=0)
            session.add(tracking)
            session.flush()

        if session_type == "morning":
            tracking.last_morning_session = now_utc
        elif session_type == "evening":
            tracking.last_evening_session = now_utc

        tracking.total_sessions = (tracking.total_sessions or 0) + 1

    return {
        "status": "success",
        "session_type": session_type,
        "timestamp": to_local(now_utc).isoformat(),
    }


def create_function_definitions() -> List[types.FunctionDeclaration]:
    """Create Gemini function declaration objects for registered tools."""
    return [
        types.FunctionDeclaration(
            name="log_daily_reflection",
            description="Log daily reflection with wins, challenges, gratitude, and priorities",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "wins": types.Schema(
                        type=types.Type.STRING,
                        description="Today's wins and accomplishments",
                    ),
                    "challenges": types.Schema(
                        type=types.Type.STRING,
                        description="Today's challenges and obstacles",
                    ),
                    "gratitude": types.Schema(
                        type=types.Type.STRING,
                        description="What the user is grateful for",
                    ),
                    "priorities": types.Schema(
                        type=types.Type.STRING, description="Tomorrow's top priorities"
                    ),
                    "energy_level": types.Schema(
                        type=types.Type.INTEGER, description="Energy level 1-10"
                    ),
                    "focus_rating": types.Schema(
                        type=types.Type.INTEGER, description="Focus rating 1-10"
                    ),
                },
                required=["wins", "challenges", "gratitude", "priorities"],
            ),
        ),
        types.FunctionDeclaration(
            name="update_ltm_profile",
            description="Update the long-term memory profile with new insights",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "summary_text": types.Schema(
                        type=types.Type.STRING,
                        description="Complete updated profile summary",
                    ),
                    "patterns": types.Schema(
                        type=types.Type.STRING,
                        description="Identified behavioral patterns",
                    ),
                    "challenges": types.Schema(
                        type=types.Type.STRING, description="Recurring challenges"
                    ),
                    "breakthroughs": types.Schema(
                        type=types.Type.STRING, description="Key breakthroughs and wins"
                    ),
                    "personality": types.Schema(
                        type=types.Type.STRING, description="Personality insights"
                    ),
                    "current_state": types.Schema(
                        type=types.Type.STRING, description="Current state and momentum"
                    ),
                    "profile_content": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Optional alias for summary_text that allows the model to "
                            "pass the entire profile markdown for auto-section parsing"
                        ),
                    ),
                },
                required=["summary_text"],
            ),
        ),
        types.FunctionDeclaration(
            name="extract_insights",
            description="Extract and store insights from the conversation",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "conversation_text": types.Schema(
                        type=types.Type.STRING,
                        description="The conversation text to analyze",
                    ),
                    "insight_type": types.Schema(
                        type=types.Type.STRING,
                        description="Type of insights (pattern, breakthrough, challenge)",
                    ),
                    "importance_score": types.Schema(
                        type=types.Type.INTEGER, description="Importance score 1-5"
                    ),
                },
                required=["conversation_text"],
            ),
        ),
        types.FunctionDeclaration(
            name="update_session_tracking",
            description="Update session tracking information",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "session_type": types.Schema(
                        type=types.Type.STRING,
                        description="Type of session (morning, evening, general)",
                    ),
                },
                required=["session_type"],
            ),
        ),
    ]
