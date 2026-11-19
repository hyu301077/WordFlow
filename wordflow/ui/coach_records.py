"""首页的手机助教课后记录。"""

from __future__ import annotations

from itertools import groupby
from operator import itemgetter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QInputDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from wordflow.coach_page import parse_page_id, read_records, send_passage
from wordflow.page_transport import PageTransport
from wordflow.ui.common import section_title, tell
from wordflow.ui.workers import CallWorker


class CoachRecordsWidget(QFrame):
    passage_finished = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.sync_worker = None
        self.sync_page_id = ""
        self.send_worker = None
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(section_title("手机助教学习记录"), 1)
        self.connect_button = QPushButton("连接 Page")
        self.connect_button.clicked.connect(self.connect_page)
        header.addWidget(self.connect_button)
        self.sync_button = QPushButton("同步记录")
        self.sync_button.clicked.connect(self.sync)
        header.addWidget(self.sync_button)
        layout.addLayout(header)

        self.records = QPlainTextEdit()
        self.records.setReadOnly(True)
        self.records.setAccessibleName("已保存的手机助教学习记录")
        self.records.setPlaceholderText("暂无课后记录")
        self.records.setMaximumHeight(168)
        layout.addWidget(self.records)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

    def page_id(self) -> str:
        return self.ctx.settings.get("coach_page_id")

    def ask_page_id(self) -> str:
        page_id = self.page_id()
        url, ok = QInputDialog.getText(
            self, "连接手机助教", "粘贴手机助教使用的 ChatGPT Page 链接",
            text=f"https://chatgpt.com/space/{page_id}" if page_id else "",
        )
        if not ok:
            return ""
        try:
            return parse_page_id(url)
        except ValueError as exc:
            tell(self, str(exc), "warn")
            return ""

    def connect_page(self) -> None:
        page_id = self.ask_page_id()
        if page_id:
            self.start_sync(page_id)

    def sync(self) -> None:
        if self.page_id():
            self.start_sync(self.page_id())

    def start_sync(self, page_id: str) -> None:
        if self.sync_worker:
            return

        def fetch(worker):
            with PageTransport(cancelled=worker.cancelled) as transport:
                return page_id, read_records(transport, page_id)

        self.set_status("正在读取手机助教的 Page…", busy=True)
        worker = CallWorker(fetch, self)
        self.sync_worker = worker
        self.sync_page_id = page_id
        worker.succeeded.connect(self._received)
        worker.failed.connect(self._sync_error)
        worker.finished.connect(self._sync_finished)
        worker.start()

    def _received(self, result) -> None:
        page_id, records = result
        try:
            self.ctx.store.save_coach_records(page_id, records)
            if page_id != self.page_id():
                self.ctx.settings.set("coach_page_id", page_id)
            self.refresh(page_id)
        except Exception as exc:
            self.set_status(f"无法保存到本机：{exc}")
            return
        self.set_status(f"已同步 {len(records)} 条课后记录。")

    def _sync_error(self, error: str) -> None:
        self.set_status(f"同步失败：{error}")

    def _sync_finished(self) -> None:
        self.sync_worker.deleteLater()
        self.sync_worker = None
        self.sync_page_id = ""
        self._update_buttons()

    def send(self, document_id: int, title: str, text: str) -> bool:
        if self.send_worker or (self.sync_worker and self.sync_page_id != self.page_id()):
            tell(self, "请等当前连接完成后再发送。")
            return False
        page_id = self.page_id()
        if not page_id:
            tell(self, "请先在首页的「手机助教学习记录」中连接 Page，然后发送所选段落。")
            return False

        def publish(worker):
            with PageTransport(cancelled=worker.cancelled) as transport:
                send_passage(transport, page_id, document_id, title, text)

        worker = CallWorker(publish, self)
        self.send_worker = worker
        worker.succeeded.connect(self._sent)
        worker.failed.connect(self._send_error)
        worker.finished.connect(self._send_finished)
        self._update_buttons()
        worker.start()
        return True

    def _sent(self, _result) -> None:
        self.passage_finished.emit("段落已保存到 Page。打开手机助教，请它读这张 Page 的最新待练材料。")

    def _send_error(self, error: str) -> None:
        self.passage_finished.emit(f"发送未确认：{error}")

    def _send_finished(self) -> None:
        self.send_worker.deleteLater()
        self.send_worker = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.connect_button.setText("更换 Page" if self.page_id() else "连接 Page")
        self.connect_button.setEnabled(not self.send_worker and not self.sync_worker)
        self.sync_button.setEnabled(bool(self.page_id()) and not self.sync_worker)

    def shutdown(self) -> None:
        for worker in (self.sync_worker, self.send_worker):
            if worker:
                worker.cancel()
                worker.wait()

    def refresh(self, page_id: str) -> None:
        self._update_buttons()
        records = self.ctx.store.list_coach_records(page_id)
        days = []
        for day, entries in groupby(records, key=itemgetter("day")):
            paragraphs = "\n".join(entry["content"] for entry in entries)
            days.append(f"{day}\n{paragraphs}")
        text = "\n\n".join(days)
        if text != self.records.toPlainText():
            self.records.setPlainText(text)

    def set_status(self, text: str, *, busy: bool = False) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
        if busy:
            self.sync_button.setEnabled(False)
            self.connect_button.setEnabled(False)
