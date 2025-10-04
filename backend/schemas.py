"""Pydantic schemas used by the FastAPI application."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SessionType(str, Enum):
    MORNING = "morning"
    EVENING = "evening"
    GENERAL = "general"
    CATCH_UP = "catch_up"
    INITIALIZATION = "initialization"


class InitialGreeting(BaseModel):
    text: str = Field(..., description="The generated initial greeting text")
    session_type: Optional[SessionType] = Field(
        default=None,
        description="Session type associated with the greeting, if any",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO timestamp when the greeting was generated",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model identifier used to generate the greeting",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Conversation thread identifier associated with the greeting",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="System instructions used to produce the greeting",
    )
    system_prompt_reference: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Reference metadata for reconstructing the system prompt",
    )
    context_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Context snapshot supplied to the model when generating the greeting",
    )
    context_reference: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Lightweight reference describing the context scope used when generating the greeting",
    )
    message_id: Optional[int] = Field(
        default=None,
        description="Database identifier for the persisted greeting message, when available",
    )


class ChatMessage(BaseModel):
    message: str = Field(..., description="User message body")
    session_type: SessionType = Field(default=SessionType.GENERAL)
    conversation_id: Optional[str] = Field(
        default=None,
        description="Conversation thread identifier. When omitted, a new conversation is created.",
    )
    initial_greeting: Optional[InitialGreeting] = Field(
        default=None,
        description="Latest initial greeting shown to the user prior to this message",
    )


class ChatResponse(BaseModel):
    response: str
    memory_updated: bool = False
    session_type: str
    conversation_id: Optional[str] = None
    message_id: Optional[int] = None
    thinking: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    context_snapshot: Optional[Dict[str, Any]] = None
    context_reference: Optional[Dict[str, Any]] = None
    system_prompt_reference: Optional[Dict[str, Any]] = None


class GreetingRequest(BaseModel):
    session_type: SessionType = Field(
        default=SessionType.GENERAL,
        description="Frontend-selected session type for the initial greeting",
    )


class Goal(BaseModel):
    description: str
    metric: Optional[str] = None
    timeline: Optional[str] = None
    rank: int = 1


class GoalUpdate(BaseModel):
    goal_id: Optional[int] = None
    rank: Optional[int] = None
    is_active: Optional[bool] = None
