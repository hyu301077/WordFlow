"""粘贴或导入单篇文章，并查看词表。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wordflow.jobs import import_article_file, import_article_text
from wordflow.ui.common import confirm, page_header, status_text, tell
from wordflow.ui.workers import CallWorker


class ArticlesPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.worker: CallWorker | None = None
        self.current_id: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(page_header("英文文章", "可以粘贴正文，或单独导入 txt、Markdown、Word 和文本型 PDF。重复内容会提示，不会再建一份。"))
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        form = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("文章标题")
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("标签，用逗号分隔，例如 科技,工作")
        form.addWidget(self.title, 2)
        form.addWidget(self.tags, 1)
        left_layout.addLayout(form)
        self.paste = QTextEdit()
        self.paste.setPlaceholderText("在这里粘贴英文文章")
        self.paste.setMinimumHeight(96)
        self.paste.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_layout.addWidget(self.paste)
        buttons = QHBoxLayout()
        paste_button = QPushButton("导入粘贴的文章")
        paste_button.setObjectName("primary")
        file_button = QPushButton("导入文件")
        paste_button.clicked.connect(self._import_text)
        file_button.clicked.connect(self._import_file)
        buttons.addWidget(paste_button)
        buttons.addWidget(file_button)
        buttons.addStretch(1)
        left_layout.addLayout(buttons)
        self.articles = QListWidget()
        self.articles.currentRowChanged.connect(self._select)
        left_layout.addWidget(self.articles, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.summary = QLabel("选择一篇文章后，这里显示词数、掌握情况和高频词。")
        self.summary.setWordWrap(True)
        right_layout.addWidget(self.summary)
        self.words = QLabel()
        self.words.setWordWrap(True)
        self.words.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right_layout.addWidget(self.words, 1)
        actions = QHBoxLayout()
        for label, slot in (
            ("阅读", self._read),
            ("摸底这篇", self._place),
            ("学习本文生词", self._learn),
            ("导入学习计划", self._make_plan),
            ("保存标题", self._save_meta),
            ("删除", self._delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        right_layout.addLayout(actions)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self._ids: list[int] = []

    def on_show(self) -> None:
        self._reload()

    def _reload(self) -> None:
        documents = self.ctx.store.list_documents()
        self._ids = [item["id"] for item in documents]
        self.articles.blockSignals(True)
        self.articles.clear()
        for item in documents:
            kind = "文章" if item["kind"] == "article" else "扫描"
            state = "原文件已删除" if item["status"] == "missing" else item["status"]
            self.articles.addItem(f"{item['title']}    {kind}    词条 {item['unique_count']}    {state}")
        self.articles.blockSignals(False)
        if self.current_id in self._ids:
            self.articles.setCurrentRow(self._ids.index(self.current_id))
        elif self._ids:
            self.articles.setCurrentRow(0)

    def _select(self, row: int) -> None:
        if row < 0 or row >= len(self._ids):
            self.current_id = None
            return
        self.current_id = self._ids[row]
        document = self.ctx.store.get_document(self.current_id)
        coverage = self.ctx.store.coverage(self.current_id)
        unique = int(coverage["unique_count"] or 0)
        mastered = int(coverage["mastered"] or 0)
        rate = round(mastered / unique * 100) if unique else 0
        self.title.setText(document["title"])
        self.tags.setText(document["tags"] or "")
        self.summary.setText(
            f"英文词数 {document['word_count']}，收录词条 {document['unique_count']}。\n"
            f"已掌握 {mastered}，学习中 {int(coverage['learning'] or 0)}，"
            f"未测试 {int(coverage['untested'] or 0)}，待确认 {int(coverage['pending'] or 0)}。\n"
            f"文章词汇覆盖率 {rate}%。"
        )
        lines = []
        for item in self.ctx.store.top_document_words(self.current_id, 40):
            gloss = item["gloss"] or "待补充"
            lines.append(f"{item['lemma']}  ×{item['frequency']}  {status_text(item['status'])}  {gloss}")
        self.words.setText("\n".join(lines) or "这篇材料里没有提取到适合学习的英文单词。")

    def _import_text(self) -> None:
        self._run(lambda: import_article_text(
            self.ctx.db_path,
            self.ctx.dict_path,
            self.title.text(),
            self.paste.toPlainText(),
            self.tags.text(),
            self.ctx.settings.extract_options(),
        ))

    def _import_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "导入英文文件",
            "",
            "文档 (*.txt *.md *.markdown *.docx *.pdf)",
        )
        if not path:
            return
        pages = self.ctx.settings.integer("ocr_max_pages", 40)
        self._run(
            lambda: import_article_file(
                self.ctx.db_path,
                self.ctx.dict_path,
                path,
                self.ctx.settings.extract_options(),
                pages,
            )
        )

    def _run(self, fn) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.summary.setText("正在分析文章…")
        self.worker = CallWorker(lambda _worker: fn(), self)
        self.worker.succeeded.connect(self._imported)
        self.worker.failed.connect(lambda message: tell(self, message, "error"))
        self.worker.start()

    def _imported(self, result) -> None:
        if result.duplicate:
            tell(self, "这篇文章已经导入过，没有重复建档。")
        elif result.status == "failed":
            tell(self, result.message, "warn")
        else:
            self.paste.clear()
            tell(self, f"{result.message}。收录词条 {result.unique_words} 个。")
        self.current_id = result.document_id or self.current_id
        self._reload()

    def _require(self) -> int | None:
        if not self.current_id:
            tell(self, "请先选择一篇文章。", "warn")
        return self.current_id

    def _read(self) -> None:
        if self._require():
            self.navigator.open_reader(self.current_id)

    def _make_plan(self) -> None:
        if not self._require():
            return
        self.ctx.store.set_study_plan(self.current_id, True)
        self.navigator.go("plans")
        self.navigator.pages["plans"].select_plan(self.current_id)
        tell(self, "已加入学习计划。可以在这里把这篇文章学到全部掌握。")

    def _place(self) -> None:
        if not self._require():
            return
        self.navigator.go("placement")
        self.navigator.pages["placement"].focus_document(self.current_id)

    def _learn(self) -> None:
        if not self._require():
            return
        ids = [
            row["id"]
            for row in self.ctx.store.top_document_words(self.current_id, 500)
            if row["status"] in {"learning", "reviewing"}
        ]
        if not ids:
            tell(self, "这篇文章里还没有生词。可以先做摸底测试。", "warn")
            return
        self.navigator.open_learn_words(ids)

    def _save_meta(self) -> None:
        if self._require():
            self.ctx.store.update_document_meta(self.current_id, self.title.text(), self.tags.text())
            self._reload()
            tell(self, "标题和标签已保存。")

    def _delete(self) -> None:
        if not self._require():
            return
        if confirm(self, "删除这篇文章及其词条关联？已经学习过的单词会保留。"):
            self.ctx.store.delete_document(self.current_id)
            self.ctx.store.delete_untouched_orphans()
            self.current_id = None
            self._reload()

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.wait(1500)
