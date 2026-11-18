import sqlite3

import pytest

from wordflow.backup import BackupError, backup_database, restore_database, validate_backup
from wordflow.store import Store


def test_backup_roundtrip_and_reject_bad_file(tmp_path):
    store = Store(tmp_path / "app.db")
    store.set_setting("theme", "dark")
    dest = tmp_path / "backups" / "one.db"
    backup_database(store, dest)
    assert validate_backup(dest) == 4
    store.set_setting("theme", "light")
    safety = restore_database(store, dest, tmp_path / "app.db", tmp_path / "backups")
    assert safety.exists()
    restored = Store(tmp_path / "app.db")
    assert restored.get_setting("theme") == "dark"
    restored.close()
    try:
        validate_backup(tmp_path / "missing.db")
        assert False
    except Exception as exc:
        assert "备份" in str(exc)


def test_failed_backup_preserves_existing_file_and_active_database(tmp_path, monkeypatch):
    store = Store(tmp_path / "app.db")
    store.set_setting("theme", "dark")
    dest = backup_database(store, tmp_path / "previous.db")
    with pytest.raises(BackupError, match="正在使用"):
        backup_database(store, store.path)
    original = dest.read_bytes()

    def fail_write(*args):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(sqlite3, "connect", fail_write)
    with pytest.raises(BackupError, match="disk full"):
        backup_database(store, dest)
    assert dest.read_bytes() == original
    assert store.get_setting("theme") == "dark"
    store.close()


def test_restore_includes_committed_wal_and_rejects_active_file(tmp_path):
    store = Store(tmp_path / "app.db")
    source = Store(tmp_path / "snapshot.db")
    source.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    source.set_setting("theme", "dark")
    with pytest.raises(BackupError, match="正在使用"):
        restore_database(store, store.path, store.path, tmp_path)
    restore_database(store, source.path, store.path, tmp_path)
    source.close()
    restored = Store(store.path)
    assert restored.get_setting("theme") == "dark"
    restored.close()
