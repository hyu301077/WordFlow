"""目录扫描、文章导入和来源合并。"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from wordflow.extract import ExtractOptions, extract_words
from wordflow.parsers import parse_path
from wordflow.timeutil import now_local, to_iso

SUPPORTED = {".txt", ".md", ".markdown", ".docx", ".pdf"}
IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    "ecdict-tmp",
}
MAX_FILE_SIZE = 80 * 1024 * 1024


@dataclass
class ImportResult:
    status: str
    message: str
    path: str = ""
    document_id: int | None = None
    unique_words: int = 0
    total_tokens: int = 0
    duplicate: bool = False


@dataclass
class ScanReport:
    files: list[ImportResult] = field(default_factory=list)
    cancelled: bool = False

    def add(self, result: ImportResult) -> None:
        self.files.append(result)

    def count(self, status: str) -> int:
        return sum(1 for item in self.files if item.status == status)


def path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.resolve())))


def discover_files(root: Path, mode: str) -> list[Path]:
    root = root.resolve()
    found: list[Path] = []
    if mode == "direct":
        found.extend(_files_under(root))
    elif mode == "recursive_output":
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = _visible_dirs(dirnames)
            current = Path(dirpath)
            if not _inside_output(current, root):
                continue
            for name in filenames:
                path = current / name
                if _supported(path):
                    found.append(path)
    else:
        if root.is_dir():
            for child in root.iterdir():
                if not child.is_dir() or not _dir_allowed(child.name):
                    continue
                output = child / "output"
                if output.is_dir():
                    found.extend(_files_under(output))
    unique = {path_key(path): path for path in found}
    return [unique[key] for key in sorted(unique)]


def in_scan_scope(path: Path, root: Path, mode: str) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    parts = [part.lower() for part in relative.parts]
    if mode == "direct":
        return True
    if "output" not in parts:
        return False
    index = parts.index("output")
    if mode == "recursive_output":
        return True
    return index == 1


class Importer:
    def __init__(self, store, dictionary, options: ExtractOptions | None = None, ocr_max_pages: int = 40):
        self.store = store
        self.dictionary = dictionary
        self.options = options or ExtractOptions()
        self.ocr_max_pages = max(1, int(ocr_max_pages or 40))

    def scan(self, root: Path, mode: str, cancel=None, progress=None) -> ScanReport:
        root = Path(root)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError("文件夹不存在")
        files = discover_files(root, mode)
        report = ScanReport()
        total = len(files)
        if progress:
            progress(0, total, "正在准备")
        seen: set[str] = set()
        for index, path in enumerate(files, start=1):
            if cancel and cancel():
                report.cancelled = True
                break
            if progress:
                progress(index, total, str(path))
            try:
                result = self.import_file(path)
            except Exception as exc:
                result = ImportResult("failed", str(exc), path=str(path))
            report.add(result)
            seen.add(path_key(path))
        if not report.cancelled:
            self._mark_deleted(root, mode, seen)
            self.store.delete_untouched_orphans()
        return report

    def import_file(self, path: Path, kind: str = "file") -> ImportResult:
        path = Path(path)
        if not path.exists() or not path.is_file():
            return ImportResult("failed", "文件不存在", path=str(path))
        stat = path.stat()
        if stat.st_size > MAX_FILE_SIZE:
            return ImportResult("skipped", "文件超过 80MB，已跳过", path=str(path))
        key = path_key(path)
        existing = self.store.get_document_by_path(key)
        if (
            existing
            and existing["file_size"] == stat.st_size
            and existing["mtime_ns"] == stat.st_mtime_ns
            and existing["status"] in {"active", "skipped"}
        ):
            return ImportResult(
                "skipped",
                existing["error_message"] or "文件未变化",
                path=str(path),
                document_id=existing["id"],
            )
        fingerprint = _hash_file(path)
        if existing and existing["fingerprint"] == fingerprint and existing["status"] in {"active", "skipped"}:
            self.store.touch_document(existing["id"], stat.st_size, stat.st_mtime_ns)
            return ImportResult(
                "skipped",
                existing["error_message"] or "文件未变化",
                path=str(path),
                document_id=existing["id"],
            )
        parsed = parse_path(path, ocr_max_pages=self.ocr_max_pages)
        title = path.stem
        if parsed.scanned_pdf or (parsed.error and not parsed.text):
            message = parsed.warning or parsed.error or "无法读取"
            status = "skipped" if parsed.scanned_pdf else "failed"
            document_id = self._save_shell(
                existing=existing,
                kind=kind,
                title=title,
                path=path,
                key=key,
                size=stat.st_size,
                mtime=stat.st_mtime_ns,
                fingerprint=fingerprint,
                status="skipped" if parsed.scanned_pdf else "active",
                error=message,
                text="",
            )
            return ImportResult(status, message, path=str(path), document_id=document_id)
        return self._import_text(
            title=title,
            text=parsed.text,
            kind=kind,
            path=path,
            key=key,
            tags=None,
            fingerprint=fingerprint,
            size=stat.st_size,
            mtime=stat.st_mtime_ns,
            existing=existing,
            warning=parsed.warning,
        )

    def import_article(self, title: str, text: str, tags: str = "", source_path: Path | None = None) -> ImportResult:
        text = text.replace("\r\n", "\n").strip()
        if not text:
            return ImportResult("failed", "文章内容为空")
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = None
        key = None
        size = None
        mtime = None
        if source_path:
            return self.import_file(source_path, kind="article")
        duplicate = self.store.get_document_by_fingerprint(fingerprint)
        if duplicate:
            return ImportResult(
                "skipped",
                "这篇文章已经导入过",
                document_id=duplicate["id"],
                duplicate=True,
            )
        title = title.strip() or _title_from_text(text)
        return self._import_text(
            title=title,
            text=text,
            kind="article",
            path=None,
            key=key,
            tags=tags,
            fingerprint=fingerprint,
            size=size,
            mtime=mtime,
            existing=existing,
            warning="",
        )

    def import_material(
        self,
        title: str,
        text: str,
        fingerprint: str,
        source_path: Path | str | None,
        material_kind: str,
        pack_path: Path | str,
    ) -> ImportResult:
        """将已提取的原始英文和素材包作为一份学习计划发布。"""
        relative_pack = PureWindowsPath(pack_path)
        if relative_pack.anchor or not relative_pack.parts or ".." in relative_pack.parts:
            raise ValueError("素材目录必须是数据目录下的相对路径")
        if not fingerprint:
            raise ValueError("缺少素材指纹")
        source = str(Path(source_path).resolve()) if source_path else None
        with self.store.tx():
            existing = self.store.find_material(fingerprint)
            if existing:
                document_id = existing["document_id"]
                document = self.store.get_document(document_id)
                if not document["study_plan"]:
                    self.store.set_study_plan(document_id, True)
                if source and source != existing["source_path"]:
                    self.store.update_material_source(document_id, source)
                return ImportResult(
                    "skipped", "已打开已有学习计划", path=source or "", document_id=document_id,
                    unique_words=document["unique_count"], total_tokens=document["word_count"], duplicate=True,
                )
            text = text.replace("\r\n", "\n").strip()
            if not re.search(r"[A-Za-z]", text):
                return ImportResult("failed", "素材中未提取到英文", path=source or "")
            result = self._import_text(
                title=title.strip() or _title_from_text(text), text=text, kind="material",
                path=None, key=None, tags=None, fingerprint=None, size=None, mtime=None,
                existing=None, warning="", require_words=material_kind in {"image", "screenshot"},
            )
            result.path = source or ""
            if result.document_id is None:
                return result
            self.store.link_material(result.document_id, fingerprint, source, material_kind, relative_pack.as_posix())
            self.store.set_study_plan(result.document_id)
            return result

    def _import_text(
        self,
        *,
        title: str,
        text: str,
        kind: str,
        path: Path | None,
        key: str | None,
        tags: str | None,
        fingerprint: str | None,
        size: int | None,
        mtime: int | None,
        existing: dict | None,
        warning: str,
        require_words: bool = False,
    ) -> ImportResult:
        words, total_tokens = extract_words(text, self.options, self.dictionary)
        if require_words and not words:
            return ImportResult("failed", "未提取到适合学习的英文单词")
        now = to_iso(now_local())
        with self.store.tx():
            document_id = self.store.upsert_document(
                {
                    "kind": kind,
                    "title": title,
                    "path": str(path.resolve()) if path else None,
                    "path_key": key,
                    "tags": tags,
                    "content": text,
                    "file_size": size,
                    "mtime_ns": mtime,
                    "fingerprint": fingerprint,
                    "status": "active",
                    "error_message": warning or None,
                    "word_count": total_tokens,
                    "unique_count": len(words),
                    "imported_at": now,
                    "updated_at": now,
                }
            )
            self.store.clear_document_links(document_id)
            for item in words:
                entry = self.dictionary.lookup(item.lemma) if self.dictionary else None
                word_id = self.store.ensure_word(item.lemma, item.lemma, entry)
                for surface, frequency in item.surfaces.items():
                    self.store.add_occurrence(word_id, document_id, surface, frequency)
                if item.example:
                    self.store.add_example(word_id, document_id, item.example)
        status = "updated" if existing else "imported"
        message = warning or ("已更新来源" if existing else "已导入")
        if not words:
            message = "未提取到适合学习的英文单词"
        return ImportResult(
            status,
            message,
            path=str(path) if path else "",
            document_id=document_id,
            unique_words=len(words),
            total_tokens=total_tokens,
        )

    def _save_shell(self, **kwargs) -> int:
        now = to_iso(now_local())
        return self.store.upsert_document(
            {
                "kind": kwargs["kind"],
                "title": kwargs["title"],
                "path": str(kwargs["path"].resolve()),
                "path_key": kwargs["key"],
                "tags": None,
                "content": kwargs["text"],
                "file_size": kwargs["size"],
                "mtime_ns": kwargs["mtime"],
                "fingerprint": kwargs["fingerprint"],
                "status": kwargs["status"],
                "error_message": kwargs["error"],
                "word_count": 0,
                "unique_count": 0,
                "imported_at": now,
                "updated_at": now,
            }
        )

    def _mark_deleted(self, root: Path, mode: str, seen: set[str]) -> None:
        for document in self.store.active_file_documents():
            if not document["path"]:
                continue
            path = Path(document["path"])
            if not in_scan_scope(path, root, mode):
                continue
            if document["path_key"] in seen:
                continue
            if not path.exists():
                self.store.mark_document_missing(document["id"])


def _files_under(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = _visible_dirs(dirnames)
        for name in filenames:
            path = Path(dirpath) / name
            if _supported(path):
                found.append(path)
    return found


def _visible_dirs(names: list[str]) -> list[str]:
    return [name for name in names if _dir_allowed(name)]


def _dir_allowed(name: str) -> bool:
    return name.lower() not in IGNORE_DIRS and not name.startswith(".")


def _supported(path: Path) -> bool:
    name = path.name
    if name.startswith("~$") or name.startswith("."):
        return False
    return path.suffix.lower() in SUPPORTED


def _inside_output(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return any(part.lower() == "output" for part in relative.parts)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:40]
    return "未命名文章"
