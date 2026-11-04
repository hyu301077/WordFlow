"""文章阅读。点击单词查看真实释义，并用浅色标出学习状态。"""

from __future__ import annotations

import html
import re
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from wordflow.extract import _TOKEN
from wordflow.ui.dialogs import LookupDialog

_COLORS = {
    "learning": "rgba(245, 158, 11, 0.35)",
    "reviewing": "rgba(59, 130, 246, 0.28)",
    "mastered": "rgba(16, 185, 129, 0.28)",
    "pending": "rgba(139, 92, 246, 0.28)",
}


class ReaderPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.document_id: int | None = None
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        back = QPushButton("返回文章")
        back.clicked.connect(lambda: navigator.go("articles"))
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.marks = QCheckBox("显示掌握标记")
        self.marks.toggled.connect(self._render)
        bar.addWidget(back)
        bar.addWidget(self.title, 1)
        bar.addWidget(self.marks)
        layout.addLayout(bar)
        self.notice = QLabel()
        self.notice.setObjectName("muted")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self._clicked)
        layout.addWidget(self.browser)
        legend = QLabel("琥珀色是学习中，蓝色是复习中，绿色是已掌握，紫色是待确认。标记可以关掉。")
        legend.setObjectName("muted")
        layout.addWidget(legend)

    def load(self, document_id: int) -> None:
        self.document_id = document_id
        self.marks.setChecked(self.ctx.settings.flag("show_reading_marks"))
        self._render()

    def on_show(self) -> None:
        if self.document_id:
            self._render()

    def on_theme(self) -> None:
        self._render()

    def _render(self) -> None:
        if not self.document_id:
            return
        self.ctx.settings.set("show_reading_marks", "1" if self.marks.isChecked() else "0")
        document = self.ctx.store.get_document(self.document_id)
        if not document:
            return
        self.title.setText(document["title"])
        if document["status"] == "missing":
            self.notice.setText("原文件已经不在磁盘上。下面是上次导入时保存的正文。")
        elif document.get("error_message"):
            self.notice.setText(document["error_message"])
        else:
            self.notice.setText("点击单词可以查看音标、释义，并加入生词本或熟词本。")
        statuses = self.ctx.store.document_status_map(self.document_id)
        dark = self.ctx.settings.get("theme") == "dark"
        foreground = "#E8EEF5" if dark else "#1F2937"
        background = "#1E2633" if dark else "#FFFFFF"
        body = self._html_body(document.get("content") or "", statuses)
        css = [f"body {{ color: {foreground}; background: {background}; font-size: 17px; line-height: 1.7; }}",
               "a { color: inherit; text-decoration: none; }"]
        if self.marks.isChecked():
            for status, color in _COLORS.items():
                css.append(f"a.{status} {{ background: {color}; border-radius: 4px; }}")
        self.browser.setHtml(
            f"<html><head><style>{''.join(css)}</style></head><body>{body}</body></html>"
        )

    def _html_body(self, text: str, statuses: dict[str, str]) -> str:
        parts = []
        cursor = 0
        for match in _TOKEN.finditer(text):
            parts.append(html.escape(text[cursor:match.start()]).replace("\n", "<br>"))
            token = match.group(0)
            lemma = self.ctx.dictionary.resolve_lemma(token) if self.ctx.dictionary.available else token.lower()
            status = statuses.get(lemma, "")
            class_name = f' class="{status}"' if status else ""
            href = "https://wordflow.local/" + quote(lemma)
            parts.append(f'<a{class_name} href="{href}">{html.escape(token)}</a>')
            cursor = match.end()
        parts.append(html.escape(text[cursor:]).replace("\n", "<br>"))
        return "".join(parts)

    def _clicked(self, url: QUrl) -> None:
        lemma = unquote(url.toString().split("wordflow.local/")[-1])
        lemma = re.sub(r"[^A-Za-z'-]", "", lemma).lower()
        if not lemma:
            return
        LookupDialog(self.ctx, lemma, self.document_id, self).exec()
        self._render()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.navigator.go("articles")
            return
        super().keyPressEvent(event)
