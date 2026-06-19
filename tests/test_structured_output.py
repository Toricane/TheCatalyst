import json

from backend.catalyst_ai import _parse_structured_envelope
from backend.functions import apply_envelope_actions


def test_parse_structured_envelope_valid_json():
    payload = {
        "reply": "Hello there.",
        "daily_log": None,
        "memory_update": None,
        "insights": None,
    }
    reply, envelope = _parse_structured_envelope(json.dumps(payload))
    assert reply == "Hello there."
    assert envelope["reply"] == "Hello there."


def test_parse_structured_envelope_fenced_json():
    raw = '```json\n{"reply": "Hi", "daily_log": null}\n```'
    reply, envelope = _parse_structured_envelope(raw)
    assert reply == "Hi"
    assert "daily_log" in envelope


def test_parse_structured_envelope_plain_text_fallback():
    reply, envelope = _parse_structured_envelope("Just a plain greeting.")
    assert reply == "Just a plain greeting."
    assert envelope["reply"] == "Just a plain greeting."


def test_apply_envelope_actions_memory_update(monkeypatch):
    calls = []

    def _fake_update(**kwargs):
        calls.append(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(
        "backend.functions.update_ltm_profile_function",
        _fake_update,
    )

    envelope = {
        "reply": "Done.",
        "memory_update": {
            "should_update": True,
            "summary_text": "## Overview\nTest profile",
        },
    }
    executed, memory_updated = apply_envelope_actions(envelope)
    assert memory_updated is True
    assert len(executed) == 1
    assert executed[0]["function"] == "update_ltm_profile"
    assert calls[0]["summary_text"].startswith("## Overview")
