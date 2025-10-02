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
