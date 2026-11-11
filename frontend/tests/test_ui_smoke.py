import os

from wordflow.context import AppContext
from wordflow.ui.main_window import MainWindow
from tests.support import write_dictionary


def test_window_pages_open(tmp_path, qapp=None):
    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

    application = QApplication.instance() or QApplication([])
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    ctx = AppContext(db_path=tmp_path / "wordflow.db", dict_path=dictionary)
    window = MainWindow(ctx)
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
    window.resize(1460, 960)
    application.processEvents()
    assert window.width() == 1460
    assert window.height() == 960
    window.go("settings")
    application.processEvents()
    host = window.stack_widget.currentWidget()
    assert host.widget() is window.pages["settings"]
    assert host.viewport().width() > 400
    window.go("home")
    application.processEvents()
    chart = window.pages["home"].chart
    assert chart.height() >= 160
    from PySide6.QtCore import QRect

    wide, tall = window._landscape_size(QRect(0, 0, 2560, 1392))
    assert wide == 1680 and tall == 1050
    small_w, small_h = window._landscape_size(QRect(-1920, 0, 1536, 816))
    assert small_w > small_h * 1.4
    assert small_h <= 816 - 16
    kept_w, kept_h = window._clamp_size(1400, 820, QRect(0, 0, 2560, 1440))
    assert (kept_w, kept_h) == (1400, 820)
    assert window._clamp_position(120, 60, kept_w, kept_h, QRect(0, 0, 2560, 1440)) == (120, 60)
    window.ctx.settings.set("window_custom", "1")
    window.ctx.settings.set("window_width", 900)
    window.ctx.settings.set("window_height", 520)
    window.ctx.settings.set("window_x", 20)
    window.ctx.settings.set("window_y", 20)
    window.show()
    application.processEvents()
    assert window.width() >= window.minimumWidth()
    assert window.height() >= window.minimumHeight()
    assert window.width() > window.height()
    rects = []
    for button in window.nav_buttons.values():
        origin = button.mapTo(window, button.rect().topLeft())
        rects.append(button.rect().translated(origin))
        assert button.height() >= button.fontMetrics().height()
    for earlier, later in zip(rects, rects[1:]):
        overlap = earlier.intersected(later)
        assert overlap.height() <= 1
    chip = window.dict_state.rect().translated(window.dict_state.mapTo(window, window.dict_state.rect().topLeft()))
    scroll = window.findChild(QScrollArea, "sidebarScroll")
    visible = scroll.viewport().rect()
    visible = visible.translated(scroll.viewport().mapTo(window, visible.topLeft()))
    scroll_rect = scroll.rect().translated(scroll.mapTo(window, scroll.rect().topLeft()))
    assert scroll_rect.intersected(chip).height() <= 1
    for rect in rects:
        shown = rect.intersected(visible)
        assert chip.intersected(shown).height() <= 1
    for caption in window.findChildren(QLabel, "navSection"):
        caption_rect = caption.rect().translated(caption.mapTo(window, caption.rect().topLeft()))
        for rect in rects:
            assert caption_rect.intersected(rect).height() <= 1
    window.close()
    ctx.close()
