"""SQLite database backup and restore for The Catalyst."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlparse

from .config import DATA_DIR, DATABASE_URL

MAX_BACKUPS = 5
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_PREFIX = "catalyst_"
BACKUP_SUFFIX = ".db"


def resolve_db_path(database_url: str = DATABASE_URL) -> Path:
    """Resolve a SQLite file path from a SQLAlchemy-style DATABASE_URL."""

    if not database_url.startswith("sqlite"):
        raise ValueError(
            f"Backups only support SQLite databases (got {database_url!r})."
        )

    parsed = urlparse(database_url)
    if parsed.netloc == ":memory:" or parsed.path in (":memory:", "/:memory:"):
        raise ValueError("In-memory databases cannot be backed up.")

    raw_path = unquote(parsed.path)
    if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
        # Windows: /C:/Users/... -> C:/Users/...
        raw_path = raw_path[1:]

    path = Path(raw_path)
    if not path.is_absolute():
        path = (DATA_DIR / path).resolve()
    return path


def list_backups(backup_dir: Optional[Path] = None) -> List[Path]:
    """Return backup files newest-first."""

    directory = backup_dir or BACKUP_DIR
    if not directory.exists():
        return []

    candidates = sorted(
        directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates


def _prune_backups(
    backup_dir: Optional[Path] = None, max_backups: int = MAX_BACKUPS
) -> List[Path]:
    """Delete oldest backups beyond max_backups. Returns removed paths."""

    directory = backup_dir or BACKUP_DIR
    backups = list_backups(directory)
    removed: List[Path] = []
    for stale in backups[max_backups:]:
        stale.unlink(missing_ok=True)
        removed.append(stale)
    return removed


def create_backup(
    *,
    db_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    max_backups: int = MAX_BACKUPS,
) -> Optional[Path]:
    """Create a consistent SQLite backup. Returns destination path or None if no DB."""

    source = db_path or resolve_db_path()
    if not source.exists():
        return None

    directory = backup_dir or BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    destination = directory / f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}"

    source_conn = sqlite3.connect(source)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    _prune_backups(directory, max_backups)
    return destination


def restore_backup(
    backup_file: Path,
    *,
    db_path: Optional[Path] = None,
) -> Path:
    """Restore database from a backup file. Returns the live database path."""

    source = Path(backup_file)
    if not source.is_file():
        raise FileNotFoundError(f"Backup not found: {source}")

    target = db_path or resolve_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    source_conn = sqlite3.connect(source)
    dest_conn = sqlite3.connect(target)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{target}{suffix}")
        if sidecar.exists():
            sidecar.unlink()

    return target


def backup_on_startup() -> Optional[Path]:
    """Create a startup backup when the live database exists."""

    try:
        path = create_backup()
    except ValueError as exc:
        print(f"⚠️  Database backup skipped: {exc}")
        return None

    if path is None:
        return None

    print(f"💾 Database backup saved: {path}")
    return path


def _format_backup_line(index: int, path: Path) -> str:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    size_kb = path.stat().st_size / 1024
    return (
        f"  [{index}] {path.name}  "
        f"({modified.strftime('%Y-%m-%d %H:%M:%S UTC')}, {size_kb:.1f} KB)"
    )


def run_backup_cli(_argv: Optional[List[str]] = None) -> int:
    """Manual backup without starting the app."""

    try:
        path = create_backup()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if path is None:
        print("No database file found — nothing to back up.")
        return 0

    print(f"Backup created: {path}")
    backups = list_backups()
    print(f"Keeping {len(backups)} backup(s) (max {MAX_BACKUPS}).")
    return 0


def run_restore_cli(argv: Optional[List[str]] = None) -> int:
    """Restore a backup from the CLI."""

    parser = argparse.ArgumentParser(
        description="Restore The Catalyst SQLite database from a backup."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list",
        action="store_true",
        help="List available backups (newest first).",
    )
    group.add_argument(
        "--latest",
        action="store_true",
        help="Restore the most recent backup.",
    )
    group.add_argument(
        "--file",
        type=str,
        metavar="PATH",
        help="Restore a specific backup file.",
    )
    group.add_argument(
        "--index",
        type=int,
        metavar="N",
        help="Restore backup by list index (1 = newest).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )

    args = parser.parse_args(argv)

    if args.list:
        backups = list_backups()
        if not backups:
            print("No backups found.")
            return 0
        print("Available backups (newest first):")
        for idx, path in enumerate(backups, start=1):
            print(_format_backup_line(idx, path))
        return 0

    if args.latest:
        backups = list_backups()
        if not backups:
            print("Error: no backups found.", file=sys.stderr)
            return 1
        backup_path = backups[0]
    elif args.index is not None:
        backups = list_backups()
        if args.index < 1 or args.index > len(backups):
            print(
                f"Error: index must be between 1 and {len(backups)}.",
                file=sys.stderr,
            )
            return 1
        backup_path = backups[args.index - 1]
    else:
        backup_path = Path(args.file)
        directory = BACKUP_DIR
        if not backup_path.is_absolute():
            backup_path = (directory / backup_path).resolve()

    if not args.yes:
        try:
            target = resolve_db_path()
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print(f"Restore {backup_path}")
        print(f"  -> {target}")
        print("Stop the running server before restoring.")
        answer = input("Continue? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Restore cancelled.")
            return 0

    try:
        target = restore_backup(backup_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Restored database from {backup_path.name} -> {target}")
    return 0
