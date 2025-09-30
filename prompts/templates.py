"""Prompt templates for The Catalyst agent."""

from __future__ import annotations

SESSION_TEMPLATES = {
    "morning": "Ignition: greet with energy, clarify top intentions, prime execution mindset.",
    "evening": "Reflection: celebrate wins, explore challenges, capture gratitude, set tomorrow's priority.",
    "catch_up": "Re-engage without judgment, regain situational awareness, rebuild momentum quickly.",
    "general": "Default coaching cadence—keep conversation tethered to the user's North Star goals.",
    "initialization": "Welcome them powerfully, co-create their North Star goal, confirm metric + timeline, secure commitment.",
}


def session_template(session_type: str) -> str:
    """Return the template guidance for a given session type."""
    return SESSION_TEMPLATES.get(session_type, SESSION_TEMPLATES["general"])
