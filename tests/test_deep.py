"""OCR、FSRS 持久化和在线助手的集成检查。"""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from wordflow.ai import AIClient, AIError, client_from_settings, explain_prompt
from wordflow.db import SCHEMA_V1
from wordflow.dictionary import Dictionary
from wordflow.extract import ExtractOptions
from wordflow.importer import Importer
from wordflow.parsers import parse_path
from wordflow.quiz import QuizBuilder
from wordflow.settings import Settings
from wordflow.srs import MemoryState, apply_rating
from wordflow.store import Store
from wordflow.study import StudyService
from tests.support import write_dictionary

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=timezone(timedelta(hours=8)))


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.bodies.append(body)
        self.server.authorizations.append(self.headers.get("Authorization"))
        payload = json.dumps({"choices": [{"message": {"content": "句中表示放弃原来的计划。"}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        return


def _scanned_pdf(path: Path) -> None:
    image = Image.new("RGB", (1600, 320), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 72)
    draw.text((40, 80), "The apple is running toward the bank beside the river.", fill="black", font=font)
    image.save(path, "PDF", resolution=144)


def test_scanned_pdf_is_ocr_and_imported(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"
    _scanned_pdf(pdf)
    parsed = parse_path(pdf)
    assert not parsed.error
    assert not parsed.scanned_pdf
    assert "apple" in parsed.text.lower()
    assert "bank" in parsed.text.lower()

    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    store = Store(tmp_path / "app.db")
    dictionary = Dictionary(dictionary_path)
    result = Importer(store, dictionary, ExtractOptions()).import_file(pdf, kind="article")
    assert result.status == "imported"
    assert store.get_word_by_lemma("apple")
    assert store.get_word_by_lemma("run")
    assert store.get_word_by_lemma("bank")
    store.close()
    dictionary.close()


def test_fsrs_schedule_survives_restart(tmp_path: Path):
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    database = tmp_path / "app.db"
    store = Store(database)
    dictionary = Dictionary(dictionary_path)
    word_id = store.ensure_word("apple", "apple", dictionary.lookup("apple"))
    state = apply_rating(store.load_state(word_id), "good", NOW)
    state = apply_rating(state, "good", state.next_review_at)
    store.save_state(word_id, state)
    store.close()
    dictionary.close()

    reopened = Store(database)
    restored = reopened.load_state(word_id)
    assert restored.fsrs_state == "review"
    assert restored.stability == pytest.approx(state.stability)
    assert restored.next_review_at == state.next_review_at
    failed = apply_rating(restored, "again", restored.next_review_at)
    assert failed.status == "learning"
    assert failed.lapses == 1
    assert failed.interval_days < restored.interval_days
    reopened.save_state(word_id, failed)
    logs_before = reopened._one("SELECT COUNT(*) AS n FROM review_logs")["n"]
    reopened.close()
    checked = Store(database)
    assert checked.load_state(word_id).lapses == 1
    assert checked._one("SELECT COUNT(*) AS n FROM review_logs")["n"] == logs_before
    checked.close()


def test_old_database_gains_fsrs_fields(tmp_path: Path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V1)
    connection.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-01-01T00:00:00+08:00')")
    connection.execute(
        """
        INSERT INTO words(lemma, display, phonetic_source, created_at, updated_at)
        VALUES ('apple', 'apple', 'missing', '2026-01-01T00:00:00+08:00', '2026-01-01T00:00:00+08:00')
        """
    )
    connection.execute(
        """
        INSERT INTO learning_states(word_id, status, ease, interval_days, repetitions, updated_at)
        VALUES (1, 'reviewing', 2.5, 4, 2, '2026-01-01T00:00:00+08:00')
        """
    )
    connection.commit()
    connection.close()

    store = Store(path)
    state = store.load_state(1)
    assert state.fsrs_state == "review"
    assert state.stability == pytest.approx(4)
    assert state.difficulty == pytest.approx(5)
    columns = {row[1] for row in store.conn.execute("PRAGMA table_info(ai_records)")}
    assert "content" in columns
    store.close()


def test_online_assistant_reads_mixed_text_parts(monkeypatch):
    body = {"choices": [{"message": {"content": ["第一段", {"text": "第二段"}, {"type": "image"}, None]}}]}
    response = BytesIO(json.dumps(body).encode("utf-8"))
    monkeypatch.setattr("wordflow.ai.urllib.request.urlopen", lambda *_args, **_kwargs: response)
    assert AIClient("http://localhost/v1", "", "test").complete("system", "user") == "第一段\n第二段"


def test_online_assistant_is_opt_in_and_does_not_change_quiz(tmp_path: Path):
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    store = Store(tmp_path / "app.db")
    dictionary = Dictionary(dictionary_path)
    settings = Settings(store)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.bodies = []
    server.authorizations = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(AIError):
            client_from_settings(settings)
        assert server.bodies == []

        word_id = store.ensure_word("abandon", "abandon", dictionary.lookup("abandon"))
        senses_before = [dict(row) for row in store.senses_of(word_id)]
        settings.set("ai_enabled", 1)
        settings.set("ai_consent", 1)
        settings.set("ai_base_url", f"http://127.0.0.1:{server.server_address[1]}/v1")
        settings.set("ai_model", "test-model")
        settings.set("ai_api_key", "secret-key-value")
        system, user = explain_prompt("abandon", "He had to abandon his original plan.", senses_before[0]["gloss_zh"])
        text = client_from_settings(settings).complete(system, user)
        assert "放弃" in text
        body = server.bodies[0].decode("utf-8")
        assert "abandon his original plan" in body
        assert "TOP SECRET DOCUMENT" not in body
        assert "secret-key-value" not in body
        assert server.authorizations[0] == "Bearer secret-key-value"
        store.add_ai_record(kind="explain", title="abandon", preview=user, content=text, model="test-model", word_id=word_id)
        assert [dict(row) for row in store.senses_of(word_id)] == senses_before
        question = QuizBuilder(dictionary).build(word_id=word_id, senses=store.senses_of(word_id), example=None)
        assert question is not None
        assert question.options.count(question.correct) == 1
        assert "句中表示" not in question.correct
    finally:
        server.shutdown()
        store.close()
        dictionary.close()


def test_scan_placement_and_review_survive_a_restart(tmp_path: Path):
    root = tmp_path / "materials"
    root.mkdir()
    _scanned_pdf(root / "scan.pdf")
    (root / "notes.txt").write_text("Develop a useful system.\n", encoding="utf-8")
    (root / "broken.docx").write_bytes(b"this is not a docx")
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    database = tmp_path / "app.db"
    store = Store(database)
    dictionary = Dictionary(dictionary_path)
    report = Importer(store, dictionary, ExtractOptions()).scan(root, "direct")
    assert report.count("imported") == 2
    assert report.count("failed") == 1
    service = StudyService(store, dictionary)
    opened = service.start_placement(limit=3, document_id=None, deck_id=None, include_pending=True)
    assert opened["queued"] >= 2
    items = store.session_items(opened["session_id"])
    wrong = service.answer(opened["session_id"], items[0], result="wrong", rating=None, chosen="不相干的释义")
    correct = service.answer(opened["session_id"], items[1], result="correct", rating=None, chosen=items[1]["correct_gloss"])
    assert wrong["state_after"].status == "learning"
    assert correct["state_after"].status == "reviewing"
    assert correct["state_after"].status != "mastered"
    assert items[1]["options"].count(items[1]["correct_gloss"]) == 1
    wrong_id = items[0]["word_id"]
    learned = service.start_learn(mode="card", limit=1, document_id=None, deck_id=None, word_ids=[wrong_id])
    learned_items = store.session_items(learned["session_id"])
    rated = service.answer(learned["session_id"], learned_items[0], result="correct", rating="good", chosen=None)
    assert rated["state_after"].fsrs_state == "learning"
    assert rated["state_after"].next_review_at is not None
    store.close()
    dictionary.close()

    reopened = Store(database)
    restored = reopened.load_state(wrong_id)
    assert restored.status == "learning"
    assert restored.stability > 0
    assert restored.wrong_count == 1
    assert reopened._one("SELECT COUNT(*) AS n FROM review_logs WHERE word_id = ?", (wrong_id,))["n"] == 2
    reopened.close()


def test_mastered_rating_is_at_least_21_days():
    state = apply_rating(MemoryState(), "mastered", NOW)
    assert state.status == "mastered"
    assert state.fsrs_state == "review"
    assert state.interval_days >= 21
