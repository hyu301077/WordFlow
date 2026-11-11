"""把耗时任务放进后台线程。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal


class CallWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn(self))
        except Exception as exc:
            logging.getLogger("wordflow").exception("后台任务失败")
            self.failed.emit(str(exc))
