"""Pydantic schemas used by the FastAPI application."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SessionType(str, Enum):
    MORNING = "morning"
    EVENING = "evening"
    GENERAL = "general"
    CATCH_UP = "catch_up"
    INITIALIZATION = "initialization"


class ChatMessage(BaseModel):
    message: str = Field(..., description="User message body")
    session_type: SessionType = Field(default=SessionType.GENERAL)


class ChatResponse(BaseModel):
    response: str
    memory_updated: bool = False
    session_type: str
    thinking: Optional[str] = None
    model: Optional[str] = None


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
