"""FastAPI application for The Catalyst backend."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, Dict, Generator, List, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response
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
    reconstruct_system_prompt,
    update_ltm_memory,
)
from .config import ALT_MODEL_NAME, GEMINI_API_KEY, MODEL_NAME, SHOW_THINKING
from .database import SessionLocal, get_session, init_database
from .functions import create_function_definitions, update_session_tracking
from .memory_manager import (
    check_for_missed_sessions,
    get_current_ltm_profile,
    get_goals_hierarchy,
    get_insights_by_ids,
    get_ltm_profile_by_id,
    get_ltm_profile_by_version,
    get_recent_insights,
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

RECENT_CONVERSATION_CHAR_LIMIT = 24000


def _conversation_id_for_record(
    record: models.Conversation, messages: Dict[str, Any]
) -> str:
    if getattr(record, "conversation_uuid", None):
        return str(record.conversation_uuid)
    conversation_id = messages.get("conversation_id")
    if conversation_id:
        return str(conversation_id)
    return f"legacy-{record.id}"


def _message_timestamp(
    messages: Dict[str, Any], record: models.Conversation
) -> Optional[str]:
    timestamp_str: Optional[str] = messages.get("timestamp")
    if timestamp_str:
        return timestamp_str
    if record.created_at:
        localized = to_local(record.created_at)
        if localized:
            return localized.isoformat()
        return record.created_at.isoformat()
    return None


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _serialize_goal_record(goal: models.Goal) -> Dict[str, Any]:
    created_at_local = to_local(goal.created_at) if goal.created_at else None
    return {
        "id": goal.id,
        "description": goal.description,
        "metric": goal.metric,
        "timeline": goal.timeline,
        "rank": goal.rank,
        "created_at": created_at_local.isoformat() if created_at_local else None,
    }


def _build_context_reference(
    sources: List[Dict[str, Any]],
    goals: List[Dict[str, Any]],
    ltm_profile: Dict[str, Any],
    missed_info: Dict[str, Any],
    insights: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    sequence: List[Dict[str, Any]] = []

    for source in sources:
        source_type = source.get("type")
        if source_type == "record":
            record_id = source.get("record_id")
            if record_id is not None:
                sequence.append({"type": "record", "id": int(record_id)})
        elif source_type == "inline":
            entry = source.get("entry")
            if entry:
                sequence.append({"type": "inline", "entry": dict(entry)})

    ltm_meta = ltm_profile.get("_meta", {}) if isinstance(ltm_profile, dict) else {}

    return {
        "sequence": sequence,
        "ltm_profile": {
            "id": ltm_meta.get("id"),
            "version": ltm_meta.get("version"),
            "updated_at": ltm_meta.get("updated_at"),
        },
        "insight_ids": [
            insight.get("id")
            for insight in (insights or [])
            if insight.get("id") is not None
        ],
        "goal_ids": [goal.get("id") for goal in goals if goal.get("id") is not None],
        "missed_sessions": missed_info.get("missed_sessions", []),
        "generated_at": utc_now().isoformat(),
    }


def _reconstruct_context_from_reference(
    db: Session, reference: Dict[str, Any]
) -> Dict[str, Any]:
    sequence: List[Dict[str, Any]] = reference.get("sequence") or []

    record_ids = [
        item.get("id")
        for item in sequence
        if item.get("type") == "record" and item.get("id") is not None
    ]

    records_map: Dict[int, models.Conversation] = {}
    if record_ids:
        records = (
            db.query(models.Conversation)
            .filter(models.Conversation.id.in_(record_ids))
            .all()
        )
        records_map = {record.id: record for record in records}

    recent_entries: List[Dict[str, Any]] = []
    for item in sequence:
        item_type = item.get("type")
        if item_type == "record":
            record_id = item.get("id")
            record = records_map.get(record_id)
            if not record or not record.messages:
                continue
            try:
                payload = json.loads(record.messages)
            except json.JSONDecodeError:
                payload = {}

            entry: Dict[str, Any] = {
                "session_type": record.session_type,
                "user": (payload.get("user") or ""),
                "catalyst": (payload.get("catalyst") or ""),
                "timestamp": payload.get("timestamp")
                or _message_timestamp(payload, record),
                "conversation_id": _conversation_id_for_record(record, payload),
            }
            if payload.get("initial_greeting"):
                entry["initial_greeting"] = True

            recent_entries.append(entry)

        elif item_type == "inline":
            entry = item.get("entry")
            if entry:
                recent_entries.append(dict(entry))

    goal_ids = reference.get("goal_ids") or []
    goals: List[Dict[str, Any]] = []
    if goal_ids:
        goal_records = db.query(models.Goal).filter(models.Goal.id.in_(goal_ids)).all()
        goal_map = {goal.id: goal for goal in goal_records}
        for goal_id in goal_ids:
            goal_record = goal_map.get(goal_id)
            if goal_record:
                goals.append(_serialize_goal_record(goal_record))

    if not goals:
        goals = get_goals_hierarchy(db)

    ltm_meta = reference.get("ltm_profile") or {}
    ltm_profile: Dict[str, Any]
    profile_id = ltm_meta.get("id")
    profile_version = ltm_meta.get("version")

    if profile_id:
        ltm_profile = get_ltm_profile_by_id(db, profile_id)
    elif profile_version:
        ltm_profile = get_ltm_profile_by_version(db, profile_version)
    else:
        ltm_profile = get_current_ltm_profile(db)

    missed_sessions = reference.get("missed_sessions", [])

    insight_ids = reference.get("insight_ids") or []
    if insight_ids:
        insights = get_insights_by_ids(db, insight_ids)
    else:
        insights = get_recent_insights(db)

    return {
        "goals": goals,
        "ltm_profile": ltm_profile,
        "missed_sessions": missed_sessions,
        "insights": insights,
        "recent_conversations": recent_entries,
    }


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
    db.refresh(goal_row)
    db.refresh(profile_row)

    context = {
        "goals": [_serialize_goal_record(goal_row)],
        "ltm_profile": get_ltm_profile_by_id(db, profile_row.id),
        "insights": get_recent_insights(db),
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

    conversation_id = str(uuid4())
    timestamp = utc_now().isoformat()

    context_reference = _build_context_reference(
        sources=[],
        goals=context.get("goals", []),
        ltm_profile=context.get("ltm_profile", {}),
        missed_info={"missed_sessions": []},
        insights=context.get("insights", []),
    )

    conversation_snapshot = models.Conversation(
        session_type=SessionType.INITIALIZATION.value,
        conversation_uuid=conversation_id,
        messages=json.dumps(
            {
                "user": goal_prompt,
                "catalyst": response["response"],
                "timestamp": timestamp,
                "function_calls": response.get("function_calls", []),
                "model": response.get("model"),
                "conversation_id": conversation_id,
                "is_conversation_start": True,
                "system_prompt_reference": response.get("system_prompt_reference"),
                "context_reference": context_reference,
            }
        ),
        thinking_log=response.get("thinking") or "",
    )
    db.add(conversation_snapshot)
    db.flush()
    message_id = conversation_snapshot.id
    db.commit()

    return ChatResponse(
        response=response["response"],
        memory_updated=True,
        session_type=SessionType.INITIALIZATION.value,
        conversation_id=conversation_id,
        message_id=message_id,
        thinking=response.get("thinking") if SHOW_THINKING else None,
        model=response.get("model"),
        system_prompt=response.get("system_prompt"),
        context_snapshot=response.get("context_snapshot"),
        context_reference=context_reference,
        system_prompt_reference=response.get("system_prompt_reference"),
    )


@app.post("/initial-greeting", response_model=ChatResponse)
async def get_initial_greeting(
    request: GreetingRequest, db: Session = Depends(get_db)
) -> ChatResponse:
    """Generate a personalized initial greeting for users with existing goals."""
    missed_info = check_for_missed_sessions(db)
    ltm_profile = get_current_ltm_profile(db)
    goals = get_goals_hierarchy(db)
    insights = get_recent_insights(db)

    recent_cutoff = utc_now() - timedelta(hours=48)
    recent_records = (
        db.query(models.Conversation)
        .filter(models.Conversation.created_at >= recent_cutoff)
        .order_by(models.Conversation.created_at.desc())
        # .limit(8)
        .all()
    )

    current_date = local_today()
    current_time = local_now()
    conversation_entries: List[Dict[str, Any]] = []
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
            "conversation_id": _conversation_id_for_record(record, messages),
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

        conversation_entries.append(
            {
                "entry": entry,
                "created": created_local,
                "summary": summary_line,
                "source": {"type": "record", "record_id": record.id},
            }
        )

    def _conversation_character_count(items: List[Dict[str, Any]]) -> int:
        return sum(
            len((item["entry"].get("user") or ""))
            + len((item["entry"].get("catalyst") or ""))
            for item in items
        )

    total_chars = _conversation_character_count(conversation_entries)
    if total_chars > RECENT_CONVERSATION_CHAR_LIMIT:
        twenty_four_hours_ago = current_time - timedelta(hours=24)
        filtered_entries = [
            item
            for item in conversation_entries
            if item.get("created") and item["created"] >= twenty_four_hours_ago
        ]
        if filtered_entries:
            conversation_entries = filtered_entries
            total_chars = _conversation_character_count(conversation_entries)
            hours_window = min(hours_window, 24)

        if total_chars > RECENT_CONVERSATION_CHAR_LIMIT and conversation_entries:
            trimmed_entries: List[Dict[str, Any]] = []
            running_total = 0
            for item in reversed(conversation_entries):
                entry = item["entry"]
                entry_length = len(entry.get("user") or "") + len(
                    entry.get("catalyst") or ""
                )
                if (
                    running_total + entry_length > RECENT_CONVERSATION_CHAR_LIMIT
                    and trimmed_entries
                ):
                    continue
                trimmed_entries.append(item)
                running_total += entry_length
                if running_total >= RECENT_CONVERSATION_CHAR_LIMIT:
                    break
            conversation_entries = list(reversed(trimmed_entries))

    recent_conversations = [item["entry"] for item in conversation_entries]
    recent_summary_lines = [
        item["summary"] for item in conversation_entries if item.get("summary")
    ]

    timestamps = [
        item["created"]
        for item in conversation_entries
        if item.get("created") is not None
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

    context_sources = [item["source"] for item in conversation_entries]

    context = {
        "goals": goals,
        "ltm_profile": ltm_profile,
        "missed_sessions": missed_info.get("missed_sessions", []),
        "insights": insights,
        "recent_conversations": recent_conversations,
    }

    context_reference = _build_context_reference(
        sources=context_sources,
        goals=goals,
        ltm_profile=ltm_profile,
        missed_info=missed_info,
        insights=insights,
    )

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

    conversation_id = str(uuid4())
    timestamp = utc_now().isoformat()

    # Persist the initial greeting so future chats can reference it
    greeting_record = models.Conversation(
        session_type=session_type.value,
        conversation_uuid=conversation_id,
        messages=json.dumps(
            {
                "user": None,
                "catalyst": response["response"],
                "timestamp": timestamp,
                "function_calls": response.get("function_calls", []),
                "model": response.get("model"),
                "initial_greeting": True,
                "conversation_id": conversation_id,
                "is_conversation_start": True,
                "system_prompt_reference": response.get("system_prompt_reference"),
                "context_reference": context_reference,
            }
        ),
        thinking_log=response.get("thinking") or "",
    )
    db.add(greeting_record)
    db.flush()
    message_id = greeting_record.id
    db.commit()

    return ChatResponse(
        response=response["response"],
        memory_updated=False,
        session_type=session_type.value,
        conversation_id=conversation_id,
        message_id=message_id,
        thinking=response.get("thinking") if SHOW_THINKING else None,
        model=response.get("model"),
        system_prompt=response.get("system_prompt"),
        context_snapshot=response.get("context_snapshot"),
        context_reference=context_reference,
        system_prompt_reference=response.get("system_prompt_reference"),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat_with_catalyst(
    message: ChatMessage,
    db: Session = Depends(get_db),
) -> ChatResponse:
    missed_info = check_for_missed_sessions(db)
    actual_session = message.session_type

    conversation_id: Optional[str] = message.conversation_id
    if conversation_id is None and message.initial_greeting:
        conversation_id = message.initial_greeting.conversation_id

    created_new_conversation = False
    if conversation_id is None:
        latest_record = (
            db.query(models.Conversation)
            .order_by(models.Conversation.created_at.desc())
            .first()
        )
        if latest_record and latest_record.messages:
            try:
                latest_payload = json.loads(latest_record.messages)
            except json.JSONDecodeError:
                latest_payload = {}
            conversation_id = _conversation_id_for_record(latest_record, latest_payload)
        else:
            conversation_id = str(uuid4())
            created_new_conversation = True

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

    insights = get_recent_insights(db)

    recent_records = (
        db.query(models.Conversation)
        .order_by(models.Conversation.created_at.desc())
        .all()
    )

    raw_entries: List[Dict[str, Any]] = []
    for record in reversed(recent_records):
        try:
            messages = json.loads(record.messages) if record.messages else {}
        except json.JSONDecodeError:
            messages = {}

        user_text = messages.get("user") or ""
        catalyst_text = messages.get("catalyst") or ""
        is_initial_greeting = bool(messages.get("initial_greeting"))

        if not user_text and not catalyst_text and not is_initial_greeting:
            continue

        entry = {
            "session_type": record.session_type,
            "user": user_text,
            "catalyst": catalyst_text,
            "conversation_id": _conversation_id_for_record(record, messages),
            "timestamp": messages.get("timestamp")
            or (to_local(record.created_at).isoformat() if record.created_at else None),
        }

        raw_entries.append(
            {
                "entry": entry,
                "record_id": record.id,
                "is_initial_greeting": is_initial_greeting,
                "has_user_text": bool(user_text.strip()),
            }
        )

    recent_conversations: List[Dict[str, Any]] = []
    context_sources: List[Dict[str, Any]] = []
    pending_greetings: List[Dict[str, Any]] = []
    user_message_seen = False

    for item in raw_entries:
        if item["is_initial_greeting"]:
            if user_message_seen:
                recent_conversations.append(item["entry"])
                context_sources.append(
                    {"type": "record", "record_id": item["record_id"]}
                )
            else:
                pending_greetings.append(item)
            continue

        if pending_greetings:
            for pending in pending_greetings:
                recent_conversations.append(pending["entry"])
                context_sources.append(
                    {"type": "record", "record_id": pending["record_id"]}
                )
            pending_greetings = []

        if item["has_user_text"]:
            user_message_seen = True

        recent_conversations.append(item["entry"])
        context_sources.append({"type": "record", "record_id": item["record_id"]})

    if user_message_seen and pending_greetings:
        for pending in pending_greetings:
            recent_conversations.append(pending["entry"])
            context_sources.append(
                {"type": "record", "record_id": pending["record_id"]}
            )

    greeting_payload = message.initial_greeting
    greeting_session_value: Optional[str] = None
    greeting_timestamp: Optional[str] = None
    if greeting_payload and greeting_payload.text:
        greeting_session = greeting_payload.session_type or actual_session
        greeting_session_value = (
            greeting_session.value
            if isinstance(greeting_session, SessionType)
            else str(greeting_session)
        )
        greeting_timestamp = greeting_payload.timestamp or utc_now().isoformat()
        if greeting_payload.conversation_id is None:
            greeting_payload.conversation_id = conversation_id

        inline_entry = {
            "session_type": greeting_session_value,
            "user": "",
            "catalyst": greeting_payload.text,
            "timestamp": greeting_timestamp,
            "conversation_id": conversation_id,
            "initial_greeting": True,
        }
        recent_conversations.append(inline_entry)
        context_sources.append({"type": "inline", "entry": dict(inline_entry)})

    context = {
        "goals": goals,
        "ltm_profile": ltm_profile,
        "missed_sessions": missed_info.get("missed_sessions", []),
        "insights": insights,
        "recent_conversations": recent_conversations,
    }

    context_reference = _build_context_reference(
        sources=context_sources,
        goals=goals,
        ltm_profile=ltm_profile,
        missed_info=missed_info,
        insights=insights,
    )

    response = await generate_catalyst_response(
        message.message, actual_session, context
    )
    memory_updated = response["memory_updated"]

    if greeting_payload and greeting_payload.text and greeting_session_value:
        greeting_conversation_id = greeting_payload.conversation_id or conversation_id
        greeting_timestamp_value = greeting_timestamp or utc_now().isoformat()

        greeting_already_saved = False
        if greeting_conversation_id:
            existing_greetings = (
                db.query(models.Conversation)
                .filter(
                    models.Conversation.conversation_uuid == greeting_conversation_id
                )
                .all()
            )
            for existing in existing_greetings:
                try:
                    existing_payload = (
                        json.loads(existing.messages) if existing.messages else {}
                    )
                except json.JSONDecodeError:
                    existing_payload = {}
                if existing_payload.get("initial_greeting"):
                    greeting_already_saved = True
                    break

        if not greeting_already_saved:
            greeting_reference = getattr(
                greeting_payload, "context_reference", context_reference
            )
            greeting_record = models.Conversation(
                session_type=greeting_session_value,
                conversation_uuid=greeting_conversation_id,
                messages=json.dumps(
                    {
                        "user": None,
                        "catalyst": greeting_payload.text,
                        "timestamp": greeting_timestamp_value,
                        "function_calls": [],
                        "model": greeting_payload.model,
                        "initial_greeting": True,
                        "conversation_id": greeting_conversation_id,
                        "is_conversation_start": True,
                        "system_prompt_reference": getattr(
                            greeting_payload, "system_prompt_reference", None
                        ),
                        "context_reference": greeting_reference,
                    }
                ),
                thinking_log="",
            )
            db.add(greeting_record)

        greeting_payload.conversation_id = greeting_conversation_id
        greeting_timestamp = greeting_timestamp_value
        created_new_conversation = False

    conversation = models.Conversation(
        session_type=actual_session.value,
        conversation_uuid=conversation_id,
        messages=json.dumps(
            {
                "user": message.message,
                "catalyst": response["response"],
                "timestamp": utc_now().isoformat(),
                "function_calls": response.get("function_calls", []),
                "model": response.get("model"),
                "conversation_id": conversation_id,
                "is_conversation_start": created_new_conversation,
                "system_prompt_reference": response.get("system_prompt_reference"),
                "context_reference": context_reference,
            }
        ),
        thinking_log=response.get("thinking") or "",
    )
    db.add(conversation)
    db.flush()
    message_id = conversation.id

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
        conversation_id=conversation_id,
        message_id=message_id,
        thinking=response.get("thinking") if SHOW_THINKING else None,
        model=response.get("model"),
        system_prompt=response.get("system_prompt"),
        context_snapshot=response.get("context_snapshot"),
        context_reference=context_reference,
        system_prompt_reference=response.get("system_prompt_reference"),
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


@app.get("/conversations")
async def list_conversations(
    limit: Optional[int] = None, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    query = db.query(models.Conversation).order_by(
        models.Conversation.created_at.desc()
    )
    if limit:
        query = query.limit(limit)

    records = query.all()
    grouped: Dict[str, Dict[str, Any]] = {}

    for record in records:
        try:
            messages = json.loads(record.messages) if record.messages else {}
        except json.JSONDecodeError:
            messages = {}

        conversation_id = _conversation_id_for_record(record, messages)
        timestamp_iso = _message_timestamp(messages, record)
        timestamp_dt = _parse_iso_timestamp(timestamp_iso) or to_local(
            record.created_at
        )

        info = grouped.setdefault(
            conversation_id,
            {
                "conversation_id": conversation_id,
                "message_count": 0,
                "preview": "",
                "started_at": timestamp_dt,
                "updated_at": timestamp_dt,
                "session_types": set(),
            },
        )

        info["message_count"] += 1
        if timestamp_dt and (
            info["started_at"] is None or timestamp_dt < info["started_at"]
        ):
            info["started_at"] = timestamp_dt
        if timestamp_dt and (
            info["updated_at"] is None or timestamp_dt > info["updated_at"]
        ):
            info["updated_at"] = timestamp_dt

        if record.session_type:
            info["session_types"].add(record.session_type)

        preview_source = (
            messages.get("user") or messages.get("catalyst") or ""
        ).strip()
        if preview_source and not info["preview"]:
            info["preview"] = preview_source[:160]

    conversations_list: List[Dict[str, Any]] = []
    for data in grouped.values():
        session_types = sorted(data["session_types"])
        conversations_list.append(
            {
                "conversation_id": data["conversation_id"],
                "message_count": data["message_count"],
                "preview": data["preview"],
                "started_at": data["started_at"].isoformat()
                if isinstance(data["started_at"], datetime)
                else data["started_at"],
                "updated_at": data["updated_at"].isoformat()
                if isinstance(data["updated_at"], datetime)
                else data["updated_at"],
                "session_types": session_types,
            }
        )

    conversations_list.sort(
        key=lambda item: item["updated_at"] or "",
        reverse=True,
    )

    latest_conversation_id = (
        conversations_list[0]["conversation_id"] if conversations_list else None
    )

    return {
        "conversations": conversations_list,
        "latest_conversation_id": latest_conversation_id,
    }


@app.get("/conversations/{conversation_id}")
async def get_conversation_transcript(
    conversation_id: str, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    records = (
        db.query(models.Conversation)
        .order_by(models.Conversation.created_at.asc())
        .all()
    )

    transcript: List[Dict[str, Any]] = []
    session_types: set[str] = set()
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    message_count = 0

    for record in records:
        if not record.messages:
            continue

        try:
            messages = json.loads(record.messages)
        except json.JSONDecodeError:
            messages = {}

        record_conversation_id = _conversation_id_for_record(record, messages)
        if record_conversation_id != conversation_id:
            continue

        timestamp_iso = _message_timestamp(messages, record)
        timestamp_dt = _parse_iso_timestamp(timestamp_iso) or to_local(
            record.created_at
        )

        if timestamp_dt:
            if started_at is None or timestamp_dt < started_at:
                started_at = timestamp_dt
            if updated_at is None or timestamp_dt > updated_at:
                updated_at = timestamp_dt

        if record.session_type:
            session_types.add(record.session_type)

        message_count += 1

        user_text = (messages.get("user") or "").strip()
        catalyst_text = (messages.get("catalyst") or "").strip()

        if user_text:
            transcript.append(
                {
                    "role": "user",
                    "content": user_text,
                    "timestamp": timestamp_iso,
                    "session_type": record.session_type,
                    "message_id": record.id,
                    "conversation_id": record_conversation_id,
                }
            )

        if catalyst_text:
            transcript.append(
                {
                    "role": "catalyst",
                    "content": catalyst_text,
                    "timestamp": timestamp_iso,
                    "session_type": record.session_type,
                    "model": messages.get("model"),
                    "thinking": record.thinking_log or None,
                    "function_calls": messages.get("function_calls", []),
                    "system_prompt": messages.get("system_prompt"),
                    "system_prompt_reference": messages.get("system_prompt_reference"),
                    "context_snapshot": messages.get("context_snapshot"),
                    "context_reference": messages.get("context_reference"),
                    "message_id": record.id,
                    "conversation_id": record_conversation_id,
                }
            )

    if message_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")

    transcript.sort(
        key=lambda item: _parse_iso_timestamp(item.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    return {
        "conversation_id": conversation_id,
        "messages": transcript,
        "metadata": {
            "message_count": message_count,
            "session_types": sorted(session_types),
            "started_at": started_at.isoformat() if started_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        },
    }


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, db: Session = Depends(get_db)
) -> Response:
    deleted_count = 0

    matching_records = (
        db.query(models.Conversation)
        .filter(models.Conversation.conversation_uuid == conversation_id)
        .all()
    )

    for record in matching_records:
        db.delete(record)
        deleted_count += 1

    if deleted_count == 0:
        legacy_records = (
            db.query(models.Conversation)
            .filter(models.Conversation.conversation_uuid.is_(None))
            .all()
        )

        for record in legacy_records:
            if not record.messages:
                continue
            try:
                payload = json.loads(record.messages)
            except json.JSONDecodeError:
                payload = {}

            derived_id = _conversation_id_for_record(record, payload)
            if derived_id == conversation_id:
                db.delete(record)
                deleted_count += 1

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.commit()
    return Response(status_code=204)


@app.get("/conversations/{conversation_id}/messages/{message_id}/context")
async def get_message_context(
    conversation_id: str,
    message_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    record = (
        db.query(models.Conversation)
        .filter(models.Conversation.id == message_id)
        .one_or_none()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Message not found")

    try:
        payload = json.loads(record.messages) if record.messages else {}
    except json.JSONDecodeError:
        payload = {}

    record_conversation_id = _conversation_id_for_record(record, payload)
    if record_conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not part of conversation")

    reference = payload.get("context_reference")
    snapshot = payload.get("context_snapshot")
    system_prompt = payload.get("system_prompt")
    system_prompt_reference = payload.get("system_prompt_reference")

    if reference:
        context_payload = _reconstruct_context_from_reference(db, reference)
    elif snapshot is not None:
        context_payload = snapshot
    else:
        context_payload = None

    runtime_base_metadata: Optional[Dict[str, Any]] = None
    checksum_match: Optional[bool] = None

    context_for_prompt = context_payload or snapshot
    if system_prompt_reference and context_for_prompt:
        session_value = (
            (
                system_prompt_reference.get("session_type")
                if isinstance(system_prompt_reference, dict)
                else None
            )
            or record.session_type
            or SessionType.GENERAL.value
        )

        try:
            session_enum = SessionType(session_value)
        except ValueError:
            session_enum = SessionType.GENERAL

        try:
            reconstructed_prompt, runtime_base_metadata = reconstruct_system_prompt(
                session_enum,
                context_for_prompt,
                system_prompt_reference
                if isinstance(system_prompt_reference, dict)
                else None,
            )
        except Exception:  # pragma: no cover - defensive
            reconstructed_prompt = None
            runtime_base_metadata = None

        if system_prompt is None:
            system_prompt = reconstructed_prompt

        stored_base = (
            system_prompt_reference.get("base")
            if isinstance(system_prompt_reference, dict)
            else None
        )
        if (
            runtime_base_metadata
            and isinstance(stored_base, dict)
            and stored_base.get("checksum")
            and runtime_base_metadata.get("checksum")
        ):
            checksum_match = (
                stored_base["checksum"] == runtime_base_metadata["checksum"]
            )

    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "context": context_payload,
        "reference": reference,
        "snapshot": snapshot,
        "system_prompt": system_prompt,
        "system_prompt_reference": system_prompt_reference,
        "system_prompt_runtime_base": runtime_base_metadata,
        "system_prompt_checksum_match": checksum_match,
    }


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
