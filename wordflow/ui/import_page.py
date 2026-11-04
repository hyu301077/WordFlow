"""目录扫描。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wordflow.jobs import scan_documents
from wordflow.ui.common import page_header, tell
from wordflow.ui.workers import CallWorker

_MODES = [
    ("project_output", "每个子目录下的 output（根目录/*/output）"),
    ("recursive_output", "递归查找更深的 output 文件夹"),
    ("direct", "直接扫描所选文件夹里的文档"),
]


class ImportPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.worker: CallWorker | None = None
        self.folder: Path | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            page_header(
                "导入文档",
                "默认查找「所选文件夹 / 项目 / output」里的 txt、md、docx 和 PDF。"
                "扫描版 PDF 会在本机用 Windows OCR 识别，不会上传。"
                "如果材料在更深层，比如 talks/某个主题/output，请选择 talks 文件夹，或改用递归查找。",
            )
        )
        row = QHBoxLayout()
        self.path_label = QLabel("还没有选择文件夹")
        self.path_label.setWordWrap(True)
        browse = QPushButton("选择文件夹")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row.addWidget(self.path_label, 1)
        layout.addLayout(row)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("扫描方式"))
        self.mode = QComboBox()
        for key, label in _MODES:
            self.mode.addItem(label, key)
        mode_row.addWidget(self.mode, 1)
        mode_row.addWidget(QLabel("扫描版最多识别"))
        self.ocr_pages = QSpinBox()
        self.ocr_pages.setRange(1, 200)
        self.ocr_pages.setSuffix(" 页")
        self.ocr_pages.valueChanged.connect(lambda value: self.ctx.settings.set("ocr_max_pages", value))
        mode_row.addWidget(self.ocr_pages)
        layout.addLayout(mode_row)
        actions = QHBoxLayout()
        self.start_button = QPushButton("开始扫描")
        self.start_button.setObjectName("primary")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel)
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("空文件夹会提示没有找到文档，损坏的单个文件不会中断整批扫描。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def on_show(self) -> None:
        index = self.mode.findData(self.ctx.settings.get("scan_mode", "project_output"))
        if index >= 0:
            self.mode.setCurrentIndex(index)
        self.ocr_pages.blockSignals(True)
        self.ocr_pages.setValue(self.ctx.settings.integer("ocr_max_pages", 40))
        self.ocr_pages.blockSignals(False)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择要扫描的根目录")
        if folder:
            self.folder = Path(folder)
            self.path_label.setText(str(self.folder))

    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if self.folder is None or not self.folder.exists():
            tell(self, "请先选择一个存在的文件夹。", "warn")
            return
        mode = self.mode.currentData()
        self.ctx.settings.set("scan_mode", mode)
        self.log.clear()
        self.progress.setValue(0)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        options = self.ctx.settings.extract_options()

        def job(worker):
            pages = self.ctx.settings.integer("ocr_max_pages", 40)
            return scan_documents(
                self.ctx.db_path,
                self.ctx.dict_path,
                self.folder,
                mode,
                options,
                worker,
                ocr_max_pages=pages,
            )

        self.worker = CallWorker(job, self)
        self.worker.progress.connect(self._progress)
        self.worker.succeeded.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, current: int, total: int, label: str) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(min(current, total) if total else 0)
        self.status.setText(label)

    def _done(self, report) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        names = {"imported": "导入", "updated": "更新", "skipped": "跳过", "failed": "失败"}
        lines = []
        for item in report.files:
            prefix = names.get(item.status, item.status)
            extra = f"，词条 {item.unique_words}" if item.unique_words else ""
            lines.append(f"[{prefix}] {item.path or item.message} {item.message}{extra}")
        if not report.files:
            lines.append("没有找到 txt、md、docx 或 pdf。请确认扫描方式是否匹配目录结构。")
        if report.cancelled:
            lines.append("已取消。取消前处理完的文件已经保存。")
        self.log.setPlainText("\n".join(lines))
        self.status.setText(
            f"导入 {report.count('imported')}，更新 {report.count('updated')}，"
            f"跳过 {report.count('skipped')}，失败 {report.count('failed')}。"
        )

    def _failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        tell(self, message, "error")

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status.setText("正在取消，当前文件处理完后停止。")

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
