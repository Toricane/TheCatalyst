"""SQLAlchemy models for The Catalyst backend."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class Goal(Base):
    __tablename__ = "goals"

    id: int = Column(Integer, primary_key=True, index=True)
    description: str = Column(Text, nullable=False)
    metric: Optional[str] = Column(String(255))
    timeline: Optional[str] = Column(String(255))
    rank: int = Column(Integer, default=999)
    progress_notes: Optional[str] = Column(Text)
    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    completed_at: Optional[datetime] = Column(DateTime(timezone=True))
    is_active: bool = Column(Boolean, default=True)


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id: int = Column(Integer, primary_key=True, index=True)
    date: datetime = Column(Date, server_default=func.date("now"))
    morning_completed: bool = Column(Boolean, default=False)
    evening_completed: bool = Column(Boolean, default=False)
    morning_intention: Optional[str] = Column(Text)
    evening_reflection: Optional[str] = Column(Text)
    wins: Optional[str] = Column(Text)
    challenges: Optional[str] = Column(Text)
    gratitude: Optional[str] = Column(Text)
    next_day_priorities: Optional[str] = Column(Text)
    energy_level: Optional[int] = Column(Integer)
    focus_rating: Optional[int] = Column(Integer)
    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class LTMProfile(Base):
    __tablename__ = "ltm_profile"

    id: int = Column(Integer, primary_key=True, index=True)
    summary_text: str = Column(Text, nullable=False)
    patterns_section: Optional[str] = Column(Text)
    challenges_section: Optional[str] = Column(Text)
    breakthroughs_section: Optional[str] = Column(Text)
    personality_section: Optional[str] = Column(Text)
    current_state_section: Optional[str] = Column(Text)
    version: int = Column(Integer, default=1)
    token_count: Optional[int] = Column(Integer)
    last_updated: datetime = Column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: int = Column(Integer, primary_key=True, index=True)
    conversation_uuid: Optional[str] = Column(String(64), index=True)
    session_type: Optional[str] = Column(String(50))
    messages: Optional[str] = Column(Text)
    thinking_log: Optional[str] = Column(Text)
    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class Insight(Base):
    __tablename__ = "insights"

    id: int = Column(Integer, primary_key=True, index=True)
    insight_type: Optional[str] = Column(String(100))
    category: Optional[str] = Column(String(100))
    description: str = Column(Text, nullable=False)
    importance_score: Optional[int] = Column(Integer)
    date_identified: datetime = Column(Date, server_default=func.date("now"))


class SessionTracking(Base):
    __tablename__ = "session_tracking"

    id: int = Column(Integer, primary_key=True, index=True)
    last_morning_session: Optional[datetime] = Column(DateTime(timezone=True))
    last_evening_session: Optional[datetime] = Column(DateTime(timezone=True))
    streak_count: int = Column(Integer, default=0)
    total_sessions: int = Column(Integer, default=0)
