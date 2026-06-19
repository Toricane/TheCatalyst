import os
import sqlite3
from pathlib import Path

import pytest

from backend import db_backup


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "catalyst.db"
    backup_dir = data_dir / "backups"

    monkeypatch.setattr(db_backup, "DATA_DIR", data_dir)
    monkeypatch.setattr(db_backup, "BACKUP_DIR", backup_dir)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    yield db_path


def _seed_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('alpha')")
    conn.commit()
    conn.close()


def test_create_backup_and_prune_to_five(isolated_data_dir):
    db_path = isolated_data_dir
    _seed_db(db_path)

    created = []
    for _ in range(7):
        path = db_backup.create_backup(
            db_path=db_path, backup_dir=db_backup.BACKUP_DIR, max_backups=5
        )
        assert path is not None
        created.append(path)

    backups = db_backup.list_backups(db_backup.BACKUP_DIR)
    assert len(backups) == 5
    assert created[-1] == backups[0]


def test_restore_backup_replaces_live_database(isolated_data_dir):
    db_path = isolated_data_dir
    _seed_db(db_path)
    backup_path = db_backup.create_backup(db_path=db_path)
    assert backup_path is not None

    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM items")
    conn.execute("INSERT INTO items (name) VALUES ('gone')")
    conn.commit()
    conn.close()

    db_backup.restore_backup(backup_path, db_path=db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT name FROM items").fetchone()
    conn.close()
    assert row[0] == "alpha"


def test_resolve_db_path_rejects_memory(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(ValueError, match="In-memory"):
        db_backup.resolve_db_path()


def test_run_restore_cli_list(capsys, isolated_data_dir):
    db_path = isolated_data_dir
    _seed_db(db_path)
    db_backup.create_backup(db_path=db_path)

    code = db_backup.run_restore_cli(["--list"])
    assert code == 0
    output = capsys.readouterr().out
    assert "catalyst_" in output
