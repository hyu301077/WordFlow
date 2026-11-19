import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.support import write_dictionary
from wordflow.db import SCHEMA_VERSION
from wordflow.dictionary import Dictionary
from wordflow.importer import Importer
from wordflow.store import Store


@pytest.fixture
def materials(tmp_path):
    dict_path = tmp_path / "dictionary.db"
    write_dictionary(dict_path)
    store = Store(tmp_path / "app.db")
    dictionary = Dictionary(dict_path)
    try:
        yield store, Importer(store, dictionary)
    finally:
        dictionary.close()
        store.close()


def test_original_bytes_identify_plan_without_changing_other_documents(materials, tmp_path):
    store, importer = materials
    text = "An apple and another apple."
    digest = hashlib.sha256(text.encode()).hexdigest()
    article = importer.import_article("文章", text)
    result = importer.import_material("录音", text, digest, tmp_path / "audio.mp3", "audio", "materials/record")
    assert result.document_id != article.document_id
    assert result.status == "imported"
    assert store.get_material(result.document_id)["pack_path"] == "materials/record"
    assert store.find_material(digest)["document_id"] == result.document_id
    word = next(row for row in store.document_words(result.document_id) if row["lemma"] == "apple")
    assert word["frequency"] == 2
    state = store.load_state(word["id"])
    state.status = "mastered"
    store.save_state(word["id"], state)
    store.update_document_meta(result.document_id, "我改的标题", "")
    store.set_study_plan(result.document_id, False)
    moved = tmp_path / "moved.mp3"
    again = importer.import_material("新文件名", "changed", digest, moved, "audio", "materials/record")
    assert again.document_id == result.document_id and again.duplicate
    assert store.find_material(digest)["source_path"] == str(moved.resolve())
    assert [row["title"] for row in store.list_study_plans()] == ["我改的标题"]
    word = next(row for row in store.document_words(again.document_id) if row["lemma"] == "apple")
    assert (word["frequency"], word["status"]) == (2, "mastered")
    other_recording = importer.import_material("另一个人朗读", text, "other", None, "audio", "materials/other")
    assert other_recording.document_id != result.document_id
    assert importer.import_article("重复文章", text).document_id == article.document_id


def test_no_empty_image_plan_and_atomic_publication(materials, monkeypatch):
    store, importer = materials
    args = ("截图", "apple", "image-key", None, "image", "materials/image")
    assert importer.import_material("截图", "中文", "empty", None, "image", "materials/image").status == "failed"
    assert importer.import_material("截图", "the", "filtered", None, "image", "materials/image").status == "failed"
    with pytest.raises(ValueError, match="相对路径"):
        importer.import_material(*args[:-1], "../outside")

    def fail_link(*args):
        raise RuntimeError("write failed")

    with monkeypatch.context() as patch:
        patch.setattr(store, "link_material", fail_link)
        with pytest.raises(RuntimeError, match="write failed"):
            importer.import_material(*args)
    assert store.list_documents() == []
    assert store.get_word_by_lemma("apple") is None
    assert importer.import_material(*args).status == "imported"
    media = importer.import_material("问候", "How are you?", "media-key", None, "audio", "materials/media")
    assert media.status == "imported" and store.get_document(media.document_id)["study_plan"]


def test_workers_importing_same_file_publish_one_plan(materials, tmp_path):
    main_store, _ = materials
    ready = Barrier(2)

    def import_once():
        store = Store(main_store.path)
        dictionary = Dictionary(tmp_path / "dictionary.db")
        try:
            ready.wait(timeout=10)
            return Importer(store, dictionary).import_material(
                "图片", "book book", "same", None, "image", "materials/same"
            )
        finally:
            dictionary.close()
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(import_once) for _ in range(2)]
        results = [job.result(timeout=20) for job in jobs]
    assert {result.status for result in results} == {"skipped", "imported"}
    assert len(main_store.list_study_plans()) == 1
    rows = main_store.document_words(results[0].document_id)
    assert [(row["lemma"], row["frequency"]) for row in rows] == [("book", 2)]


def test_v5_plan_and_coach_records_survive_material_migration(materials):
    old, importer = materials
    article = importer.import_article("旧文章", "A book.")
    old.set_study_plan(article.document_id)
    old.save_coach_records("page", [{"block_id": "note", "day": "2026-11-19", "content": "Read a book."}])
    old.conn.execute("DROP TABLE study_materials")
    old.conn.execute("DELETE FROM schema_migrations WHERE version = 6")
    old.conn.execute("PRAGMA user_version = 5")
    migrated = Store(old.path)
    try:
        assert migrated.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert migrated.list_study_plans()[0]["id"] == article.document_id
        assert migrated.get_material(article.document_id) is None
        assert migrated.list_coach_records("page")[0]["content"] == "Read a book."
    finally:
        migrated.close()
