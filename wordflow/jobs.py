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


def import_files(db_path, dict_path, paths, options, worker, ocr_max_pages: int = 40,
                 *, data_dir=None, retry_document_id=None) -> ScanReport:
    store = Store(Path(db_path))
    dictionary = Dictionary(Path(dict_path) if dict_path else None)
    try:
        importer = Importer(store, dictionary, options, ocr_max_pages=ocr_max_pages)
        report = ScanReport()
        files = [Path(path) for path in paths]
        total = len(files)
        if data_dir is not None:
            from wordflow.materials import import_material_file, material_kind
        retry = store.get_material(retry_document_id) if retry_document_id is not None else None
        if retry_document_id is not None and retry is None:
            raise ValueError("找不到要补齐的学习素材。")
        for index, path in enumerate(files, start=1):
            if worker.cancelled():
                report.cancelled = True
                break
            worker.progress.emit(index, total, path.name)
            try:
                if data_dir is not None and (retry or material_kind(path)):
                    def progress(message):
                        worker.progress.emit(index - 1, total, f"{path.name} · {message}")

                    item = import_material_file(importer, path, Path(data_dir), progress, worker.cancelled, retry)
                else:
                    item = importer.import_file(path)
                report.add(item)
            except Exception as exc:
                if not worker.cancelled():
                    report.add(ImportResult("failed", str(exc), path=str(path)))
            if worker.cancelled():
                report.cancelled = True
                break
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
