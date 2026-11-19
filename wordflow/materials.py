"""将同一素材的正文、句子音频与学习计划关联起来。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QLockFile

from wordflow.ai import material_client_from_settings
from wordflow.image_material import IMAGE_EXTENSIONS, enrich_image, prepare_image
from wordflow.settings import Settings
from wordflow.talk_clips import MEDIA_EXTENSIONS, enrich_material_talk, prepare_material_talk


def material_kind(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return "media"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return None


def material_folder(data_dir: Path, pack_path: str) -> Path:
    path = (data_dir / pack_path).resolve()
    root = (data_dir / "materials").resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("素材目录不在词流的数据目录中。")
    return path


def has_media_source_cache(folder: Path) -> bool:
    wav = folder / "talk.wav"
    if wav.is_file() and wav.stat().st_size:
        return True
    try:
        manifest = json.loads((folder / "output" / "material_talk.json").read_text(encoding="utf-8"))
        spans = manifest["spans"]
        if not isinstance(spans, list) or not spans:
            return False
        clips = folder / "sentences_by_sentence"
        return all((clips / f"{n:03d}.mp3").stat().st_size > 0 for n in range(1, len(spans) + 1))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def sentence_rows(folder: Path) -> list[dict]:
    try:
        rows = json.loads((folder / "sentences_by_sentence" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("text"), str)]


def source_fingerprint(path: Path, cancelled) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            if cancelled():
                raise InterruptedError("已取消。")
            digest.update(block)
    return digest.hexdigest()


def import_material_file(importer, path, data_dir, report, cancelled, retry=None):
    store = importer.store
    path = Path(path)
    if retry:
        fingerprint, kind = retry["fingerprint"], retry["material_kind"]
        if path.is_file() and source_fingerprint(path, cancelled) != fingerprint:
            raise ValueError("这个文件的内容与计划中的原素材不同。请选择原文件，或把新文件作为新素材导入。")
    else:
        kind = material_kind(path)
        fingerprint = source_fingerprint(path, cancelled)
    existing = retry or store.find_material(fingerprint)
    pack_path = existing["pack_path"] if existing else f"materials/{fingerprint}"
    folder = material_folder(data_dir, pack_path)
    folder.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(folder / "import.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise RuntimeError("这份素材正在另一项导入任务中处理。")
    try:
        settings = Settings(store)
        if kind == "image":
            if existing:
                text = store.get_document(existing["document_id"])["content"]
            else:
                report("正在本机识别截图中的英文。")
                text = prepare_image(path, folder)
        else:
            local = prepare_material_talk(path, folder, settings.get("talk_model", "small"),
                                          data_dir / "models", progress=report, cancelled=cancelled)
            text = local.full_text
        title = f"截图 {fingerprint[:8]}" if path.parent == data_dir / "screenshots" else path.stem
        result = importer.import_material(title, text, fingerprint, path, kind, pack_path)
        if not result.document_id:
            return result
        try:
            if cancelled():
                raise InterruptedError("已取消。")
            client = material_client_from_settings(Settings(store))
            if kind == "image":
                words = store.document_words(result.document_id)
                targets = [row["lemma"] for row in words if row["status"] != "mastered"]
                if not targets:
                    targets = [row["lemma"] for row in words]
                known, _ = store.list_words(statuses=("mastered",), limit=32)
                note = enrich_image(folder, targets, [row["lemma"] for row in known], client,
                                    settings, progress=report, cancelled=cancelled)
            else:
                talk = local
                if client and local.pending_translations:
                    talk = enrich_material_talk(folder, client, progress=report, cancelled=cancelled)
                note = talk.warning
                if talk.pending_translations and not client:
                    note = f"{note} 有 {talk.pending_translations} 句待译，可启用在线助手的素材自动处理后补齐。".strip()
            result.message = "已关联学习计划。" + (note or "")
        except Exception as exc:
            result.message = f"本地学习计划已保存，可在计划中补齐素材。{exc}"
        return result
    finally:
        lock.unlock()
