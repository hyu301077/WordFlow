import os

from wordflow.context import AppContext
from wordflow.ui.main_window import MainWindow
from tests.support import write_dictionary


def test_window_pages_open(tmp_path, qapp=None):
    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

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
    window.close()
    ctx.close()
