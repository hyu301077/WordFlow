"""数据库备份与恢复。恢复前会先检查文件，并保留一份恢复前的副本。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from wordflow.db import SCHEMA_VERSION
from wordflow.timeutil import now_local


class BackupError(Exception):
    pass


def backup_database(store, dest: Path) -> Path:
    dest = Path(dest)
    temporary = None
    try:
        if dest.exists() and dest.samefile(store.path):
            raise BackupError("备份位置是正在使用的学习数据库，请选择另一个文件。")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=dest.parent, prefix=".wordflow-", suffix=".db", delete=False) as handle:
            temporary = Path(handle.name)
        with closing(sqlite3.connect(str(temporary))) as target:
            store.conn.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")
        temporary.replace(dest)
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f"备份写入失败：{exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dest


def validate_backup(path: Path) -> int:
    path = Path(path)
    if not path.is_file():
        raise BackupError("找不到备份文件")
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
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
    if source.samefile(db_path):
        raise BackupError("所选文件是正在使用的学习数据库，请选择一份备份。")
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    safety = safety_dir / f"wordflow-pre-restore-{stamp}-{uuid4().hex[:8]}.db"
    backup_database(store, safety)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as snapshot:
        if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BackupError("备份未通过数据库完整性检查。")
        snapshot.backup(store.conn)
    store.close()
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
