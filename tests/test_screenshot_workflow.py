from types import SimpleNamespace

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from tests.support import write_dictionary
from wordflow.context import AppContext
from wordflow.extract import ExtractOptions
from wordflow.importer import Importer
from wordflow.materials import has_media_source_cache, material_folder
from wordflow.ui.main_window import MainWindow


def test_paste_screenshot_once_and_open_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("WORDFLOW_DATA", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    dictionary = tmp_path / "test-dictionary.db"
    write_dictionary(dictionary)
    ctx = AppContext(tmp_path / "study.db", dictionary)
    window = MainWindow(ctx)
    image = QImage(200, 100, QImage.Format_RGB32)
    image.fill(0xFFFFFF)
    monkeypatch.setattr(QApplication, "clipboard", lambda: SimpleNamespace(image=lambda: image))
    monkeypatch.setattr("wordflow.image_material.recognize_image", lambda _: "apple apple bank")
    page = window.pages["import"]
    window.go("import")
    try:
        page.paste.click()
        assert page.worker.wait(10000)
        app.processEvents()
        assert page.doc_picker.count() == 1
        document_id = page.doc_picker.currentData()
        assert page.plan_button.text() == "打开学习计划"
        page.plan_button.click()
        plan = window.pages["plans"]
        assert plan.plan.currentData() == document_id
        assert "2 个词待生成例句" in plan.material_status.text()
        assert not plan.listen.isEnabled()
        assert [(row["lemma"], row["frequency"]) for row in plan.model.rows] == [("apple", 2), ("bank", 1)]
        window.go("import")
        page.paste.click()
        assert page.worker.wait(10000)
        app.processEvents()
        assert page.doc_picker.currentData() == document_id
        assert len(ctx.store.list_study_plans()) == 1
    finally:
        window.close()
        ctx.close()


def test_resume_screenshot_from_db_after_backup_restored(tmp_path, monkeypatch):
    from wordflow.materials import import_material_file

    monkeypatch.setenv("WORDFLOW_DATA", str(tmp_path))
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    ctx = AppContext(tmp_path / "study.db", dictionary)
    try:
        importer = Importer(ctx.store, ctx.dictionary, ExtractOptions())
        original = tmp_path / "moved.png"
        fingerprint = "a" * 64
        result = importer.import_material("截图", "apple bank", fingerprint, original, "image",
                                          f"materials/{fingerprint}")
        record = ctx.store.get_material(result.document_id)
        assert not material_folder(tmp_path, record["pack_path"]).exists()
        retry = import_material_file(importer, original, tmp_path, lambda _: None, lambda: False, record)
        assert retry.document_id == result.document_id
        assert "例句待生成" in retry.message
        assert len(ctx.store.list_study_plans()) == 1
    finally:
        ctx.close()


def test_missing_original_can_only_be_replaced_by_complete_audio_cache(tmp_path):
    folder = tmp_path / "pack"
    output = folder / "output"
    output.mkdir(parents=True)
    (output / "word_timeline.json").write_text("{}")
    assert not has_media_source_cache(folder)
    (output / "material_talk.json").write_text('{"spans": [{}, {}]}')
    clips = folder / "sentences_by_sentence"
    clips.mkdir()
    (clips / "001.mp3").write_bytes(b"first clip")
    assert not has_media_source_cache(folder)
    (clips / "002.mp3").write_bytes(b"second clip")
    assert has_media_source_cache(folder)
