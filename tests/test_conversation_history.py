import json
import os
import uuid
from contextlib import contextmanager

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import (
    TestClient,  # noqa: E402  pylint: disable=wrong-import-position
)

from backend import models  # noqa: E402  pylint: disable=wrong-import-position
from backend.app import app  # noqa: E402  pylint: disable=wrong-import-position
from backend.database import (  # noqa: E402  pylint: disable=wrong-import-position
    SessionLocal,
    init_database,
)

init_database()


def _clear_conversations() -> None:
    session = SessionLocal()
    try:
        session.query(models.Conversation).delete()
        session.commit()
    finally:
        session.close()


def _create_conversation(conversation_id: str | None = None) -> str:
    conversation_uuid = conversation_id or str(uuid.uuid4())
    payload = {
        "conversation_id": conversation_uuid,
        "user": "Test user message",
        "catalyst": "Test catalyst response",
        "timestamp": "2024-01-01T00:00:00Z",
    }

    session = SessionLocal()
    try:
        record = models.Conversation(
            conversation_uuid=conversation_uuid,
            session_type="general",
            messages=json.dumps(payload),
        )
        session.add(record)
        session.commit()
    finally:
        session.close()

    return conversation_uuid


@contextmanager
def client_context():
    with TestClient(app) as client:
        yield client


def test_conversations_endpoint_returns_empty_list_when_no_history():
    with client_context() as client:
        response = client.get("/conversations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert data.get("conversations") == []
    assert data.get("latest_conversation_id") is None


def test_conversation_transcript_returns_404_for_unknown_id():
    with client_context() as client:
        response = client.get("/conversations/nonexistent-id")
    assert response.status_code == 404
    payload = response.json()
    assert payload.get("detail") == "Conversation not found"
    payload = response.json()
    assert payload.get("detail") == "Conversation not found"


def test_delete_conversation_removes_history_entries():
    _clear_conversations()
    conversation_id = _create_conversation()

    with client_context() as client:
        response = client.get("/conversations")
        assert response.status_code == 200
        data = response.json()
        assert any(
            item["conversation_id"] == conversation_id
            for item in data.get("conversations", [])
        )

        delete_response = client.delete(f"/conversations/{conversation_id}")
        assert delete_response.status_code == 204

        refreshed = client.get("/conversations")
        assert refreshed.status_code == 200
        refreshed_data = refreshed.json()
        assert all(
            item["conversation_id"] != conversation_id
            for item in refreshed_data.get("conversations", [])
        )
        assert refreshed_data.get("conversations") == []
        assert refreshed_data.get("latest_conversation_id") is None

        second_delete = client.delete(f"/conversations/{conversation_id}")
        assert second_delete.status_code == 404
        assert second_delete.json().get("detail") == "Conversation not found"


def test_chat_does_not_duplicate_initial_greeting(monkeypatch):
    _clear_conversations()
    existing_conversation_id = str(uuid.uuid4())
    greeting_payload = {
        "user": None,
        "catalyst": "Hello from The Catalyst.",
        "timestamp": "2025-10-02T19:38:56.123305+00:00",
        "function_calls": [],
        "model": "test-model",
        "initial_greeting": True,
        "conversation_id": existing_conversation_id,
        "is_conversation_start": True,
    }

    session = SessionLocal()
    try:
        session.add(
            models.Goal(
                description="Test goal",
                metric="",
                timeline="",
                rank=1,
            )
        )
        session.flush()
        session.add(
            models.Conversation(
                conversation_uuid=existing_conversation_id,
                session_type="general",
                messages=json.dumps(greeting_payload),
            )
        )
        session.commit()
    finally:
        session.close()

    async def _fake_generate_catalyst_response(*_args, **_kwargs):
        context_payload = _args[2] if len(_args) >= 3 else _kwargs.get("context")
        assert context_payload is not None
        assert "insights" in context_payload
        return {
            "response": "Mock assistant reply.",
            "memory_updated": False,
            "function_calls": [],
            "model": "mock-model",
        }

    monkeypatch.setattr(
        "backend.app.generate_catalyst_response",
        _fake_generate_catalyst_response,
    )

    payload = {
        "message": "First user message",
        "session_type": "general",
        "conversation_id": existing_conversation_id,
        "initial_greeting": {
            "text": greeting_payload["catalyst"],
            "session_type": "general",
            "timestamp": greeting_payload["timestamp"],
            "model": greeting_payload["model"],
            "conversation_id": existing_conversation_id,
        },
    }

    with client_context() as client:
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        response_data = response.json()
        assert response_data.get("conversation_id") == existing_conversation_id

    session = SessionLocal()
    try:
        records = (
            session.query(models.Conversation)
            .filter(models.Conversation.conversation_uuid == existing_conversation_id)
            .all()
        )
        assert len(records) == 2

        greeting_count = 0
        for record in records:
            stored_payload = json.loads(record.messages or "{}")
            if stored_payload.get("initial_greeting"):
                greeting_count += 1
        assert greeting_count == 1
    finally:
        session.close()
