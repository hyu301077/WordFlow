"""直接选择文档并导入。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QBuffer, QIODevice, QSaveFile, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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
from wordflow.materials import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS, has_media_source_cache, material_folder
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
        self.retry_document_id = None
        self.close_after_import = False
        layout = QVBoxLayout(self)
        layout.addWidget(
            page_header(
                "导入素材",
                "音视频和截图会自动生成学习计划。也可以导入 TXT、Markdown、Word 和 PDF。",
            )
        )
        row = QHBoxLayout()
        self.path_label = QLabel("还没有选择文件")
        self.path_label.setWordWrap(True)
        self.browse = QPushButton("选择文件")
        self.browse.clicked.connect(self._browse)
        self.paste = QPushButton("粘贴截图")
        self.paste.clicked.connect(self._paste)
        self.paste_key = QShortcut(QKeySequence.Paste, self)
        self.paste_key.setContext(Qt.WidgetWithChildrenShortcut)
        self.paste_key.activated.connect(self._paste)
        row.addWidget(self.browse)
        row.addWidget(self.paste)
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
        if not self.files:
            try:
                paths = json.loads(self.ctx.settings.get("unfinished_material_import", "[]"))
                if isinstance(paths, list):
                    self.files = [Path(raw) for raw in paths if isinstance(raw, str) and Path(raw).is_file()]
            except (ValueError, OSError):
                self.files = []
            if self.files:
                self._show_files()
                self.status.setText("上次导入尚未完成，点「开始导入」继续。")

    def _browse(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "选择要导入的素材",
            "",
            "学习素材 (*.txt *.md *.markdown *.docx *.pdf " +
            " ".join("*" + ext for ext in sorted(IMAGE_EXTENSIONS | MEDIA_EXTENSIONS)) + ")",
        )
        if not paths:
            return
        self.files = [Path(path) for path in paths]
        self.retry_document_id = None
        self._show_files()

    def _show_files(self) -> None:
        if len(self.files) == 1:
            shown = str(self.files[0])
        else:
            names = [path.name for path in self.files]
            shown = f"{len(names)} 个文件：" + "、".join(names[:8])
            if len(names) > 8:
                shown += "…"
        self.path_label.setText(shown)

    def _paste(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        image = QApplication.clipboard().image()
        if image.isNull():
            tell(self, "剪贴板里没有图片。请先复制一张截图。", "warn")
            return
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            tell(self, "截图无法转换为 PNG 图片。", "warn")
            return
        raw = bytes(buffer.data())
        name = hashlib.sha256(raw).hexdigest()
        path = self.ctx.data_dir / "screenshots" / f"截图-{name}.png"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                output = QSaveFile(str(path))
                if not output.open(QIODevice.WriteOnly) or output.write(raw) != len(raw) or not output.commit():
                    raise OSError(output.errorString())
        except OSError as exc:
            tell(self, f"无法保存剪贴板截图。{exc}", "warn")
            return
        self.retry_document_id = None
        self.files = [path]
        self._show_files()
        self._start()

    def resume_material(self, document_id: int) -> None:
        if self.worker and self.worker.isRunning():
            tell(self, "素材导入仍在进行，请等待当前任务完成。", "warn")
            return
        material = self.ctx.store.get_material(document_id)
        if not material:
            return
        source = Path(material["source_path"] or "")
        folder = material_folder(self.ctx.data_dir, material["pack_path"])
        cached = material["material_kind"] == "image" or has_media_source_cache(folder)
        if not source.is_file() and not cached:
            raw, _ = QFileDialog.getOpenFileName(self, "重新关联这份计划的原文件")
            if not raw:
                return
            source = Path(raw)
        self.retry_document_id = document_id
        self.files = [source]
        self._show_files()
        self._start()

    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not self.files:
            tell(self, "请先选择素材或粘贴截图。", "warn")
            return
        self.log.clear()
        self._clear_words()
        self.progress.setValue(0)
        self.start_button.setEnabled(False)
        self.browse.setEnabled(False)
        self.paste.setEnabled(False)
        self.cancel_button.setEnabled(True)
        options = self.ctx.settings.extract_options()
        pages = self.ctx.settings.integer("ocr_max_pages", 40)
        paths = tuple(self.files)
        retry = self.retry_document_id
        if retry is None:
            self.ctx.settings.set("unfinished_material_import", json.dumps([str(p) for p in paths]))

        def job(worker):
            return import_files(
                self.ctx.db_path,
                self.ctx.dict_path,
                paths,
                options,
                worker,
                ocr_max_pages=pages,
                data_dir=self.ctx.data_dir,
                retry_document_id=retry,
            )

        self.worker = CallWorker(job, self)
        self.worker.progress.connect(self._progress)
        self.worker.succeeded.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
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
            lines.append("没有已完成的素材。")
        if report.cancelled:
            lines.append("已取消。取消前处理完的文件已经保存。")
        self.log.setPlainText("\n".join(lines))
        self.status.setText(
            f"导入 {report.count('imported')}，更新 {report.count('updated')}，"
            f"跳过 {report.count('skipped')}，失败 {report.count('failed')}。"
        )
        self._fill_documents(report)
        if self.retry_document_id is None:
            complete = {item.path for item in report.files if item.status != "failed"}
            unfinished = [str(path) for path in self.files if str(path) not in complete and path.is_file()]
            self.ctx.settings.set("unfinished_material_import", json.dumps(unfinished))
        if not report.cancelled:
            self.progress.setValue(self.progress.maximum())

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
        self.plan_button.setText("打开学习计划" if document and document.get("study_plan") else "导入学习计划")
        self.word_count.setText(f"{title} 检出 {len(rows)} 个单词。{planned}词典没有释义的显示为待补充。")

    def _import_plan(self) -> None:
        document_id = self.doc_picker.currentData()
        if not document_id:
            tell(self, "请先导入文档，并在下方选中它。", "warn")
            return
        document = self.ctx.store.get_document(int(document_id))
        if document and document.get("study_plan"):
            self.navigator.go("plans")
            self.navigator.pages["plans"].select_plan(int(document_id))
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

    def cancel_on_close(self) -> bool:
        if self.worker and self.worker.isRunning():
            self.close_after_import = True
            self._cancel()
            return True
        return False

    def _finished(self) -> None:
        self.browse.setEnabled(True)
        self.paste.setEnabled(True)
        if self.close_after_import:
            self.close_after_import = False
            QTimer.singleShot(0, self.navigator.close)

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
