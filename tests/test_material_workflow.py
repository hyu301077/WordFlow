import json
import tempfile
import threading
import time
import wave
from contextlib import contextmanager
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from tests.support import write_dictionary
from wordflow import jobs, materials, talk_clips
from wordflow.context import AppContext
from wordflow.ui.main_window import MainWindow
from wordflow.ui.workers import CallWorker


ENGLISH = ["We can eat an apple.", "We can read a book."]
CHINESE = ["我们可以吃一个苹果。", "我们可以读一本书。"]


@pytest.fixture
def desktop_files(monkeypatch):
    # 模拟默认短数据目录，留足 Windows 句子资源路径的长度。
    workspace = tempfile.TemporaryDirectory(prefix="wf")
    tmp_path = Path(workspace.name)
    monkeypatch.setenv("WORDFLOW_DATA", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    source = tmp_path / "A short lesson.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 8000 * 10)
    yield app, tmp_path / "wordflow.db", dictionary, source
    workspace.cleanup()


@contextmanager
def open_desktop(db, dictionary):
    ctx = AppContext(db_path=db, dict_path=dictionary)
    window = MainWindow(ctx)
    window.show()
    try:
        yield ctx, window
    finally:
        window.close()
        ctx.close()


def test_media_import_deduplicates_and_reopens_plan_reader_and_listen(desktop_files, monkeypatch):
    _, db, dictionary, source = desktop_files
    calls = []

    def transcribe(*args):
        calls.append("asr")
        return [talk_clips.Segment(text, i * 5, i * 5 + 5) for i, text in enumerate(ENGLISH)], []

    class Client:
        def complete(self, system, user, timeout):
            calls.append("translation")
            return "\n".join(f"[{i:03d}] {text}" for i, text in enumerate(CHINESE, 1))

    monkeypatch.setattr(talk_clips, "transcribe_wav", transcribe)
    monkeypatch.setattr(materials, "material_client_from_settings", lambda settings: Client())
    with open_desktop(db, dictionary) as (ctx, window):
        worker = CallWorker(lambda _: None)
        def import_source(path):
            return jobs.import_files(db, dictionary, [path], ctx.settings.extract_options(), worker, data_dir=ctx.data_dir)

        first = import_source(source).files[0]
        assert first.status == "imported", first.message
        doc_id = first.document_id
        selected = source.rename(source.with_stem("same bytes"))
        again = import_source(selected).files[0]
        assert again.duplicate and again.document_id == doc_id
        assert calls == ["asr", "translation"]
        assert [row["id"] for row in ctx.store.list_study_plans()] == [doc_id]
        assert ctx.store.get_document(doc_id)["content"] == " ".join(ENGLISH)
        assert {"apple", "book"}.issubset({item["lemma"] for item in ctx.store.document_words(doc_id)})
        record = ctx.store.get_material(doc_id)
        assert Path(record["source_path"]) == selected
        folder = ctx.data_dir / record["pack_path"]

    selected.rename(selected.with_stem("moved after closing"))
    with open_desktop(db, dictionary) as (_, window):
        window.go("plans")
        plan = window.pages["plans"]
        assert plan.plan.currentData() == doc_id
        assert plan.listen.isEnabled() and plan.sentences.isEnabled()
        next(b for b in plan.findChildren(QPushButton) if b.text() == "阅读原文").click()
        reader = window.pages["reader"]
        assert window.stack_widget.currentWidget() is window.hosts["reader"]
        assert reader.browser.toPlainText() == " ".join(ENGLISH)
        reader.back.click()
        assert window.stack_widget.currentWidget() is window.hosts["plans"]
        plan.sentences.click()
        text = reader.browser.toPlainText()
        assert all(sentence in text for sentence in [*ENGLISH, *CHINESE])
        reader.back.click()
        plan.listen.click()
        listen = window.pages["listen"]
        assert window.stack_widget.currentWidget() is window.hosts["listen"]
        assert listen.folder == folder / "sentences_by_sentence"
        assert [row["text"] for row in listen.model.rows] == ENGLISH
        assert all(Path(row["path"]).is_file() for row in listen.model.rows)


def test_close_while_importing_waits_for_worker_and_restores_pending_source(desktop_files, monkeypatch):
    app, db, dictionary, source = desktop_files
    entered = threading.Event()
    release = threading.Event()

    def delayed_transcription(wav, model, model_dir, progress, cancelled):
        entered.set()
        assert release.wait(10)
        assert cancelled()
        raise talk_clips.TalkError("已取消。")

    monkeypatch.setattr(talk_clips, "transcribe_wav", delayed_transcription)
    with open_desktop(db, dictionary) as (ctx, window):
        window.go("import")
        page = window.pages["import"]
        page.files = [source]
        page.start_button.click()
        try:
            assert entered.wait(10)
            assert not window.close()
            assert window.isVisible() and page.worker.cancelled()
        finally:
            release.set()
            assert page.worker.wait(10000)
        deadline = time.monotonic() + 5
        while window.isVisible() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert not window.isVisible()
        assert json.loads(ctx.settings.get("unfinished_material_import")) == [str(source)]
        assert not ctx.store.list_study_plans()
    with open_desktop(db, dictionary) as (_, window):
        window.go("import")
        assert window.pages["import"].files == [source]
        assert window.pages["import"].start_button.isEnabled()
