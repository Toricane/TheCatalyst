"""Conversation helpers for transcript loading, context, and export."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models
from .memory_manager import (
    get_current_ltm_profile,
    get_goals_hierarchy,
    get_insights_by_ids,
    get_ltm_profile_by_id,
    get_ltm_profile_by_version,
    get_recent_insights,
)
from .schemas import SessionType
from .time_utils import to_local, utc_now

RECENT_CONVERSATION_CHAR_LIMIT = 24000

SESSION_LABELS = {
    SessionType.MORNING.value: "Morning",
    SessionType.EVENING.value: "Evening",
    SessionType.GENERAL.value: "General",
    SessionType.CATCH_UP.value: "Catch-up",
    SessionType.INITIALIZATION.value: "Initialization",
}

ROLE_ICONS = {
    "user": "👤",
    "assistant": "🤖",
    "catalyst": "🤖",
    "system": "🛰️",
    "tool": "🛠️",
}


def conversation_id_for_record(
    record: models.Conversation, messages: Dict[str, Any]
) -> str:
    if getattr(record, "conversation_uuid", None):
        return str(record.conversation_uuid)
    conversation_id = messages.get("conversation_id")
    if conversation_id:
        return str(conversation_id)
    return f"legacy-{record.id}"


def message_timestamp(
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


def parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
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


def conversation_session_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, SessionType):
        normalized = value.value
    else:
        normalized = str(value)
    if normalized in SESSION_LABELS:
        return SESSION_LABELS[normalized]
    return normalized.replace("_", " ").title()


def format_markdown_timestamp(
    value: Optional[str], default: Optional[str] = "Unknown time"
) -> Optional[str]:
    if not value:
        return default

    parsed = parse_iso_timestamp(value)
    if not parsed:
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            if default == "Unknown time":
                return default
            return value

    localized = to_local(parsed) or parsed.astimezone()

    month = localized.strftime("%b")
    day = localized.day
    year = localized.year
    hour = localized.strftime("%I").lstrip("0") or "0"
    minute = localized.strftime("%M")
    meridiem = localized.strftime("%p").lower()
    meridiem = meridiem.replace("am", "a.m.").replace("pm", "p.m.")
    return f"{month} {day}, {year}, {hour}:{minute} {meridiem}"


def build_conversation_markdown(
    transcript: List[Dict[str, Any]], metadata: Dict[str, Any]
) -> str:
    lines: List[str] = ["# The Catalyst Conversation"]

    summary_lines: List[str] = []
    started_at = metadata.get("started_at")
    updated_at = metadata.get("updated_at")
    if started_at:
        summary_lines.append(f"- Started: {format_markdown_timestamp(started_at)}")
    if updated_at and updated_at != started_at:
        summary_lines.append(
            f"- Last updated: {format_markdown_timestamp(updated_at)}"
        )
    message_count = metadata.get("message_count")
    if message_count:
        summary_lines.append(f"- Messages: {message_count}")
    session_types = metadata.get("session_types") or []
    if session_types:
        readable_sessions = ", ".join(
            filter(
                None, (conversation_session_label(value) for value in session_types)
            )
        )
        if readable_sessions:
            summary_lines.append(f"- Sessions: {readable_sessions}")

    if summary_lines:
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.extend(summary_lines)
        lines.append("")

    if not transcript:
        lines.append("_No messages in this conversation yet._")
        return "\n".join(lines).strip() + "\n"

    for entry in transcript:
        content = (entry.get("content") or "").strip()
        if not content:
            continue

        timestamp_label = entry.get("timestamp")
        session_label = conversation_session_label(entry.get("session_type"))

        meta_parts: List[str] = []
        if timestamp_label:
            meta_parts.append(format_markdown_timestamp(timestamp_label))
        if session_label:
            meta_parts.append(session_label)

        meta_display = " • ".join(meta_parts)

        role = entry.get("role")
        if role == "catalyst":
            model_label = entry.get("model") or "The Catalyst"
            heading = f"### 🤖 {model_label}"
            if meta_display:
                heading = f"{heading} • {meta_display}"
        elif role == "user":
            heading = "### 👤"
            if meta_display:
                heading = f"{heading} {meta_display}"
        else:
            label = str(role or "message").replace("_", " ").title()
            heading = f"### 💬 {label}"
            if meta_display:
                heading = f"{heading} • {meta_display}"

        lines.append(heading)
        lines.append("")
        lines.append(content.replace("\r\n", "\n"))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def suggest_export_filename(metadata: Dict[str, Any], conversation_id: str) -> str:
    timestamp_source = metadata.get("started_at") or metadata.get("updated_at")
    parsed = parse_iso_timestamp(timestamp_source)
    if parsed:
        localized = to_local(parsed) or parsed.astimezone()
        date_part = localized.strftime("%Y%m%d")
        time_part = localized.strftime("%H%M")
        base = f"{date_part}-{time_part}"
    else:
        base = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")

    safe_id = "".join(ch for ch in conversation_id if ch.isalnum())[:8]
    suffix = f"-{safe_id}" if safe_id else ""
    return f"catalyst-conversation-{base}{suffix}.md"


def load_conversation_thread(
    db: Session, conversation_id: str
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
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

        record_conversation_id = conversation_id_for_record(record, messages)
        if record_conversation_id != conversation_id:
            continue

        timestamp_iso = message_timestamp(messages, record)
        timestamp_dt = parse_iso_timestamp(timestamp_iso) or to_local(
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
        key=lambda item: parse_iso_timestamp(item.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    metadata = {
        "message_count": message_count,
        "session_types": sorted(session_types),
        "started_at": started_at.isoformat() if started_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }

    return transcript, metadata


def serialize_goal_record(goal: models.Goal) -> Dict[str, Any]:
    created_at_local = to_local(goal.created_at) if goal.created_at else None
    return {
        "id": goal.id,
        "description": goal.description,
        "metric": goal.metric,
        "timeline": goal.timeline,
        "rank": goal.rank,
        "created_at": created_at_local.isoformat() if created_at_local else None,
    }


def build_context_reference(
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


def reconstruct_context_from_reference(
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
                or message_timestamp(payload, record),
                "conversation_id": conversation_id_for_record(record, payload),
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
                goals.append(serialize_goal_record(goal_record))

    if not goals:
        goals = get_goals_hierarchy(db)

    ltm_meta = reference.get("ltm_profile") or {}
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


def load_conversation_transcript(
    db: Session, conversation_id: str
) -> Dict[str, Any]:
    transcript, metadata = load_conversation_thread(db, conversation_id)
    return {
        "conversation_id": conversation_id,
        "messages": transcript,
        "metadata": metadata,
    }


def build_conversation_filename(
    conversation_id: str, metadata: Dict[str, Any]
) -> str:
    timestamp_source = metadata.get("updated_at") or metadata.get("started_at")
    timestamp = parse_iso_timestamp(timestamp_source) if timestamp_source else None
    if not timestamp:
        timestamp = utc_now()
    local_timestamp = timestamp.astimezone()
    stamp = local_timestamp.strftime("%Y%m%d-%H%M")
    safe_fragment = re.sub(r"[^a-zA-Z0-9]+", "-", conversation_id).strip("-")
    if not safe_fragment:
        safe_fragment = "conversation"
    return f"catalyst-{stamp}-{safe_fragment[:16].lower()}.md"


def generate_markdown_export(payload: Dict[str, Any]) -> str:
    conversation_id = payload.get("conversation_id", "")
    metadata = payload.get("metadata", {})
    messages = payload.get("messages", [])

    lines: List[str] = ["# Conversation Export", ""]
    if conversation_id:
        lines.append(f"- **Conversation ID:** `{conversation_id}`")

    message_count = metadata.get("message_count")
    if message_count:
        lines.append(f"- **Messages:** {message_count}")

    started = metadata.get("started_at")
    formatted_started = format_markdown_timestamp(started, default=None)
    if formatted_started:
        lines.append(f"- **Started:** {formatted_started}")

    updated = metadata.get("updated_at")
    formatted_updated = format_markdown_timestamp(updated, default=None)
    if formatted_updated:
        lines.append(f"- **Last activity:** {formatted_updated}")

    lines.append(f"- **Exported:** {format_markdown_timestamp(utc_now().isoformat())}")
    lines.extend(["", "---", ""])

    for message in messages:
        role = message.get("role", "")
        icon = ROLE_ICONS.get(role, "💬")
        session_label = conversation_session_label(message.get("session_type"))
        timestamp_text = format_markdown_timestamp(
            message.get("timestamp"), default=None
        )

        if role == "catalyst":
            primary = message.get("model") or "The Catalyst"
        else:
            primary = timestamp_text or "User"

        heading_parts = [primary]
        if role == "catalyst" and timestamp_text:
            heading_parts.append(timestamp_text)
        if role == "catalyst" and session_label:
            heading_parts.append(session_label)
        if role != "catalyst":
            if timestamp_text and primary != timestamp_text:
                heading_parts.append(timestamp_text)
            if session_label:
                heading_parts.append(session_label)

        heading = " • ".join(part for part in heading_parts if part)
        lines.append(f"### {icon} {heading}")
        lines.append("")

        content = (message.get("content") or "").strip()
        if not content:
            lines.append("_No content recorded._")
        else:
            lines.append(content)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
