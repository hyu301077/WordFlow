"""后台任务用自己的数据库连接，避免和界面线程共用 SQLite。"""

from __future__ import annotations

from pathlib import Path

from wordflow.dictionary import Dictionary
from wordflow.importer import ImportResult, Importer, ScanReport
from wordflow.store import Store
from wordflow.study import StudyService


def scan_documents(db_path, dict_path, root, mode, options, worker, ocr_max_pages: int = 40):
    store = Store(Path(db_path))
    dictionary = Dictionary(Path(dict_path) if dict_path else None)
    try:
        importer = Importer(store, dictionary, options, ocr_max_pages=ocr_max_pages)
        return importer.scan(
            Path(root),
            mode,
            cancel=worker.cancelled,
            progress=lambda current, total, label: worker.progress.emit(current, total, label),
        )
    finally:
        store.close()
        dictionary.close()


def import_files(db_path, dict_path, paths, options, worker, ocr_max_pages: int = 40) -> ScanReport:
    store = Store(Path(db_path))
    dictionary = Dictionary(Path(dict_path) if dict_path else None)
    try:
        importer = Importer(store, dictionary, options, ocr_max_pages=ocr_max_pages)
        report = ScanReport()
        files = [Path(path) for path in paths]
        total = len(files)
        for index, path in enumerate(files, start=1):
            if worker.cancelled():
                report.cancelled = True
                break
            worker.progress.emit(index, total, path.name)
            try:
                report.add(importer.import_file(path))
            except Exception as exc:
                report.add(ImportResult("failed", str(exc), path=str(path)))
        return report
    finally:
        store.close()
        dictionary.close()


def import_article_text(db_path, dict_path, title, text, tags, options):
    store = Store(Path(db_path))
    dictionary = Dictionary(Path(dict_path) if dict_path else None)
    try:
        return Importer(store, dictionary, options).import_article(title, text, tags)
    finally:
        store.close()
        dictionary.close()


def import_article_file(db_path, dict_path, path, options, ocr_max_pages: int = 40):
    store = Store(Path(db_path))
    dictionary = Dictionary(Path(dict_path) if dict_path else None)
    try:
        return Importer(store, dictionary, options, ocr_max_pages=ocr_max_pages).import_file(Path(path), kind="article")
    finally:
        store.close()
        dictionary.close()


def start_session(db_path, dict_path, kind: str, payload: dict) -> dict:
    store = Store(Path(db_path))
    dictionary = Dictionary(Path(dict_path) if dict_path else None)
    try:
        service = StudyService(store, dictionary)
        if kind == "placement":
            return service.start_placement(**payload)
        if kind == "learn":
            return service.start_learn(**payload)
        if kind == "review":
            return service.start_review(**payload)
        raise ValueError(kind)
    finally:
        store.close()
        dictionary.close()
