"""Conversation history API routes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .. import models
from ..catalyst_ai import reconstruct_system_prompt
from ..conversation import (
    build_conversation_filename,
    conversation_id_for_record,
    generate_markdown_export,
    load_conversation_transcript,
    message_timestamp,
    parse_iso_timestamp,
    reconstruct_context_from_reference,
)
from ..dependencies import get_db
from ..schemas import SessionType
from ..time_utils import to_local

router = APIRouter()


@router.get("/conversations/recent")
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


@router.get("/conversations")
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

        conversation_id = conversation_id_for_record(record, messages)
        timestamp_iso = message_timestamp(messages, record)
        timestamp_dt = parse_iso_timestamp(timestamp_iso) or to_local(
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


@router.delete("/conversations/{conversation_id}", status_code=204)
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

            derived_id = conversation_id_for_record(record, payload)
            if derived_id == conversation_id:
                db.delete(record)
                deleted_count += 1

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.commit()
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}")
async def get_conversation_transcript(
    conversation_id: str, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    return load_conversation_transcript(db, conversation_id)


@router.get(
    "/conversations/{conversation_id}/export",
    response_class=PlainTextResponse,
)
async def export_conversation_markdown(
    conversation_id: str, db: Session = Depends(get_db)
) -> PlainTextResponse:
    payload = load_conversation_transcript(db, conversation_id)
    markdown = generate_markdown_export(payload)
    filename = build_conversation_filename(
        conversation_id, payload.get("metadata", {})
    )
    headers = {"X-Conversation-Suggested-Filename": filename}
    return PlainTextResponse(markdown, media_type="text/markdown", headers=headers)


@router.get("/conversations/{conversation_id}/messages/{message_id}/context")
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

    record_conversation_id = conversation_id_for_record(record, payload)
    if record_conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not part of conversation")

    reference = payload.get("context_reference")
    snapshot = payload.get("context_snapshot")
    system_prompt = payload.get("system_prompt")
    system_prompt_reference = payload.get("system_prompt_reference")

    if reference:
        context_payload = reconstruct_context_from_reference(db, reference)
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
