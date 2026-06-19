"""Tests for goals API and streak computation."""

from __future__ import annotations

import os
from datetime import date, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402

from backend import models  # noqa: E402
from backend.app import app  # noqa: E402
from backend.database import SessionLocal, init_database  # noqa: E402
from backend.memory_manager import compute_streak, sync_ltm_north_star  # noqa: E402
from backend.time_utils import local_today  # noqa: E402

init_database()


def _clear_goals() -> None:
    session = SessionLocal()
    try:
        session.query(models.Goal).delete()
        session.query(models.LTMProfile).delete()
        session.query(models.DailyLog).delete()
        session.commit()
    finally:
        session.close()


def _seed_goal(
    description: str = "North Star goal",
    metric: str = "Metric A",
    timeline: str = "6 months",
    rank: int = 1,
) -> int:
    session = SessionLocal()
    try:
        goal = models.Goal(
            description=description,
            metric=metric,
            timeline=timeline,
            rank=rank,
        )
        session.add(goal)
        session.commit()
        session.refresh(goal)
        return goal.id
    finally:
        session.close()


def _seed_ltm(summary: str) -> None:
    session = SessionLocal()
    try:
        session.add(models.LTMProfile(summary_text=summary, version=1, token_count=10))
        session.commit()
    finally:
        session.close()


def test_get_goals_empty() -> None:
    _clear_goals()
    with TestClient(app) as client:
        response = client.get("/goals")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["north_star"] is None


def test_create_and_update_goal_content() -> None:
    _clear_goals()
    north_id = _seed_goal()

    with TestClient(app) as client:
        sub_response = client.post(
            "/goals",
            json={
                "description": "Sub-goal one",
                "metric": "Weekly review",
                "timeline": "3 months",
            },
        )
        assert sub_response.status_code == 200
        sub_id = sub_response.json()["goal"]["id"]

        update_response = client.put(
            f"/goals/{north_id}",
            json={
                "description": "Updated North Star",
                "metric": "New metric",
                "timeline": "1 year",
            },
        )
        assert update_response.status_code == 200
        goal = update_response.json()["goal"]
        assert goal["description"] == "Updated North Star"
        assert goal["metric"] == "New metric"
        assert goal["timeline"] == "1 year"

        list_response = client.get("/goals")
        goals = list_response.json()["goals"]
        assert len(goals) == 2
        assert goals[0]["id"] == north_id
        assert goals[1]["id"] == sub_id


def test_promote_sub_goal_to_north_star() -> None:
    _clear_goals()
    north_id = _seed_goal(description="Old North Star", rank=1)
    sub_id = _seed_goal(description="Rising goal", rank=2)

    with TestClient(app) as client:
        response = client.put(f"/goals/{sub_id}", json={"rank": 1})
        assert response.status_code == 200
        assert response.json()["goal"]["rank"] == 1

        goals = client.get("/goals").json()["goals"]
        assert goals[0]["id"] == sub_id
        assert any(goal["id"] == north_id and goal["rank"] == 2 for goal in goals)


def test_deactivate_sub_goal() -> None:
    _clear_goals()
    _seed_goal()
    sub_id = _seed_goal(description="Temporary goal", rank=2)

    with TestClient(app) as client:
        response = client.put(f"/goals/{sub_id}", json={"is_active": False})
        assert response.status_code == 200
        data = client.get("/goals").json()
        assert data["total"] == 1


def test_cannot_deactivate_north_star() -> None:
    _clear_goals()
    north_id = _seed_goal()

    with TestClient(app) as client:
        response = client.put(f"/goals/{north_id}", json={"is_active": False})
        assert response.status_code == 400


def test_cannot_create_second_rank_one_goal() -> None:
    _clear_goals()
    _seed_goal()

    with TestClient(app) as client:
        response = client.post(
            "/goals",
            json={"description": "Duplicate North Star", "rank": 1},
        )
        assert response.status_code == 409


def test_sync_ltm_north_star_updates_section() -> None:
    _clear_goals()
    summary = """# USER PROFILE

## Overview & North Star
- Primary Goal: Old goal
- Success Metric: Old metric
- Timeline: Old timeline

## Key Patterns
- Pattern one
"""
    _seed_ltm(summary)

    session = SessionLocal()
    try:
        sync_ltm_north_star(session, "New goal", "New metric", "New timeline")
        session.commit()
        profile = session.query(models.LTMProfile).first()
        assert profile is not None
        assert "Primary Goal: New goal" in profile.summary_text
        assert "Pattern one" in profile.summary_text
    finally:
        session.close()


def test_compute_streak_counts_consecutive_days() -> None:
    _clear_goals()
    today = local_today()
    session = SessionLocal()
    try:
        for offset in range(3):
            day = today - timedelta(days=offset)
            session.add(
                models.DailyLog(
                    date=day,
                    morning_completed=True,
                    evening_completed=offset == 0,
                )
            )
        session.commit()
        assert compute_streak(session) == 3
    finally:
        session.close()


def test_compute_streak_grace_for_today_without_activity() -> None:
    _clear_goals()
    today = local_today()
    session = SessionLocal()
    try:
        session.add(
            models.DailyLog(
                date=today - timedelta(days=1),
                morning_completed=True,
                evening_completed=False,
            )
        )
        session.commit()
        assert compute_streak(session) == 1
    finally:
        session.close()


def test_stats_endpoint_uses_computed_streak() -> None:
    _clear_goals()
    today = local_today()
    session = SessionLocal()
    try:
        session.add(
            models.SessionTracking(streak_count=0, total_sessions=5)
        )
        for offset in range(2):
            session.add(
                models.DailyLog(
                    date=today - timedelta(days=offset),
                    morning_completed=True,
                    evening_completed=True,
                )
            )
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        response = client.get("/stats")
    assert response.status_code == 200
    assert response.json()["streak"] == 2
