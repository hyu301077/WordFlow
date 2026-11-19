import sqlite3
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from wordflow.context import AppContext
from wordflow.extract import ExtractOptions
from wordflow.importer import Importer
from wordflow.page_transport import PageTransportError
from wordflow.settings import Settings
from wordflow.store import Store
from wordflow.ui.coach_records import CoachRecordsWidget
from wordflow.ui.main_window import MainWindow


def wait_for(application, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert condition()


def snapshot(page_id, paragraphs):
    return {"content": {"page_id": page_id, "blocks": [
        {"id": str(i), "kind": "markdown", "markdown": text} for i, text in enumerate(paragraphs)
    ]}}


@pytest.fixture
def transport(monkeypatch):
    fake = MagicMock()
    fake.__enter__.return_value = fake
    monkeypatch.setattr("wordflow.ui.coach_records.PageTransport", lambda **kwargs: fake)
    return fake


@pytest.fixture
def open_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("WORDFLOW_DATA", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])

    @contextmanager
    def open_window(bound_page=None):
        ctx = AppContext(db_path=tmp_path / "wordflow.db", dict_path=tmp_path / "missing-dict.db")
        if bound_page:
            ctx.settings.set("coach_page_id", bound_page)
        window = MainWindow(ctx)
        window.show()
        try:
            yield app, window, ctx
        finally:
            window.close()
            app.processEvents()
            ctx.close()

    return open_window


def test_record_cache_updates_stable_blocks_and_survives_reopen(tmp_path):
    path = tmp_path / "wordflow.db"
    store = Store(path)
    first = {"block_id": "a", "day": "2026-11-19", "content": "One ticket, please."}
    second = {"block_id": "b", "day": "2026-11-19", "content": "I missed the train."}
    store.save_coach_records("page-a", [first, second])
    changes = store.conn.total_changes
    store.save_coach_records("page-a", [first, second])
    assert store.conn.total_changes == changes
    edited = {**first, "content": "One return ticket, please."}
    store.save_coach_records("page-a", [second, edited])
    assert store.list_coach_records("page-a") == [second, edited]
    store.save_coach_records("page-b", [first])
    today = {"block_id": "c", "day": "2026-11-20", "content": "I can say it on my own."}
    with pytest.raises(sqlite3.IntegrityError):
        store.save_coach_records("page-a", [today, today])
    assert store.list_coach_records("page-a") == [second, edited]
    store.save_coach_records("page-a", [edited, today])
    store.close()

    restored = Store(path)
    assert restored.list_coach_records("page-a") == [today, edited]
    restored.save_coach_records("page-a", [])
    assert restored.list_coach_records("page-a") == []
    assert restored.list_coach_records("page-b") == [first]
    restored.close()


def test_v4_upgrade_preserves_old_data_and_sync_button_updates_record_widget(tmp_path, transport):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (4, '2026-11-18');
        CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings VALUES ('theme', 'dark');
        PRAGMA user_version = 4;
        """
    )
    conn.close()
    store = Store(path)
    assert store.get_setting("theme") == "dark"
    page_id = "page_test"
    settings = Settings(store)
    settings.set("coach_page_id", page_id)
    store.save_coach_records(page_id, [{"block_id": "1", "day": "2026-11-19", "content": "Read <this>."}])

    application = QApplication.instance() or QApplication([])
    widget = CoachRecordsWidget(SimpleNamespace(store=store, settings=settings))
    widget.refresh(page_id)
    assert widget.records.toPlainText() == "2026-11-19\nRead <this>."
    transport.call.return_value = snapshot(page_id, ["# 2026-11-19", "New lesson record."])
    widget.sync_button.click()
    assert not widget.sync_button.isEnabled()
    wait_for(application, lambda: widget.sync_worker is None)
    assert widget.records.toPlainText() == "2026-11-19\nNew lesson record."
    assert widget.sync_button.isEnabled()
    widget.close()
    application.processEvents()
    store.close()


def test_bind_private_page_and_reopen_offline_with_cached_record(open_desktop, transport, monkeypatch):
    page_id = "page_lesson"
    record = "I asked for a ticket."
    dialogs = iter([f"https://chatgpt.com/space/{page_id}", "https://chatgpt.com/space/page_private"])
    monkeypatch.setattr("wordflow.ui.coach_records.QInputDialog.getText", lambda *args, **kwargs: (next(dialogs), True))
    transport.call.return_value = snapshot(page_id, ["# 2026-11-19", record])
    with open_desktop() as (app, window, ctx):
        coach = window.pages["home"].coach
        app.processEvents()
        assert not coach.sync_button.isEnabled()
        transport.call.assert_not_called()
        coach.connect_button.click()
        wait_for(app, lambda: coach.sync_worker is None)
        assert ctx.settings.get("coach_page_id") == page_id
        assert record in coach.records.toPlainText()
        transport.call.side_effect = PageTransportError("无访问权限")
        coach.connect_button.click()
        wait_for(app, lambda: coach.sync_worker is None)
        assert "无访问权限" in coach.status.text()
        assert ctx.settings.get("coach_page_id") == page_id
    transport.call.reset_mock()
    transport.call.side_effect = PageTransportError("网络未连接")
    with open_desktop() as (app, window, _ctx):
        coach = window.pages["home"].coach
        assert record in coach.records.toPlainText()
        wait_for(app, lambda: "网络未连接" in coach.status.text() and coach.sync_worker is None)
        assert transport.call.call_args.args[1]["page_id"] == page_id
        assert record in coach.records.toPlainText() and coach.sync_button.isEnabled()


def test_startup_reads_new_lesson_and_reader_sends_selected_words(open_desktop, transport):
    page_id = "page_lesson"
    records = ["# 2026-11-19", "I can buy a ticket."]
    initial = snapshot(page_id, records)
    transport.call.return_value = initial
    with open_desktop(page_id) as (app, window, ctx):
        coach = window.pages["home"].coach
        wait_for(app, lambda: records[1] in coach.records.toPlainText() and coach.sync_worker is None)
        doc = Importer(ctx.store, ctx.dictionary, ExtractOptions()).import_article("Getting home", "Take the bus home. Walk to work.")
        window.open_reader(doc.document_id)
        reader = window.pages["reader"]
        passage = "Walk to work."
        assert reader.browser.find(passage)
        source = f"词流文章 {doc.document_id} · Getting home"
        written = snapshot(page_id, ["# 待练材料", source, f"```text\n{passage}\n```", *records])
        transport.call.reset_mock()
        transport.call.side_effect = [initial, {}, written]
        reader.send_passage.click()
        assert not reader.send_passage.isEnabled()
        wait_for(app, lambda: coach.send_worker is None)
        assert "已保存" in reader.notice.text()
        assert reader.send_passage.isEnabled()
        op, arguments = transport.call.call_args_list[1].args
        assert op == "chatgpt_space.edit_page" and arguments["page_id"] == page_id
        source_unit, body_unit = arguments["operations"][0]["block_units"][-2:]
        assert source_unit["markdown"] == source
        assert body_unit["markdown"].splitlines()[1:-1] == [passage]
        transport.call.side_effect = PageTransportError("网络未连接")
        reader.send_passage.click()
        wait_for(app, lambda: coach.send_worker is None)
        assert "网络未连接" in reader.notice.text()
        assert reader.send_passage.isEnabled() and reader.browser.textCursor().selectedText() == passage
