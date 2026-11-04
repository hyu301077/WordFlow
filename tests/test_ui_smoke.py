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
    window.close()
    ctx.close()
