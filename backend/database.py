"""Database utilities for The Catalyst backend."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, scoped_session, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    # SQLite requires this flag when used with FastAPI / multithreading
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
)

Base = declarative_base()


def init_database() -> None:
    """Create all database tables."""
    # Import models to ensure they are registered with the metadata
    from . import models  # noqa: F401  # pylint: disable=unused-import

    models.Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        session.close()
