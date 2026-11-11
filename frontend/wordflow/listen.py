"""检索文件夹里的 MP3，并读出同目录 index.json 里已有的句子文本。"""

from __future__ import annotations

import json
import re
from pathlib import Path


def list_clips(folder: Path) -> list[dict]:
    root = Path(folder)
    if not root.is_dir():
        return []
    captions = _caption_maps(root)
    files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".mp3"]
    files.sort(key=lambda path: _natural(path.relative_to(root).as_posix()))
    rows = []
    for path in files:
        relative = path.relative_to(root)
        name = path.name if relative.parent == Path(".") else relative.as_posix()
        info = captions.get(path.parent, {}).get(path.stem, {})
        rows.append(
            {
                "path": path,
                "name": name,
                "text": info.get("text") or "",
                "duration": info.get("duration"),
            }
        )
    return rows


def _caption_maps(root: Path) -> dict[Path, dict[str, dict]]:
    maps: dict[Path, dict[str, dict]] = {}
    for index in root.rglob("index.json"):
        if index.is_file():
            maps[index.parent] = _read_index(index)
    return maps


def _read_index(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}
    found: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip()
        if not key:
            continue
        duration = item.get("duration")
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        found[key] = {"text": str(item.get("text") or "").strip(), "duration": duration}
    return found


def _natural(text: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]
