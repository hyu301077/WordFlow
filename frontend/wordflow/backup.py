"""数据库备份与恢复。恢复前会先检查文件，并保留一份恢复前的副本。"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from wordflow.db import SCHEMA_VERSION
from wordflow.timeutil import now_local


class BackupError(Exception):
    pass


def backup_database(store, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    target = sqlite3.connect(str(dest))
    try:
        store.conn.backup(target)
    finally:
        target.close()
    if not dest.is_file() or dest.stat().st_size == 0:
        raise BackupError("备份文件没有写成功")
    return dest


def validate_backup(path: Path) -> int:
    path = Path(path)
    if not path.is_file():
        raise BackupError("找不到备份文件")
    try:
        connection = sqlite3.connect(str(path))
    except sqlite3.Error as exc:
        raise BackupError(f"无法读取备份：{exc}") from exc
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "words" not in tables or "schema_migrations" not in tables or "learning_states" not in tables:
            raise BackupError("这不是可用的 WordFlow 备份")
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        version = row[0]
        if version is None:
            raise BackupError("备份缺少数据库版本")
        if int(version) > SCHEMA_VERSION:
            raise BackupError("这份备份来自更新的 WordFlow，请先升级软件再恢复")
        return int(version)
    except sqlite3.Error as exc:
        raise BackupError(f"备份校验失败：{exc}") from exc
    finally:
        connection.close()


def restore_database(store, source: Path, db_path: Path, safety_dir: Path) -> Path:
    source = Path(source)
    db_path = Path(db_path)
    safety_dir = Path(safety_dir)
    validate_backup(source)
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    safety = safety_dir / f"wordflow-pre-restore-{stamp}.db"
    backup_database(store, safety)
    try:
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    store.close()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(db_path) + suffix)
        if extra.exists():
            extra.unlink()
    try:
        shutil.copy2(source, db_path)
        validate_backup(db_path)
    except Exception:
        shutil.copy2(safety, db_path)
        raise
    return safety


def maybe_auto_backup(store, folder: Path) -> Path | None:
    folder.mkdir(parents=True, exist_ok=True)
    today = now_local().strftime("%Y%m%d")
    existing = sorted(folder.glob("wordflow-auto-*.db"))
    if any(today in path.name for path in existing):
        return None
    dest = folder / f"wordflow-auto-{today}.db"
    backup_database(store, dest)
    kept = sorted(folder.glob("wordflow-auto-*.db"))
    for old in kept[:-10]:
        old.unlink(missing_ok=True)
    return dest
