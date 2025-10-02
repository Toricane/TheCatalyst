"""Database utilities for The Catalyst backend."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, scoped_session, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    # SQLite requires this flag when used with FastAPI / multithreading
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
)

Base = declarative_base()


def init_database() -> None:
    """Create all database tables."""
    # Import models to ensure they are registered with the metadata
    from . import models  # noqa: F401  # pylint: disable=unused-import

    models.Base.metadata.create_all(bind=engine)
    _ensure_conversation_schema()


def _ensure_conversation_schema() -> None:
    """Ensure conversation table has dedicated UUID column and backfilled data."""

    with engine.begin() as connection:
        columns = connection.execute(text("PRAGMA table_info(conversations)"))
        has_uuid_column = any(row[1] == "conversation_uuid" for row in columns)
        if not has_uuid_column:
            connection.execute(
                text(
                    "ALTER TABLE conversations ADD COLUMN conversation_uuid VARCHAR(64)"
                )
            )

    from .models import Conversation  # imported lazily to avoid circular import

    session: Session = SessionLocal()
    try:
        needs_backfill = (
            session.query(Conversation)
            .filter(Conversation.conversation_uuid.is_(None))
            .count()
        )
        if needs_backfill:
            _backfill_conversation_threads(session)
    finally:
        session.close()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
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


def _backfill_conversation_threads(session: Session) -> None:
    """Populate missing conversation UUIDs and align embedded payloads."""

    from .models import Conversation  # local import to avoid circular dependency

    gap_threshold = timedelta(hours=2)
    records = (
        session.query(Conversation)
        .order_by(Conversation.created_at.asc(), Conversation.id.asc())
        .all()
    )

    last_uuid: Optional[str] = None
    last_timestamp: Optional[datetime] = None
    updates: int = 0

    for record in records:
        payload: Dict[str, Any]
        if not record.messages:
            payload = {}
        else:
            try:
                payload = json.loads(record.messages)
            except json.JSONDecodeError:
                payload = {"_invalid_json": record.messages}

        explicit_uuid = payload.get("conversation_id") or record.conversation_uuid
        if explicit_uuid:
            conversation_uuid = str(explicit_uuid)
        else:
            message_timestamp = _parse_iso(payload.get("timestamp"))
            created_at = (
                record.created_at if isinstance(record.created_at, datetime) else None
            )
            timestamp = message_timestamp or created_at

            start_new_thread = bool(
                payload.get("initial_greeting") or payload.get("is_conversation_start")
            )

            if last_uuid is None:
                start_new_thread = True
            elif timestamp is None or last_timestamp is None:
                # Without timestamps fall back to continuing the current thread only if explicitly flagged
                start_new_thread = start_new_thread or False
            else:
                start_new_thread = start_new_thread or (
                    timestamp - last_timestamp > gap_threshold
                )

            conversation_uuid = last_uuid if not start_new_thread else str(uuid.uuid4())

        # Update record if needed
        if record.conversation_uuid != conversation_uuid:
            record.conversation_uuid = conversation_uuid
            updates += 1

        if payload.get("conversation_id") != conversation_uuid:
            payload["conversation_id"] = conversation_uuid
            record.messages = json.dumps(payload)
            updates += 1

        timestamp_value = _parse_iso(payload.get("timestamp")) or (
            record.created_at if isinstance(record.created_at, datetime) else None
        )

        last_uuid = conversation_uuid
        if timestamp_value is not None:
            last_timestamp = timestamp_value

    if updates:
        session.commit()


@contextmanager
def get_session() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        session.close()
