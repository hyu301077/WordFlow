"""直接选择文档并导入。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from wordflow.jobs import import_files
from wordflow.ui.common import format_phonetic, page_header, status_text, tell
from wordflow.ui.dialogs import WordDialog
from wordflow.ui.workers import CallWorker

class DetectedWordModel(QAbstractTableModel):
    HEADERS = ["单词", "音标", "释义", "词频", "状态"]

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=None) -> int:
        return len(self.rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self.rows[index.row()]
        values = [
            row["lemma"],
            format_phonetic(row.get("phonetic")),
            row.get("gloss") or "待补充",
            str(row.get("frequency") or 0),
            status_text(row.get("status")),
        ]
        return values[index.column()]


class ImportPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.worker: CallWorker | None = None
        self.files: list[Path] = []
        layout = QVBoxLayout(self)
        layout.addWidget(
            page_header(
                "导入文档",
                "直接选择 txt、md、docx 或 PDF，可以一次选多份。"
                "扫描版 PDF 会在本机用 Windows OCR 识别，不会上传。",
            )
        )
        row = QHBoxLayout()
        self.path_label = QLabel("还没有选择文件")
        self.path_label.setWordWrap(True)
        browse = QPushButton("选择文件")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row.addWidget(self.path_label, 1)
        layout.addLayout(row)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("扫描版最多识别"))
        self.ocr_pages = QSpinBox()
        self.ocr_pages.setRange(1, 200)
        self.ocr_pages.setSuffix(" 页")
        self.ocr_pages.valueChanged.connect(lambda value: self.ctx.settings.set("ocr_max_pages", value))
        mode_row.addWidget(self.ocr_pages)
        layout.addLayout(mode_row)
        actions = QHBoxLayout()
        self.start_button = QPushButton("开始导入")
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
        self.status = QLabel("只处理选中的文件。某一个文件打不开时，其余文件继续导入。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(72)
        layout.addWidget(self.log, 1)
        words = QFrame()
        words.setObjectName("card")
        word_layout = QVBoxLayout(words)
        head = QHBoxLayout()
        title = QLabel("检出的单词")
        self.doc_picker = QComboBox()
        self.doc_picker.currentIndexChanged.connect(self._show_document_words)
        self.word_count = QLabel("导入完成后，这里列出所选文档里检测出的全部单词。")
        self.word_count.setObjectName("muted")
        self.word_count.setWordWrap(True)
        self.plan_button = QPushButton("导入学习计划")
        self.plan_button.clicked.connect(self._import_plan)
        head.addWidget(title)
        head.addWidget(self.doc_picker, 1)
        head.addWidget(self.plan_button)
        word_layout.addLayout(head)
        word_layout.addWidget(self.word_count)
        self.word_model = DetectedWordModel()
        self.word_view = QTableView()
        self.word_view.setModel(self.word_model)
        self.word_view.setSelectionBehavior(QTableView.SelectRows)
        self.word_view.setSelectionMode(QTableView.SingleSelection)
        self.word_view.verticalHeader().setVisible(False)
        self.word_view.horizontalHeader().setStretchLastSection(True)
        self.word_view.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.word_view.doubleClicked.connect(self._open_word)
        self.word_view.setMinimumHeight(160)
        word_layout.addWidget(self.word_view, 1)
        layout.addWidget(words, 2)

    def on_show(self) -> None:
        self.ocr_pages.blockSignals(True)
        self.ocr_pages.setValue(self.ctx.settings.integer("ocr_max_pages", 40))
        self.ocr_pages.blockSignals(False)

    def _browse(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "选择要导入的文档",
            "",
            "文档 (*.txt *.md *.markdown *.docx *.pdf)",
        )
        if not paths:
            return
        self.files = [Path(path) for path in paths]
        if len(self.files) == 1:
            shown = str(self.files[0])
        else:
            names = [path.name for path in self.files]
            shown = f"{len(names)} 个文件：" + "、".join(names[:8])
            if len(names) > 8:
                shown += "…"
        self.path_label.setText(shown)

    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        missing = [path for path in self.files if not path.is_file()]
        if not self.files or missing:
            tell(self, "请先选择存在的文档。", "warn")
            return
        self.log.clear()
        self._clear_words()
        self.progress.setValue(0)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        options = self.ctx.settings.extract_options()

        def job(worker):
            pages = self.ctx.settings.integer("ocr_max_pages", 40)
            return import_files(
                self.ctx.db_path,
                self.ctx.dict_path,
                self.files,
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
        self._fill_documents(report)

    def _clear_words(self) -> None:
        self.doc_picker.blockSignals(True)
        self.doc_picker.clear()
        self.doc_picker.blockSignals(False)
        self.word_model.set_rows([])
        self.word_count.setText("导入完成后，这里列出所选文档里检测出的全部单词。")

    def _fill_documents(self, report) -> None:
        order = {"imported": 0, "updated": 1, "skipped": 2, "failed": 3}
        seen: set[int] = set()
        items = []
        for item in report.files:
            if not item.document_id or item.document_id in seen:
                continue
            seen.add(item.document_id)
            items.append(item)
        items.sort(key=lambda item: (order.get(item.status, 9), item.path or ""))
        self.doc_picker.blockSignals(True)
        self.doc_picker.clear()
        for item in items:
            document = self.ctx.store.get_document(item.document_id)
            title = document["title"] if document else (item.path or "未命名文档")
            self.doc_picker.addItem(title, item.document_id)
        self.doc_picker.blockSignals(False)
        if items:
            self.doc_picker.setCurrentIndex(0)
            self._show_document_words()
        else:
            self.word_model.set_rows([])
            self.word_count.setText("这次没有导入可列出单词的文档。")

    def _show_document_words(self) -> None:
        document_id = self.doc_picker.currentData()
        if not document_id:
            self.word_model.set_rows([])
            return
        rows = self.ctx.store.document_words(int(document_id))
        self.word_model.set_rows(rows)
        document = self.ctx.store.get_document(int(document_id))
        title = document["title"] if document else "这份文档"
        planned = "已在学习计划中。" if document and int(document.get("study_plan") or 0) else "可导入学习计划。"
        self.word_count.setText(f"{title} 检出 {len(rows)} 个单词。{planned}词典没有释义的显示为待补充。")

    def _import_plan(self) -> None:
        document_id = self.doc_picker.currentData()
        if not document_id:
            tell(self, "请先导入文档，并在下方选中它。", "warn")
            return
        rows = self.ctx.store.document_words(int(document_id))
        if not rows:
            tell(self, "这份文档没有检出可学习的英文单词。", "warn")
            return
        self.ctx.store.set_study_plan(int(document_id), True)
        self._show_document_words()
        document = self.ctx.store.get_document(int(document_id))
        title = document["title"] if document else "这份文档"
        tell(self, f"已把「{title}」加入学习计划，共 {len(rows)} 个单词。打开「学习计划」可以专门把这份文件学完。")

    def _open_word(self, index) -> None:
        if not index.isValid():
            return
        row = self.word_model.rows[index.row()]
        if WordDialog(self.ctx, row["id"], self).exec():
            self._show_document_words()

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
