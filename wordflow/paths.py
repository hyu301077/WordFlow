"""路径解析。用户数据放在本机应用数据目录，不写死任何用户名。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    override = os.environ.get("WORDFLOW_DATA")
    if override:
        path = Path(override).expanduser()
    else:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            path = Path(local) / "WordFlow"
        else:
            path = Path.home() / ".wordflow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    override = os.environ.get("WORDFLOW_DB")
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return user_data_dir() / "wordflow.db"


def backup_dir() -> Path:
    path = user_data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return user_data_dir() / "wordflow.log"


def find_dictionary() -> Path | None:
    candidates: list[Path] = []
    override = os.environ.get("WORDFLOW_DICT")
    if override:
        candidates.append(Path(override).expanduser())
    root = bundle_root()
    data = user_data_dir()
    candidates.extend(
        [
            root / "data" / "ecdict.db",
            data / "ecdict.db",
            root / "data" / "stardict.db",
            data / "stardict.db",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def stopwords_path() -> Path | None:
    custom = user_data_dir() / "stopwords.txt"
    if custom.is_file():
        return custom
    bundled = bundle_root() / "data" / "stopwords.txt"
    if bundled.is_file():
        return bundled
    return None


def confusion_path() -> Path | None:
    bundled = bundle_root() / "data" / "confusion_pairs.txt"
    if bundled.is_file():
        return bundled
    return None
