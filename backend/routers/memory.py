"""Memory, logs, insights, and stats API routes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_db
from ..memory_manager import get_current_ltm_profile
from ..time_utils import local_today

router = APIRouter()


@router.get("/memory/profile")
async def get_memory_profile(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return get_current_ltm_profile(db)


@router.get("/logs/recent")
async def get_recent_logs(
    days: int = 7, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    cutoff = local_today() - timedelta(days=days)
    logs = (
        db.query(models.DailyLog)
        .filter(models.DailyLog.date >= cutoff)
        .order_by(models.DailyLog.date.desc())
        .all()
    )

    return [
        {
            "id": log.id,
            "date": log.date.isoformat() if log.date else None,
            "morning_completed": log.morning_completed,
            "evening_completed": log.evening_completed,
            "morning_intention": log.morning_intention,
            "evening_reflection": log.evening_reflection,
            "wins": log.wins,
            "challenges": log.challenges,
            "gratitude": log.gratitude,
            "next_day_priorities": log.next_day_priorities,
            "energy_level": log.energy_level,
            "focus_rating": log.focus_rating,
        }
        for log in logs
    ]


@router.get("/insights")
async def get_insights(
    limit: int = 10, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    insights = (
        db.query(models.Insight)
        .order_by(
            models.Insight.importance_score.desc(),
            models.Insight.date_identified.desc(),
        )
        .limit(limit)
        .all()
    )
    return [
        {
            "id": insight.id,
            "insight_type": insight.insight_type,
            "category": insight.category,
            "description": insight.description,
            "importance_score": insight.importance_score,
            "date_identified": insight.date_identified.isoformat()
            if insight.date_identified
            else None,
        }
        for insight in insights
    ]


@router.get("/stats")
async def get_user_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    tracking = (
        db.query(models.SessionTracking)
        .order_by(models.SessionTracking.id.desc())
        .first()
    )

    thirty_days_ago = local_today() - timedelta(days=30)

    stats = (
        db.query(
            func.count(models.DailyLog.id).label("total_days"),
            func.sum(func.coalesce(models.DailyLog.morning_completed, 0)).label(
                "mornings_completed"
            ),
            func.sum(func.coalesce(models.DailyLog.evening_completed, 0)).label(
                "evenings_completed"
            ),
            func.avg(models.DailyLog.energy_level).label("avg_energy"),
            func.avg(models.DailyLog.focus_rating).label("avg_focus"),
        )
        .filter(models.DailyLog.date >= thirty_days_ago)
        .one()
    )

    total_days = stats.total_days or 0
    divisor = total_days if total_days else 1

    return {
        "streak": tracking.streak_count
        if tracking and tracking.streak_count is not None
        else 0,
        "total_sessions": tracking.total_sessions
        if tracking and tracking.total_sessions is not None
        else 0,
        "completion_rate": {
            "morning": (stats.mornings_completed or 0) / divisor * 100,
            "evening": (stats.evenings_completed or 0) / divisor * 100,
        },
        "average_energy": float(stats.avg_energy or 0),
        "average_focus": float(stats.avg_focus or 0),
    }
