from wordflow.backup import backup_database, restore_database, validate_backup
from wordflow.store import Store


def test_backup_roundtrip_and_reject_bad_file(tmp_path):
    store = Store(tmp_path / "app.db")
    store.set_setting("theme", "dark")
    dest = tmp_path / "backups" / "one.db"
    backup_database(store, dest)
    assert validate_backup(dest) == 2
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
