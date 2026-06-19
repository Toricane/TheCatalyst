"""Goals API routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_db
from ..memory_manager import (
    get_goals_hierarchy,
    serialize_goal_row,
    sync_ltm_north_star,
)
from ..schemas import GoalCreate, GoalUpdate

router = APIRouter()


def _apply_north_star_promotion(
    db: Session, goal: models.Goal, new_rank: int
) -> None:
    """When promoting a goal to rank 1, demote the current North Star."""
    if new_rank != 1 or goal.rank == 1:
        return

    current_north_star = (
        db.query(models.Goal)
        .filter(
            models.Goal.is_active.is_(True),
            models.Goal.id != goal.id,
            models.Goal.rank == 1,
        )
        .first()
    )
    if current_north_star:
        current_north_star.rank = goal.rank if goal.rank > 1 else 2


@router.get("/goals")
async def get_goals(db: Session = Depends(get_db)) -> Dict[str, Any]:
    goals = get_goals_hierarchy(db)
    return {
        "goals": goals,
        "north_star": goals[0] if goals else None,
        "total": len(goals),
    }


@router.post("/goals")
async def create_goal(
    payload: GoalCreate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    description = payload.description.strip()
    if not description:
        raise HTTPException(status_code=422, detail="Description cannot be empty")

    rank = payload.rank
    if rank == 1:
        existing = (
            db.query(models.Goal)
            .filter(models.Goal.is_active.is_(True), models.Goal.rank == 1)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail="A North Star already exists. Promote an existing goal instead.",
            )

    goal = models.Goal(
        description=description,
        metric=payload.metric,
        timeline=payload.timeline,
        rank=rank,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return {"status": "success", "goal": serialize_goal_row(goal)}


@router.put("/goals/{goal_id}")
async def update_goal(
    goal_id: int, update: GoalUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    goal = db.query(models.Goal).filter(models.Goal.id == goal_id).one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    north_star_content_changed = False

    if update.description is not None:
        stripped = update.description.strip()
        if not stripped:
            raise HTTPException(status_code=422, detail="Description cannot be empty")
        goal.description = stripped
        north_star_content_changed = goal.rank == 1

    if update.metric is not None:
        goal.metric = update.metric.strip() or None
        north_star_content_changed = north_star_content_changed or goal.rank == 1

    if update.timeline is not None:
        goal.timeline = update.timeline.strip() or None
        north_star_content_changed = north_star_content_changed or goal.rank == 1

    if update.rank is not None:
        _apply_north_star_promotion(db, goal, update.rank)
        goal.rank = update.rank

    if update.is_active is not None:
        goal.is_active = update.is_active
        if not update.is_active and goal.rank == 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate the North Star. Promote another goal first.",
            )

    if north_star_content_changed and goal.is_active and goal.rank == 1:
        sync_ltm_north_star(db, goal.description, goal.metric, goal.timeline)

    db.commit()
    db.refresh(goal)
    return {"status": "success", "goal": serialize_goal_row(goal)}
