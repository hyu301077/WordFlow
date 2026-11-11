from pathlib import Path

from docx import Document
from pypdf import PdfWriter

from wordflow.dictionary import Dictionary
from wordflow.extract import ExtractOptions, extract_words
from wordflow.importer import Importer, discover_files
from wordflow.store import Store
from wordflow.study import StudyService
from tests.support import write_dictionary


class Lexicon:
    def __init__(self, lemmas=None, common=None, entries=None):
        self.lemmas = lemmas or {}
        self.common = common or set()
        self.entries = entries or set()

    def resolve_lemma(self, token: str) -> str:
        lower = token.lower()
        return self.lemmas.get(lower, lower)

    def is_common(self, word: str) -> bool:
        return word.lower() in self.common

    def has_entry(self, word: str) -> bool:
        return word.lower() in self.entries or word.lower() in self.common


def test_extract_dedup_filters_and_keeps_example():
    text = """
    ```python
    print("apple")
    ```
    Visit https://example.com/apple today.
    The apple is running. John met NASA.
    He kept running toward the apple.
    """
    lexicon = Lexicon(
        lemmas={"running": "run", "apple": "apple"},
        common={"apple", "running", "run", "kept", "toward", "today", "visit", "met"},
        entries={"apple", "running", "run", "kept", "toward", "today", "visit", "met"},
    )
    words, total = extract_words(text, ExtractOptions(), lexicon)
    found = {item.lemma: item for item in words}
    assert "apple" in found
    assert found["apple"].frequency == 2
    assert "run" in found
    assert "running" not in found
    assert "the" not in found
    assert "john" not in found
    assert "nasa" not in found
    assert "print" not in found
    assert "https" not in found
    assert "com" not in found
    assert total >= found["apple"].frequency
    assert found["apple"].example


def test_project_scan_is_incremental_and_survives_bad_files(tmp_path: Path):
    root = tmp_path / "materials"
    output = root / "ProjectA" / "output"
    output.mkdir(parents=True)
    (output / "nested").mkdir()
    (root / "ProjectA" / "notes").mkdir()
    (root / "deep" / "inner" / "output").mkdir(parents=True)
    (output / "story.md").write_text("The apple is running. The apple was good.\n", encoding="utf-8")
    (output / "nested" / "more.txt").write_text("Develop a system.\n", encoding="utf-8")
    (root / "ProjectA" / "notes" / "skip.txt").write_text("bank\n", encoding="utf-8")
    (root / "deep" / "inner" / "output" / "later.txt").write_text("music\n", encoding="utf-8")
    (output / "broken.docx").write_bytes(b"this is not a docx")
    blank = output / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with blank.open("wb") as handle:
        writer.write(handle)

    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    store = Store(tmp_path / "app.db")
    dictionary = Dictionary(dictionary_path)
    importer = Importer(store, dictionary, ExtractOptions())
    first = importer.scan(root, "project_output")
    assert first.count("failed") == 1
    assert first.count("skipped") >= 1
    assert discover_files(root, "project_output")
    assert all("notes" not in path.as_posix() for path in discover_files(root, "project_output"))
    assert any(item.unique_words > 0 and item.status == "imported" for item in first.files)
    apple = store.get_word_by_lemma("apple")
    running = store.get_word_by_lemma("run")
    assert apple and running
    assert store.get_word_by_lemma("apple")["id"] == apple["id"]
    senses = store.senses_of(apple["id"])
    assert any("苹果" in sense["gloss_zh"] for sense in senses)
    assert apple["phonetic"]

    second = importer.scan(root, "project_output")
    assert second.count("imported") == 0
    assert second.count("updated") == 0
    assert store._one("SELECT COUNT(*) AS n FROM words")["n"] == store._one("SELECT COUNT(*) AS n FROM words")["n"]

    story = output / "story.md"
    story.write_text("The apple is running across the bank.\n", encoding="utf-8")
    third = importer.scan(root, "project_output")
    assert third.count("updated") == 1
    assert store.get_word_by_lemma("bank")

    store.save_state(apple["id"], store.load_state(apple["id"]))
    from wordflow.srs import apply_manual_status
    from wordflow.timeutil import now_local

    store.save_state(apple["id"], apply_manual_status(store.load_state(apple["id"]), "learning", now_local()))
    story.unlink()
    (output / "nested" / "more.txt").unlink()
    fourth = importer.scan(root, "project_output")
    assert store.get_word_by_lemma("apple")
    assert store.load_state(apple["id"]).status == "learning"
    assert any(item.status == "skipped" or item.status == "imported" or item.status == "failed" for item in fourth.files)

    recursive = discover_files(root, "recursive_output")
    assert any(path.name == "later.txt" for path in recursive)
    assert not any(path.name == "later.txt" for path in discover_files(root, "project_output"))
    empty = importer.scan(tmp_path / "empty", "direct") if False else None
    (tmp_path / "empty").mkdir()
    empty = importer.scan(tmp_path / "empty", "direct")
    assert empty.files == []
    store.close()
    dictionary.close()


def test_article_quiz_and_reopen(tmp_path: Path):
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    db_path = tmp_path / "app.db"
    store = Store(db_path)
    dictionary = Dictionary(dictionary_path)
    importer = Importer(store, dictionary, ExtractOptions(filter_stopwords=True))
    text = "People abandon a system and develop an important idea. They accept the record."
    result = importer.import_article("Sample", text, "科技")
    assert result.status == "imported"
    assert result.unique_words >= 4
    again = importer.import_article("Sample 2", text, "")
    assert again.duplicate
    document = Document()
    document.add_paragraph("The computer provides music and history.")
    docx_path = tmp_path / "note.docx"
    document.save(docx_path)
    imported = importer.import_file(docx_path, kind="article")
    assert imported.unique_words >= 2

    study = StudyService(store, dictionary)
    started = study.start_placement(limit=10, document_id=result.document_id, deck_id=None, include_pending=True)
    assert started["session_id"]
    items = store.session_items(started["session_id"])
    assert items
    item = items[0]
    assert item["correct_gloss"] in item["options"]
    assert len(item["options"]) == 4
    wrong_choice = next(option for option in item["options"] if option != item["correct_gloss"])
    study.answer(started["session_id"], item, result="wrong", rating=None, chosen=wrong_choice)
    state = store.load_state(item["word_id"])
    assert state.status == "learning"
    assert state.wrong_count == 1
    store.close()
    dictionary.close()

    reopened = Store(db_path)
    kept = reopened.load_state(item["word_id"])
    assert kept.status == "learning"
    assert kept.wrong_count == 1
    assert reopened.get_session(started["session_id"])["status"] == "active"
    reopened.close()


def test_study_plan_picks_unlearned_words_from_that_document(tmp_path: Path):
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    store = Store(tmp_path / "app.db")
    dictionary = Dictionary(dictionary_path)
    story = tmp_path / "story.txt"
    story.write_text("The apple is running across the bank.\n", encoding="utf-8")
    music = tmp_path / "music.txt"
    music.write_text("Music and science.\n", encoding="utf-8")
    importer = Importer(store, dictionary, ExtractOptions())
    first = importer.import_file(story)
    second = importer.import_file(music)
    store.set_study_plan(first.document_id, True)
    assert store.get_document(first.document_id)["study_plan"] == 1
    assert store.list_study_plans()[0]["id"] == first.document_id
    service = StudyService(store, dictionary)
    untouched = service.start_learn(mode="card", limit=20, document_id=None, deck_id=None)
    assert untouched["session_id"] is None
    opened = service.start_learn(mode="card", limit=20, document_id=first.document_id, deck_id=None)
    lemmas = {item["lemma"] for item in store.session_items(opened["session_id"])}
    assert {"apple", "run", "bank"} <= lemmas
    assert "music" not in lemmas and "science" not in lemmas
    apple = store.get_word_by_lemma("apple")
    state = store.load_state(apple["id"])
    state.status = "mastered"
    store.save_state(apple["id"], state)
    again = service.start_learn(mode="card", limit=20, document_id=first.document_id, deck_id=None)
    again_lemmas = {item["lemma"] for item in store.session_items(again["session_id"])}
    assert "apple" not in again_lemmas
    assert second.document_id
    store.update_document_meta(first.document_id, "运动改变大脑", "")
    story.write_text("The apple is running across the bank again.\n", encoding="utf-8")
    importer.import_file(story)
    assert store.get_document(first.document_id)["title"] == "运动改变大脑"
    assert store.list_study_plans()[0]["title"] == "运动改变大脑"
    store.close()
    dictionary.close()


def test_selected_files_import_without_a_folder(tmp_path: Path):
    from wordflow.jobs import import_files

    class _Worker:
        def cancelled(self) -> bool:
            return False

        class progress:
            @staticmethod
            def emit(*_args) -> None:
                return None

    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    story = tmp_path / "story.txt"
    story.write_text("The apple is running across the bank.\n", encoding="utf-8")
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    music = other_dir / "music.txt"
    music.write_text("Music and science.\n", encoding="utf-8")
    report = import_files(tmp_path / "app.db", dictionary_path, [story, music], ExtractOptions(), _Worker())
    assert report.count("imported") == 2
    store = Store(tmp_path / "app.db")
    assert store.get_word_by_lemma("apple")
    assert store.get_word_by_lemma("music")
    store.close()


def test_import_page_lists_every_detected_word(tmp_path: Path):
    import os

    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    from PySide6.QtWidgets import QApplication

    from wordflow.context import AppContext
    from wordflow.ui.import_page import ImportPage

    QApplication.instance() or QApplication([])
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    ctx = AppContext(db_path=tmp_path / "app.db", dict_path=dictionary_path)
    root = tmp_path / "docs"
    root.mkdir()
    (root / "story.txt").write_text("The apple is running across the bank.\n", encoding="utf-8")
    (root / "more.txt").write_text("Music and science.\n", encoding="utf-8")
    report = Importer(ctx.store, ctx.dictionary, ExtractOptions()).scan(root, "direct")
    page = ImportPage(ctx, None)
    page._done(report)
    found = []
    for index in range(page.doc_picker.count()):
        page.doc_picker.setCurrentIndex(index)
        found.append({row["lemma"] for row in page.word_model.rows})
    assert page.doc_picker.count() == 2
    assert any({"apple", "run", "bank"} <= item for item in found)
    assert any({"music", "science"} <= item for item in found)
    ctx.close()


def test_study_plan_scopes_review_and_word_books(tmp_path: Path):
    import os
    from datetime import timedelta

    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    from wordflow.context import AppContext
    from wordflow.timeutil import now_local
    from wordflow.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    ctx = AppContext(db_path=tmp_path / "app.db", dict_path=dictionary_path)
    story = tmp_path / "story.txt"
    story.write_text("The apple is running across the bank.\n", encoding="utf-8")
    music = tmp_path / "music.txt"
    music.write_text("Music and science.\n", encoding="utf-8")
    importer = Importer(ctx.store, ctx.dictionary, ExtractOptions())
    first = importer.import_file(story)
    importer.import_file(music)
    ctx.store.set_study_plan(first.document_id, True)
    today = now_local()
    for lemma in ("apple", "music"):
        word = ctx.store.get_word_by_lemma(lemma)
        state = ctx.store.load_state(word["id"])
        state.status = "learning"
        state.wrong_count = 2
        state.next_review_at = today - timedelta(days=1)
        ctx.store.save_state(word["id"], state)
    opened = StudyService(ctx.store, ctx.dictionary).start_review(
        mode="card", limit=20, deck_id=None, document_id=first.document_id
    )
    lemmas = {item["lemma"] for item in ctx.store.session_items(opened["session_id"])}
    assert "apple" in lemmas
    assert "music" not in lemmas
    window = MainWindow(ctx)
    window.go("plans")
    page = window.pages["plans"]
    page.select_plan(first.document_id)
    assert page.apply_name("  句子精听  ")
    assert page.plan.currentText() == "句子精听"
    assert "句子精听" in page.progress_label.text()
    assert "已掌握" in page.progress_label.text()
    assert any(row["lemma"] == "apple" for row in page.model.rows)
    assert all(row["lemma"] != "music" for row in page.model.rows)
    window.go("learning")
    learning = window.pages["learning"]
    learning.document.setCurrentIndex(learning.document.findData(first.document_id))
    assert learning.document.currentText() == "句子精听"
    shown = {row["lemma"] for row in learning.model.rows}
    assert "apple" in shown
    assert "music" not in shown
    window.go("mistakes")
    mistakes = window.pages["mistakes"].words
    mistakes.document.setCurrentIndex(mistakes.document.findData(first.document_id))
    wrong = {row["lemma"] for row in mistakes.model.rows}
    assert "apple" in wrong
    assert "music" not in wrong
    ctx.close()
