from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend import memory_manager, models


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    models.Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def _set_local_time(monkeypatch: pytest.MonkeyPatch, target: datetime) -> None:
    monkeypatch.setattr(memory_manager, "local_now", lambda: target)
    monkeypatch.setattr(
        memory_manager,
        "to_local",
        lambda value: memory_manager.ensure_utc(value).astimezone(target.tzinfo)
        if value
        else None,
    )


def test_morning_and_evening_recorded_within_windows(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_now = datetime(2025, 10, 13, 13, 0, tzinfo=timezone.utc)
    _set_local_time(monkeypatch, target_now)

    tracking = models.SessionTracking(
        last_morning_session=datetime(2025, 10, 13, 6, 0, tzinfo=timezone.utc),
        last_evening_session=datetime(2025, 10, 12, 22, 0, tzinfo=timezone.utc),
    )
    db_session.add(tracking)
    db_session.commit()

    result = memory_manager.check_for_missed_sessions(db_session)

    assert result["missed_sessions"] == []
    assert result["needs_catchup"] is False


def test_morning_flagged_after_noon_if_missing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_now = datetime(2025, 10, 13, 13, 0, tzinfo=timezone.utc)
    _set_local_time(monkeypatch, target_now)

    tracking = models.SessionTracking(
        last_morning_session=datetime(2025, 10, 12, 8, 0, tzinfo=timezone.utc),
        last_evening_session=datetime(2025, 10, 12, 22, 0, tzinfo=timezone.utc),
    )
    db_session.add(tracking)
    db_session.commit()

    result = memory_manager.check_for_missed_sessions(db_session)

    assert "morning" in result["missed_sessions"]
    assert result["needs_catchup"] is True


def test_evening_flagged_after_four_am_if_missing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_now = datetime(2025, 10, 13, 9, 0, tzinfo=timezone.utc)
    _set_local_time(monkeypatch, target_now)

    tracking = models.SessionTracking(
        last_morning_session=datetime(2025, 10, 13, 6, 0, tzinfo=timezone.utc),
        last_evening_session=datetime(2025, 10, 11, 22, 0, tzinfo=timezone.utc),
    )
    db_session.add(tracking)
    db_session.commit()

    result = memory_manager.check_for_missed_sessions(db_session)

    assert "evening" in result["missed_sessions"]
    assert result["needs_catchup"] is True


def test_evening_not_flagged_before_deadline(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_now = datetime(2025, 10, 13, 2, 0, tzinfo=timezone.utc)
    _set_local_time(monkeypatch, target_now)

    tracking = models.SessionTracking(
        last_morning_session=datetime(2025, 10, 12, 8, 0, tzinfo=timezone.utc),
        last_evening_session=datetime(2025, 10, 11, 22, 0, tzinfo=timezone.utc),
    )
    db_session.add(tracking)
    db_session.commit()

    result = memory_manager.check_for_missed_sessions(db_session)

    assert "evening" not in result["missed_sessions"]
    assert result["needs_catchup"] is False
