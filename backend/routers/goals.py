"""Goals API routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_db
from ..memory_manager import get_goals_hierarchy
from ..schemas import GoalUpdate

router = APIRouter()


@router.get("/goals")
async def get_goals(db: Session = Depends(get_db)) -> Dict[str, Any]:
    goals = get_goals_hierarchy(db)
    return {
        "goals": goals,
        "north_star": goals[0] if goals else None,
        "total": len(goals),
    }


@router.put("/goals/{goal_id}")
async def update_goal(
    goal_id: int, update: GoalUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    goal = db.query(models.Goal).filter(models.Goal.id == goal_id).one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if update.rank is not None:
        goal.rank = update.rank
    if update.is_active is not None:
        goal.is_active = update.is_active

    db.commit()
    return {"status": "success", "goal_id": goal_id}
