"""Chat, initialization, and greeting API routes."""

from __future__ import annotations

import json
from datetime import timedelta
from math import ceil
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..catalyst_ai import generate_catalyst_response
from ..config import SHOW_THINKING
from ..conversation import (
    RECENT_CONVERSATION_CHAR_LIMIT,
    build_context_reference,
    conversation_id_for_record,
    parse_iso_timestamp,
    serialize_goal_record,
)
from ..dependencies import get_db
from ..functions import update_session_tracking
from ..memory_manager import (
    check_for_missed_sessions,
    get_current_ltm_profile,
    get_goals_hierarchy,
    get_ltm_profile_by_id,
    get_recent_insights,
)
from ..schemas import ChatMessage, ChatResponse, Goal, GreetingRequest, SessionType
from ..time_utils import local_now, local_today, to_local, utc_now

router = APIRouter()


def _persisted_debug_fields(response: Dict[str, Any]) -> Dict[str, Any]:
    """Fields stored on conversation rows for the system-context debug UI."""

    return {
        "system_prompt": response.get("system_prompt"),
        "context_snapshot": response.get("context_snapshot"),
        "system_prompt_reference": response.get("system_prompt_reference"),
    }


@router.post("/initialize", response_model=ChatResponse)
async def initialize_catalyst(
    goal: Goal, db: Session = Depends(get_db)
) -> ChatResponse:
    existing_goals = (
        db.query(models.Goal).filter(models.Goal.is_active.is_(True)).count()
    )
    if existing_goals > 0:
        raise HTTPException(
            status_code=409,
            detail="Catalyst is already initialized. Use POST /goals to add goals.",
        )

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
        "goals": [serialize_goal_record(goal_row)],
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
        output_mode="plain",
    )

    conversation_id = str(uuid4())
    timestamp = utc_now().isoformat()

    context_reference = build_context_reference(
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
                "context_reference": context_reference,
                **_persisted_debug_fields(response),
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


@router.post("/initial-greeting", response_model=ChatResponse)
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
            "conversation_id": conversation_id_for_record(record, messages),
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

    context_reference = build_context_reference(
        sources=context_sources,
        goals=goals,
        ltm_profile=ltm_profile,
        missed_info=missed_info,
        insights=insights,
    )

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
        output_mode="greeting",
    )

    conversation_id = str(uuid4())
    timestamp = utc_now().isoformat()

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
                "context_reference": context_reference,
                **_persisted_debug_fields(response),
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


@router.post("/chat", response_model=ChatResponse)
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
            conversation_id = conversation_id_for_record(latest_record, latest_payload)
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

    recent_cutoff = utc_now() - timedelta(hours=48)
    recent_records = (
        db.query(models.Conversation)
        .filter(models.Conversation.created_at >= recent_cutoff)
        .order_by(models.Conversation.created_at.desc())
        .all()
    )

    current_time = local_now()

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
            "conversation_id": conversation_id_for_record(record, messages),
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

    def _entry_length(entry: Dict[str, Any]) -> int:
        return len(entry.get("user") or "") + len(entry.get("catalyst") or "")

    def _make_conversation_item(
        entry: Dict[str, Any], source: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "entry": entry,
            "source": source,
            "created": parse_iso_timestamp(entry.get("timestamp")),
        }

    conversation_items: List[Dict[str, Any]] = []
    pending_greeting_items: List[Dict[str, Any]] = []
    user_message_seen = False

    for item in raw_entries:
        entry = item["entry"]
        source = {"type": "record", "record_id": item["record_id"]}
        conversation_item = _make_conversation_item(entry, source)

        if item["is_initial_greeting"]:
            if user_message_seen:
                conversation_items.append(conversation_item)
            else:
                pending_greeting_items.append(conversation_item)
            continue

        if pending_greeting_items:
            conversation_items.extend(pending_greeting_items)
            pending_greeting_items = []

        if item["has_user_text"]:
            user_message_seen = True

        conversation_items.append(conversation_item)

    if user_message_seen and pending_greeting_items:
        conversation_items.extend(pending_greeting_items)

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
        conversation_items.append(
            _make_conversation_item(
                inline_entry, {"type": "inline", "entry": dict(inline_entry)}
            )
        )

    total_chars = sum(_entry_length(item["entry"]) for item in conversation_items)
    if total_chars > RECENT_CONVERSATION_CHAR_LIMIT:
        twenty_four_hours_ago = current_time - timedelta(hours=24)
        filtered_items = [
            item
            for item in conversation_items
            if item["created"] and item["created"] >= twenty_four_hours_ago
        ]
        if filtered_items:
            conversation_items = filtered_items
            total_chars = sum(
                _entry_length(item["entry"]) for item in conversation_items
            )

        if total_chars > RECENT_CONVERSATION_CHAR_LIMIT and conversation_items:
            trimmed_items: List[Dict[str, Any]] = []
            running_total = 0
            for item in reversed(conversation_items):
                entry_length = _entry_length(item["entry"])
                if (
                    running_total + entry_length > RECENT_CONVERSATION_CHAR_LIMIT
                    and trimmed_items
                ):
                    continue
                trimmed_items.append(item)
                running_total += entry_length
                if running_total >= RECENT_CONVERSATION_CHAR_LIMIT:
                    break
            conversation_items = list(reversed(trimmed_items))

    recent_conversations = [item["entry"] for item in conversation_items]
    context_sources = [item["source"] for item in conversation_items]

    context = {
        "goals": goals,
        "ltm_profile": ltm_profile,
        "missed_sessions": missed_info.get("missed_sessions", []),
        "insights": insights,
        "recent_conversations": recent_conversations,
    }

    context_reference = build_context_reference(
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
                        "context_reference": greeting_reference,
                        "system_prompt": getattr(
                            greeting_payload, "system_prompt", None
                        ),
                        "context_snapshot": getattr(
                            greeting_payload, "context_snapshot", None
                        ),
                        "system_prompt_reference": getattr(
                            greeting_payload, "system_prompt_reference", None
                        ),
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
                "context_reference": context_reference,
                **_persisted_debug_fields(response),
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
