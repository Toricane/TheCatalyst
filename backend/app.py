"""FastAPI application for The Catalyst backend."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict, Generator, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .catalyst_ai import (
    _make_api_call_with_retry,
    generate_catalyst_response,
    get_session_instructions,
    update_ltm_memory,
)
from .config import ALT_MODEL_NAME, GEMINI_API_KEY, MODEL_NAME, SHOW_THINKING
from .database import SessionLocal, get_session, init_database
from .functions import create_function_definitions, update_session_tracking
from .memory_manager import (
    check_for_missed_sessions,
    get_current_ltm_profile,
    get_goals_hierarchy,
)
from .rate_limiter import estimate_tokens, rate_limiter
from .schemas import (
    ChatMessage,
    ChatResponse,
    Goal,
    GoalUpdate,
    GreetingRequest,
    SessionType,
)
from .time_utils import local_now, local_today, to_local, utc_now

RECENT_CONVERSATION_CHAR_LIMIT = 16000


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover - startup/shutdown glue
    init_database()
    print("🔥 The Catalyst is online - FastAPI backend ready")
    yield
    print("The Catalyst backend shutting down...")


app = FastAPI(title="The Catalyst", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "active",
        "message": "The Catalyst is ready",
        "version": "2.0",
        "model": MODEL_NAME,
    }


@app.post("/initialize", response_model=ChatResponse)
async def initialize_catalyst(
    goal: Goal, db: Session = Depends(get_db)
) -> ChatResponse:
    goal_row = models.Goal(
        description=goal.description,
        metric=goal.metric,
        timeline=goal.timeline,
        rank=goal.rank,
    )
    db.add(goal_row)

    initial_profile = f"""# USER PROFILE - The Catalyst Memory System

## Overview & North Star
- Primary Goal: {goal.description}
- Success Metric: {goal.metric or "Not specified"}
- Timeline: {goal.timeline or "Not specified"}
- Start Date: {local_today()}
- Initial Commitment Level: High

## Key Patterns
- [To be discovered through interaction]

## Recurring Challenges
- [To be identified through daily reflections]

## Breakthroughs & Wins
- Day 1: Set ambitious goal and committed to The Catalyst process

## Personality Traits
- Ambitious enough to seek AI mentorship
- Action-oriented (chose to start today)

## Current State & Momentum
- Status: Ignition phase - full of potential energy
- Next Focus: Establish daily ritual and build momentum
- Energy: Fresh and ready to begin
"""

    profile_row = models.LTMProfile(
        summary_text=initial_profile,
        version=1,
        token_count=len(initial_profile.split()),
    )
    db.add(profile_row)

    tracking = models.SessionTracking(streak_count=0, total_sessions=0)
    db.add(tracking)

    db.commit()

    context = {
        "goals": [
            {
                "description": goal.description,
                "metric": goal.metric,
                "timeline": goal.timeline,
                "rank": goal.rank,
            }
        ],
        "ltm_profile": {
            "full_text": initial_profile,
            "patterns": "",
            "challenges": "",
            "breakthroughs": "",
            "personality": "",
            "current_state": "",
        },
    }

    goal_prompt = (
        f"I want to achieve: {goal.description}\n"
        f"Success metric: {goal.metric or 'Not specified'}\n"
        f"Timeline: {goal.timeline or 'Not specified'}\n"
        f"Priority rank: {goal.rank if goal.rank is not None else 'Not ranked'}"
    )

    response = await generate_catalyst_response(
        goal_prompt,
        SessionType.INITIALIZATION,
        context,
    )

    return ChatResponse(
        response=response["response"],
        memory_updated=True,
        session_type=SessionType.INITIALIZATION.value,
        thinking=response.get("thinking") if SHOW_THINKING else None,
        model=response.get("model"),
    )


@app.post("/initial-greeting", response_model=ChatResponse)
async def get_initial_greeting(
    request: GreetingRequest, db: Session = Depends(get_db)
) -> ChatResponse:
    """Generate a personalized initial greeting for users with existing goals."""
    missed_info = check_for_missed_sessions(db)
    ltm_profile = get_current_ltm_profile(db)
    goals = get_goals_hierarchy(db)

    recent_cutoff = utc_now() - timedelta(hours=48)
    recent_records = (
        db.query(models.Conversation)
        .filter(models.Conversation.created_at >= recent_cutoff)
        .order_by(models.Conversation.created_at.desc())
        .limit(8)
        .all()
    )

    current_date = local_today()
    current_time = local_now()
    conversation_entries: List[
        Tuple[Dict[str, Any], Optional[datetime], Optional[str]]
    ] = []
    hours_window = 48
    for record in reversed(recent_records):
        messages = json.loads(record.messages) if record.messages else {}
        created_local = to_local(record.created_at)
        if created_local:
            days_ago = (current_date - created_local.date()).days
            if days_ago == 0:
                relative_prefix = "Today"
            elif days_ago == 1:
                relative_prefix = "Yesterday"
            elif days_ago > 1:
                relative_prefix = f"{days_ago} days ago"
            elif days_ago == -1:
                relative_prefix = "Tomorrow"
            elif days_ago < -1:
                relative_prefix = f"In {abs(days_ago)} days"
            else:
                relative_prefix = created_local.strftime("%A")

            timestamp = (
                f"{relative_prefix} - {created_local.strftime('%b %d %I:%M %p')}"
            )
        else:
            timestamp = "Unknown time"
        user_snippet = (messages.get("user", "") or "").strip()
        catalyst_snippet = (messages.get("catalyst", "") or "").strip()

        entry = {
            "id": record.id,
            "timestamp": created_local.isoformat() if created_local else None,
            "user": user_snippet,
            "catalyst": catalyst_snippet,
        }

        summary_line: Optional[str] = None
        if user_snippet or catalyst_snippet:
            summary_line = (
                f'- {timestamp}: User "{user_snippet or "..."}"; '
                f'Catalyst "{catalyst_snippet or "..."}"'
            )

        conversation_entries.append((entry, created_local, summary_line))

    def _conversation_character_count(
        items: List[Tuple[Dict[str, Any], Optional[datetime], Optional[str]]],
    ) -> int:
        return sum(
            len((entry.get("user") or "")) + len((entry.get("catalyst") or ""))
            for entry, _, _ in items
        )

    total_chars = _conversation_character_count(conversation_entries)
    if total_chars > RECENT_CONVERSATION_CHAR_LIMIT:
        twenty_four_hours_ago = current_time - timedelta(hours=24)
        filtered_entries = [
            (entry, created_local, summary)
            for entry, created_local, summary in conversation_entries
            if created_local and created_local >= twenty_four_hours_ago
        ]
        if filtered_entries:
            conversation_entries = filtered_entries
            total_chars = _conversation_character_count(conversation_entries)
            hours_window = min(hours_window, 24)

        if total_chars > RECENT_CONVERSATION_CHAR_LIMIT and conversation_entries:
            trimmed_entries: List[
                Tuple[Dict[str, Any], Optional[datetime], Optional[str]]
            ] = []
            running_total = 0
            for entry, created_local, summary in reversed(conversation_entries):
                entry_length = len(entry.get("user") or "") + len(
                    entry.get("catalyst") or ""
                )
                if (
                    running_total + entry_length > RECENT_CONVERSATION_CHAR_LIMIT
                    and trimmed_entries
                ):
                    continue
                trimmed_entries.append((entry, created_local, summary))
                running_total += entry_length
                if running_total >= RECENT_CONVERSATION_CHAR_LIMIT:
                    break
            conversation_entries = list(reversed(trimmed_entries))

    recent_conversations = [entry for entry, _, _ in conversation_entries]
    recent_summary_lines = [
        summary for _, _, summary in conversation_entries if summary
    ]

    timestamps = [
        created_local for _, created_local, _ in conversation_entries if created_local
    ]
    if timestamps:
        earliest = min(timestamps)
        delta_hours = (current_time - earliest).total_seconds() / 3600
        if delta_hours <= 0:
            hours_window = min(hours_window, 1)
        else:
            hours_window = min(hours_window, max(1, ceil(delta_hours)))

    recent_hours = int(hours_window)

    if not goals:
        return ChatResponse(
            response="Welcome. I'm The Catalyst. Let's ignite your next breakthrough.",
            memory_updated=False,
            session_type=SessionType.GENERAL.value,
        )

    session_type = request.session_type

    # Check if we need a catch-up session
    if missed_info["needs_catchup"] and session_type in {
        SessionType.MORNING,
        SessionType.EVENING,
    }:
        session_type = SessionType.CATCH_UP

    print(f"{session_type=}")

    context = {
        "goals": goals,
        "ltm_profile": ltm_profile,
        "missed_sessions": missed_info.get("missed_sessions", []),
        "recent_conversations": recent_conversations,
    }

    # Create a contextual greeting message based on time and user's situation
    if recent_summary_lines:
        recent_activity_section = "\n".join(recent_summary_lines)
    else:
        recent_activity_section = (
            f"- No conversations recorded in the last {recent_hours} hours."
        )
    greeting_prompt = f"""Generate a personalized initial greeting for the user. This is their first interaction in this new chat session.

Create a warm, motivating greeting that acknowledges:
1. The current time/day context
2. Their existing commitment to their North Star
3. Sets an energetic, focused tone for the session
4. If recent conversations exist, mention what was discussed and highlight in exact words what the user said they wanted to do, if applicable
5. Includes a brief check-in or prompt to get them engaged

Keep it concise but inspiring.

Current context:
- Date: {current_time.strftime("%A, %B %d, %Y")}
- Time: {current_time.strftime("%I:%M %p")}
- Session type: {session_type.value}
- User has established North Star goal: {goals[0]["description"] if goals else "None"}
- Recent conversations (last {recent_hours}h):
---

{recent_activity_section}

---
"""

    response = await generate_catalyst_response(
        greeting_prompt,
        session_type,
        context,
        primary_model=ALT_MODEL_NAME,
    )

    # Persist the initial greeting so future chats can reference it
    greeting_record = models.Conversation(
        session_type=session_type.value,
        messages=json.dumps(
            {
                "user": None,
                "catalyst": response["response"],
                "timestamp": utc_now().isoformat(),
                "function_calls": response.get("function_calls", []),
                "model": response.get("model"),
                "initial_greeting": True,
            }
        ),
        thinking_log=response.get("thinking") or "",
    )
    db.add(greeting_record)
    db.commit()

    return ChatResponse(
        response=response["response"],
        memory_updated=False,
        session_type=session_type.value,
        thinking=response.get("thinking") if SHOW_THINKING else None,
        model=response.get("model"),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat_with_catalyst(
    message: ChatMessage,
    db: Session = Depends(get_db),
) -> ChatResponse:
    missed_info = check_for_missed_sessions(db)
    actual_session = message.session_type

    if missed_info["needs_catchup"] and message.session_type in {
        SessionType.MORNING,
        SessionType.EVENING,
    }:
        actual_session = SessionType.CATCH_UP

    print(f"{actual_session=}")

    ltm_profile = get_current_ltm_profile(db)
    goals = get_goals_hierarchy(db)

    if not goals:
        return ChatResponse(
            response="I notice you haven't set your North Star goal yet. Let's start there - what extraordinary outcome do you want to achieve?",
            memory_updated=False,
            session_type=actual_session.value,
        )

    recent_records = (
        db.query(models.Conversation)
        .order_by(models.Conversation.created_at.desc())
        .limit(8)
        .all()
    )

    recent_conversations: List[Dict[str, Any]] = []
    for record in reversed(recent_records):
        try:
            messages = json.loads(record.messages) if record.messages else {}
        except json.JSONDecodeError:
            messages = {}

        user_text = messages.get("user") or ""
        catalyst_text = messages.get("catalyst") or ""
        if not user_text and not catalyst_text:
            continue

        recent_conversations.append(
            {
                "session_type": record.session_type,
                "user": user_text,
                "catalyst": catalyst_text,
                "timestamp": messages.get("timestamp")
                or (
                    to_local(record.created_at).isoformat()
                    if record.created_at
                    else None
                ),
            }
        )

    context = {
        "goals": goals,
        "ltm_profile": ltm_profile,
        "missed_sessions": missed_info.get("missed_sessions", []),
        "recent_conversations": recent_conversations,
    }

    response = await generate_catalyst_response(
        message.message, actual_session, context
    )
    memory_updated = response["memory_updated"]

    conversation = models.Conversation(
        session_type=actual_session.value,
        messages=json.dumps(
            {
                "user": message.message,
                "catalyst": response["response"],
                "timestamp": utc_now().isoformat(),
                "function_calls": response.get("function_calls", []),
                "model": response.get("model"),
            }
        ),
        thinking_log=response.get("thinking") or "",
    )
    db.add(conversation)

    if actual_session in {SessionType.MORNING, SessionType.EVENING}:
        update_session_tracking(actual_session.value)

    if actual_session == SessionType.MORNING:
        log = (
            db.query(models.DailyLog)
            .filter(models.DailyLog.date == local_today())
            .one_or_none()
        )
        if not log:
            log = models.DailyLog(date=local_today())
            db.add(log)
        log.morning_completed = True
        log.morning_intention = message.message

    if actual_session == SessionType.EVENING:
        log = (
            db.query(models.DailyLog)
            .filter(models.DailyLog.date == local_today())
            .one_or_none()
        )
        if not log:
            log = models.DailyLog(date=local_today())
            db.add(log)
        log.evening_completed = True
        log.evening_reflection = message.message

    db.commit()

    if actual_session == SessionType.EVENING:
        with get_session() as memory_session:
            updated = await update_ltm_memory(
                message.message,
                response["response"],
                context,
                memory_session,
            )
            memory_updated = memory_updated or updated

    return ChatResponse(
        response=response["response"],
        memory_updated=memory_updated,
        session_type=actual_session.value,
        thinking=response.get("thinking") if SHOW_THINKING else None,
        model=response.get("model"),
    )


@app.get("/goals")
async def get_goals(db: Session = Depends(get_db)) -> Dict[str, Any]:
    goals = get_goals_hierarchy(db)
    return {
        "goals": goals,
        "north_star": goals[0] if goals else None,
        "total": len(goals),
    }


@app.put("/goals/{goal_id}")
async def update_goal(
    goal_id: int, update: GoalUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    goal = db.query(models.Goal).filter(models.Goal.id == goal_id).one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if update.rank is not None:
        goal.rank = update.rank
    if update.is_active is not None:
        goal.is_active = update.is_active

    db.commit()
    return {"status": "success", "goal_id": goal_id}


@app.get("/memory/profile")
async def get_memory_profile(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return get_current_ltm_profile(db)


@app.get("/logs/recent")
async def get_recent_logs(
    days: int = 7, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    cutoff = local_today() - timedelta(days=days)
    logs = (
        db.query(models.DailyLog)
        .filter(models.DailyLog.date >= cutoff)
        .order_by(models.DailyLog.date.desc())
        .all()
    )

    return [
        {
            "id": log.id,
            "date": log.date.isoformat() if log.date else None,
            "morning_completed": log.morning_completed,
            "evening_completed": log.evening_completed,
            "morning_intention": log.morning_intention,
            "evening_reflection": log.evening_reflection,
            "wins": log.wins,
            "challenges": log.challenges,
            "gratitude": log.gratitude,
            "next_day_priorities": log.next_day_priorities,
            "energy_level": log.energy_level,
            "focus_rating": log.focus_rating,
        }
        for log in logs
    ]


@app.get("/insights")
async def get_insights(
    limit: int = 10, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    insights = (
        db.query(models.Insight)
        .order_by(
            models.Insight.importance_score.desc(),
            models.Insight.date_identified.desc(),
        )
        .limit(limit)
        .all()
    )
    return [
        {
            "id": insight.id,
            "insight_type": insight.insight_type,
            "category": insight.category,
            "description": insight.description,
            "importance_score": insight.importance_score,
            "date_identified": insight.date_identified.isoformat()
            if insight.date_identified
            else None,
        }
        for insight in insights
    ]


@app.get("/stats")
async def get_user_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    tracking = (
        db.query(models.SessionTracking)
        .order_by(models.SessionTracking.id.desc())
        .first()
    )

    thirty_days_ago = local_today() - timedelta(days=30)

    stats = (
        db.query(
            func.count(models.DailyLog.id).label("total_days"),
            func.sum(func.coalesce(models.DailyLog.morning_completed, 0)).label(
                "mornings_completed"
            ),
            func.sum(func.coalesce(models.DailyLog.evening_completed, 0)).label(
                "evenings_completed"
            ),
            func.avg(models.DailyLog.energy_level).label("avg_energy"),
            func.avg(models.DailyLog.focus_rating).label("avg_focus"),
        )
        .filter(models.DailyLog.date >= thirty_days_ago)
        .one()
    )

    total_days = stats.total_days or 0
    divisor = total_days if total_days else 1

    return {
        "streak": tracking.streak_count
        if tracking and tracking.streak_count is not None
        else 0,
        "total_sessions": tracking.total_sessions
        if tracking and tracking.total_sessions is not None
        else 0,
        "completion_rate": {
            "morning": (stats.mornings_completed or 0) / divisor * 100,
            "evening": (stats.evenings_completed or 0) / divisor * 100,
        },
        "average_energy": float(stats.avg_energy or 0),
        "average_focus": float(stats.avg_focus or 0),
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        goal_count = db.query(models.Goal).count()
        memory_count = db.query(models.LTMProfile).count()
        return {
            "status": "healthy",
            "version": "2.0",
            "database": "connected",
            "goals_count": goal_count,
            "memory_profiles": memory_count,
            "function_calling": "enabled",
            "ai_model": MODEL_NAME,
            "rate_limits": {
                model: limits for model, limits in rate_limiter._limits.items()
            },
        }
    except Exception as exc:  # pragma: no cover
        return {"status": "unhealthy", "error": str(exc), "version": "2.0"}


@app.get("/conversations/recent")
async def get_recent_conversations(
    limit: int = 5, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    records = (
        db.query(models.Conversation)
        .order_by(models.Conversation.created_at.desc())
        .limit(limit)
        .all()
    )

    conversations: List[Dict[str, Any]] = []
    for record in records:
        messages = json.loads(record.messages) if record.messages else {}
        conversations.append(
            {
                "id": record.id,
                "session_type": record.session_type,
                "timestamp": (
                    to_local(record.created_at).isoformat()
                    if record.created_at
                    else None
                ),
                "user_message": messages.get("user", ""),
                "catalyst_response": (messages.get("catalyst", "")[:200] + "...")
                if messages.get("catalyst")
                else "",
                "function_calls": len(messages.get("function_calls", [])),
            }
        )
    return conversations


@app.get("/test/functions")
async def test_function_calling() -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")

    try:
        function_declarations = create_function_definitions()
        tools = [types.Tool(function_declarations=function_declarations)]

        client = genai.Client(api_key=GEMINI_API_KEY)
        test_message = "Please update my session tracking for a morning session."
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text=test_message)])
        ]
        config = types.GenerateContentConfig(
            temperature=0.3,
            tools=tools,
            response_modalities=["TEXT"],
            system_instruction="You are a helpful assistant. If appropriate, use the available functions.",
        )

        estimated = estimate_tokens(test_message)
        response, model_used = await _make_api_call_with_retry(
            client, MODEL_NAME, contents, config, estimated, "test"
        )
        response_text = getattr(response, "text", "") or ""
        await rate_limiter.record_usage(model_used, estimate_tokens(response_text))

        function_calls = []
        text_parts: List[str] = []

        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if getattr(part, "function_call", None):
                    function_calls.append(
                        {
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args)
                            if part.function_call.args
                            else {},
                        }
                    )
                elif getattr(part, "text", None):
                    text_parts.append(part.text)

        return {
            "status": "success",
            "function_declarations_created": len(function_declarations),
            "function_names": [fd.name for fd in function_declarations],
            "test_response": {
                "function_calls": function_calls,
                "text_response": " ".join(text_parts),
                "has_function_call": bool(function_calls),
            },
        }
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "error": str(exc), "error_type": type(exc).__name__}


@app.get("/session/instructions/{session_type}")
async def session_instructions(session_type: SessionType) -> Dict[str, Any]:
    return {
        "session_type": session_type.value,
        "instructions": get_session_instructions(session_type),
    }


@app.get("/rate-limit-status")
async def get_rate_limit_status() -> Dict[str, Any]:
    """Provide current rate limit status for frontend awareness."""
    import time

    status = {}
    current_time = time.monotonic()

    for model_name, limits in rate_limiter._limits.items():
        if model_name not in rate_limiter._states:
            # No usage yet
            status[model_name] = {
                "requests_remaining": limits.get("rpm", 0),
                "tokens_remaining": limits.get("tpm", 0),
                "daily_requests_remaining": limits.get("rpd", 0),
                "estimated_wait_seconds": 0,
                "quota_status": "available",
            }
            continue

        state = rate_limiter._states[model_name]

        # Calculate remaining quotas
        requests_used_this_minute = len(
            [t for t in state.minute_requests if current_time - t < 60.0]
        )

        tokens_used_this_minute = sum(
            [
                count
                for timestamp, count in state.token_events
                if current_time - timestamp < 60.0
            ]
        )

        requests_used_today = len(
            [t for t in state.day_requests if current_time - t < 86400.0]
        )

        rpm_limit = limits.get("rpm", 0)
        tpm_limit = limits.get("tpm", 0)
        rpd_limit = limits.get("rpd", 0)

        requests_remaining = (
            max(0, rpm_limit - requests_used_this_minute) if rpm_limit else float("inf")
        )
        tokens_remaining = (
            max(0, tpm_limit - tokens_used_this_minute) if tpm_limit else float("inf")
        )
        daily_remaining = (
            max(0, rpd_limit - requests_used_today) if rpd_limit else float("inf")
        )

        # Estimate wait time if limits are hit
        estimated_wait = 0
        if requests_remaining == 0 and state.minute_requests:
            estimated_wait = max(
                estimated_wait, 60.0 - (current_time - state.minute_requests[0])
            )
        if tokens_remaining == 0 and state.token_events:
            estimated_wait = max(
                estimated_wait, 60.0 - (current_time - state.token_events[0][0])
            )
        if daily_remaining == 0 and state.day_requests:
            estimated_wait = max(
                estimated_wait, 86400.0 - (current_time - state.day_requests[0])
            )

        # Determine quota status
        if estimated_wait > 0:
            quota_status = "rate_limited"
        elif (requests_remaining / rpm_limit if rpm_limit else 1) < 0.2:
            quota_status = "approaching_limit"
        else:
            quota_status = "available"

        status[model_name] = {
            "requests_remaining": int(requests_remaining)
            if requests_remaining != float("inf")
            else None,
            "tokens_remaining": int(tokens_remaining)
            if tokens_remaining != float("inf")
            else None,
            "daily_requests_remaining": int(daily_remaining)
            if daily_remaining != float("inf")
            else None,
            "estimated_wait_seconds": max(0, int(estimated_wait)),
            "quota_status": quota_status,
            "limits": {
                "rpm": rpm_limit or None,
                "tpm": tpm_limit or None,
                "rpd": rpd_limit or None,
            },
        }

    return {"models": status, "primary_model": MODEL_NAME, "timestamp": current_time}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
