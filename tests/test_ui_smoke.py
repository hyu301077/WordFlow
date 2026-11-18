import pytest

from wordflow.backup import backup_database
from wordflow.context import AppContext
from wordflow.extract import ExtractOptions
from wordflow.importer import Importer
from wordflow.study import StudyService
from wordflow.ui.main_window import MainWindow
from wordflow.ui.theme import build_qss
from tests.support import write_dictionary


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("WORDFLOW_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    original_theme = application.styleSheet()
    application.setStyleSheet(build_qss("light"))
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    ctx = AppContext(db_path=tmp_path / "wordflow.db", dict_path=dictionary)
    window = MainWindow(ctx)
    window.show()
    yield application, window, ctx
    window.close()
    ctx.close()
    application.setStyleSheet(original_theme)


def test_window_pages_open(desktop):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QBoxLayout, QPushButton, QScrollArea

    application, window, ctx = desktop
    for key in (
        "home",
        "import",
        "articles",
        "plans",
        "listen",
        "placement",
        "learn",
        "review",
        "learning",
        "mastered",
        "mistakes",
        "stats",
        "assistant",
        "settings",
    ):
        window.go(key)
        application.processEvents()
    window.resize(980, 600)
    application.processEvents()
    assert window.width() == 980
    assert window.height() == 600
    window.go("home")
    dashboard = window.pages["home"]
    assert dashboard.actions[0].text() == "导入文档"
    assert dashboard.charts.direction() == QBoxLayout.TopToBottom
    window.resize(1460, 960)
    application.processEvents()
    assert window.width() == 1460
    assert window.height() == 960
    assert dashboard.charts.direction() == QBoxLayout.LeftToRight
    imported = Importer(ctx.store, ctx.dictionary, ExtractOptions()).import_article("练习计划", "An apple grows here.")
    ctx.store.set_study_plan(imported.document_id, True)
    window.go("home")
    dashboard.plan.setCurrentIndex(dashboard.plan.findData(imported.document_id))
    assert dashboard.actions[0].text() == "摸底测试"
    dashboard.findChild(QPushButton, "heroPrimary").click()
    assert window.pages["placement"].document.currentData() == imported.document_id
    window.go("home")
    dashboard.plan.setCurrentIndex(0)
    dashboard.findChild(QPushButton, "heroPrimary").click()
    assert window.pages["placement"].document.currentData() is None

    window.resize(800, 480)
    application.processEvents()
    sidebar = window.findChild(QScrollArea, "sidebarScroll")
    assert sidebar.verticalScrollBar().maximum() > 0
    assert sidebar.geometry().bottom() < window.dict_state.geometry().top()
    sidebar.ensureWidgetVisible(window.nav_buttons["settings"])
    window.nav_buttons["settings"].setFocus(Qt.TabFocusReason)
    assert window.nav_buttons["settings"].hasFocus()
    for key in ("home", "review", "listen", "assistant", "stats"):
        window.go(key)
        application.processEvents()
        assert window.hosts[key].horizontalScrollBar().maximum() == 0
    assert window.pages["stats"].details.direction() == QBoxLayout.TopToBottom
    window.go("settings")
    application.processEvents()
    host = window.stack_widget.currentWidget()
    assert host.widget() is window.pages["settings"]
    assert host.viewport().width() > 400
    assert host.horizontalScrollBar().maximum() == 0
    assert host.verticalScrollBar().maximum() > 0
    window.apply_theme("dark")
    assert ctx.settings.get("theme") == "dark"
    window.go("home")
    application.processEvents()
    assert window.pages["home"].chart.height() >= 160
    window.close()
    restored = MainWindow(ctx)
    assert restored.size() == window.size()
    restored.close()


def test_stats_switches_between_scored_and_empty_plans(desktop):
    _, window, ctx = desktop
    importer = Importer(ctx.store, ctx.dictionary, ExtractOptions())
    imported = importer.import_article("苹果", "An apple grows here.")
    ctx.store.set_study_plan(imported.document_id)
    word = ctx.store.get_word_by_lemma("apple")
    sid = ctx.store.create_session("placement", "quiz", None, None, [{"word_id": word["id"]}])
    study = StudyService(ctx.store, ctx.dictionary)
    study.answer(sid, ctx.store.session_items(sid)[0], result="wrong", rating=None, chosen="wrong")
    other = importer.import_article("另一份计划", "They abandon the plan.")
    ctx.store.set_study_plan(other.document_id)
    window.go("stats")
    stats = window.pages["stats"]
    stats.plan.setCurrentIndex(stats.plan.findData(imported.document_id))
    assert len(stats.activity.values) == 30 and sum(stats.activity.values) == 1
    assert stats.accuracy.values == [0]
    assert stats.metrics[1][0].text() == "0.0%"
    stats.plan.setCurrentIndex(stats.plan.findData(other.document_id))
    assert sum(stats.activity.values) == 0
    assert stats.accuracy.values == []
    assert stats.metrics[1][0].text() == "—"
    stats.plan.setCurrentIndex(0)
    assert sum(stats.activity.values) == 1


def test_restore_resets_only_after_success_and_reloads_practice(desktop, tmp_path, monkeypatch):
    from wordflow.ui import settings_page

    _, window, ctx = desktop
    ctx.settings.set("auto_speak", "0")
    word_id = ctx.store.ensure_word("apple", "apple", ctx.dictionary.lookup("apple"))
    sid = ctx.store.create_session("placement", "quiz", None, None, [{"word_id": word_id}])
    study = StudyService(ctx.store, ctx.dictionary)
    study.answer(sid, ctx.store.session_items(sid)[0], result="wrong", rating=None, chosen="wrong")
    page = window.pages["placement"]
    page._finished(study.report(sid))
    page._undo_last()
    assert page.stack.currentWidget() is page.session_host
    assert page.study_widget.current["word_id"] == word_id
    backup = backup_database(ctx.store, tmp_path / "restore.db")
    ctx.settings.set("daily_new_limit", "42")
    settings = window.pages["settings"]
    monkeypatch.setattr(settings_page, "confirm", lambda *args: True)
    monkeypatch.setattr(settings_page, "tell", lambda *args: None)
    monkeypatch.setattr(settings_page.QFileDialog, "getOpenFileName", lambda *args: (str(ctx.db_path), ""))
    settings._restore()
    assert page.study_widget.service.store.get_session(sid)["status"] == "active"
    monkeypatch.setattr(settings_page.QFileDialog, "getOpenFileName", lambda *args: (str(backup), ""))
    settings._restore()
    assert ctx.settings.integer("daily_new_limit", 20) == 20
    assert page.study_widget is None
    assert page.stack.currentWidget() is page.setup
    assert page._active_id == sid
