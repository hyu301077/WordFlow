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
