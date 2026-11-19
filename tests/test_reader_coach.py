from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wordflow.ui.reader import ReaderPage


@pytest.fixture
def reader():
    application = QApplication.instance() or QApplication([])
    ctx = Mock()
    ctx.dictionary.available = False
    ctx.settings.flag.return_value = False
    ctx.store.document_status_map.return_value = {}
    ctx.store.get_document.return_value = {
        "title": "Taking the train",
        "status": "ok",
        "content": "First line.\n\nSecond line. Last words.",
    }
    navigator = SimpleNamespace(send_coach_passage=Mock(return_value=True))
    page = ReaderPage(ctx, navigator)
    page.load(42)
    page.show()
    application.processEvents()
    yield page, navigator
    page.close()


def test_drag_passage_and_keep_selection_until_send_finishes(reader, monkeypatch):
    page, navigator = reader
    lookup = Mock()
    monkeypatch.setattr("wordflow.ui.reader.LookupDialog", lookup)
    assert not page.send_passage.isEnabled()

    browser = page.browser
    cursor = browser.textCursor()
    cursor.setPosition(6)
    start = browser.cursorRect(cursor).center()
    cursor.setPosition(browser.toPlainText().index(" Last"))
    end = browser.cursorRect(cursor).center()
    QTest.mousePress(browser.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(browser.viewport(), end)
    QTest.mouseRelease(browser.viewport(), Qt.LeftButton, pos=end)
    assert page.send_passage.isEnabled()
    lookup.assert_not_called()

    page.send_passage.click()
    navigator.send_coach_passage.assert_called_once_with(42, "Taking the train", "line.\n\nSecond line.")
    assert not page.send_passage.isEnabled()
    page.send_passage.click()
    assert navigator.send_coach_passage.call_count == 1
    page.set_coach_sending(False)
    assert page.send_passage.isEnabled()
    assert page.browser.textCursor().selection().toPlainText() == "line.\n\nSecond line."


def test_unavailable_sender_keeps_selection_and_switching_article_clears_it(reader):
    page, navigator = reader
    navigator.send_coach_passage.return_value = False
    cursor = page.browser.textCursor()
    cursor.select(QTextCursor.WordUnderCursor)
    page.browser.setTextCursor(cursor)
    page.send_passage.click()
    assert page.send_passage.isEnabled()
    assert page.browser.textCursor().selectedText() == "First"
    page.load(43)
    assert not page.send_passage.isEnabled()
