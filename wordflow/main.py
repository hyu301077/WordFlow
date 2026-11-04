"""WordFlow 启动入口。"""

from __future__ import annotations

import logging
import sys

from wordflow.context import AppContext
from wordflow.logging_setup import setup_logging
from wordflow.paths import log_path
from wordflow.ui.common import app_icon
from wordflow.ui.main_window import MainWindow
from wordflow.ui.theme import build_qss


def main() -> int:
    setup_logging(log_path())
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("WordFlow")
    app.setOrganizationName("WordFlow")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")

    def handle_exception(exc_type, value, traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logging.getLogger("wordflow").exception("未处理的错误", exc_info=(exc_type, value, traceback))
        QMessageBox.critical(None, "WordFlow", f"出现未处理的错误：\n{value}\n\n详细信息已写入日志。")

    sys.excepthook = handle_exception
    ctx = AppContext()
    app.setStyleSheet(build_qss(ctx.settings.get("theme", "light")))
    window = MainWindow(ctx)
    window.show()
    code = app.exec()
    ctx.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
