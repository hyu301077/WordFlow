"""生词本、熟词本和错题本。"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QTabWidget,
)

from wordflow.constants import NEW_WORD_STATUSES, STATUS_MASTERED
from wordflow.paths import confusion_path
from wordflow.ui.common import confirm, format_phonetic, page_header, status_text, tell
from wordflow.ui.dialogs import BatchDialog, WordDialog
from wordflow.vocab import export_csv, move_words

_PAGE_SIZE = 100


class WordModel(QAbstractTableModel):
    HEADERS = ["单词", "音标", "释义", "状态", "掌握", "词频", "错误", "下次复习"]

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
        gloss = row.get("gloss") or "待补充"
        due = (row.get("next_review_at") or "")[:16].replace("T", " ")
        values = [
            row["lemma"],
            format_phonetic(row.get("phonetic")) if row.get("phonetic") else "暂无音标",
            gloss,
            status_text(row["status"]),
            str(row["mastery"]),
            str(row["freq"]),
            str(row["wrong_count"]),
            due,
        ]
        return values[index.column()]


class WordListPage(QWidget):
    def __init__(self, ctx, navigator, kind: str):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.kind = kind
        self.page = 0
        self.total = 0
        titles = {
            "learning": ("生词本", "正在学习和等待复习的词。熟词不会同时出现在这里。"),
            "mastered": ("熟词本", "已经掌握的词。抽查答错后会回到生词复习。"),
            "mistakes": ("错题本", "记录答错次数。可以只复习这些词。"),
        }
        layout = QVBoxLayout(self)
        layout.addWidget(page_header(*titles[kind]))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索单词或中文释义")
        self.sort = QComboBox()
        for key, label in (
            ("alpha", "按字母"),
            ("freq", "按词频"),
            ("wrong", "按错误次数"),
            ("mastery", "按掌握程度"),
            ("time", "按更新时间"),
            ("due", "按复习时间"),
        ):
            self.sort.addItem(label, key)
        self.document = QComboBox()
        self.deck = QComboBox()
        filters.addWidget(self.search, 2)
        filters.addWidget(self.sort)
        filters.addWidget(self.document)
        filters.addWidget(self.deck)
        layout.addLayout(filters)
        self.view = QTableView()
        self.model = WordModel()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setSelectionMode(QTableView.ExtendedSelection)
        self.view.doubleClicked.connect(lambda _index: self._edit())
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.verticalHeader().setVisible(False)
        layout.addWidget(self.view)
        actions = QHBoxLayout()
        add = QPushButton("添加")
        batch = QPushButton("批量添加")
        edit = QPushButton("编辑")
        to_learn = QPushButton("移入生词本")
        to_known = QPushButton("移入熟词本")
        delete = QPushButton("删除")
        export = QPushButton("导出 CSV")
        review = QPushButton("复习这些错题")
        add.clicked.connect(self._add)
        batch.clicked.connect(self._batch)
        edit.clicked.connect(self._edit)
        to_learn.clicked.connect(lambda: self._move("learning"))
        to_known.clicked.connect(lambda: self._move("mastered"))
        delete.clicked.connect(self._delete)
        export.clicked.connect(self._export)
        review.clicked.connect(self._review)
        for button in (add, batch, edit, to_learn, to_known, delete, export):
            actions.addWidget(button)
        if kind == "mistakes":
            actions.addWidget(review)
        actions.addStretch(1)
        layout.addLayout(actions)
        pager = QHBoxLayout()
        self.prev = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.page_label = QLabel()
        self.prev.clicked.connect(self._prev)
        self.next.clicked.connect(self._next)
        pager.addWidget(self.prev)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next)
        pager.addStretch(1)
        layout.addLayout(pager)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda _text: self.timer.start(250))
        self.sort.currentIndexChanged.connect(lambda _index: self.reload())
        self.document.currentIndexChanged.connect(lambda _index: self.reload())
        self.deck.currentIndexChanged.connect(lambda _index: self.reload())

    def on_show(self) -> None:
        self._fill_filters()
        self.reload()

    def _fill_filters(self) -> None:
        doc = self.document.currentData()
        deck = self.deck.currentData()
        self.document.blockSignals(True)
        self.deck.blockSignals(True)
        self.document.clear()
        self.deck.clear()
        self.document.addItem("全部文章", None)
        for document in self.ctx.store.list_documents():
            self.document.addItem(document["title"], document["id"])
        self.deck.addItem("全部词库", None)
        for item in self.ctx.store.list_decks():
            self.deck.addItem(item["name"], item["id"])
        for combo, value in ((self.document, doc), (self.deck, deck)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.document.blockSignals(False)
        self.deck.blockSignals(False)

    def reload(self) -> None:
        statuses = None
        mistakes = False
        if self.kind == "learning":
            statuses = NEW_WORD_STATUSES
        elif self.kind == "mastered":
            statuses = (STATUS_MASTERED,)
        else:
            mistakes = True
        rows, total = self.ctx.store.list_words(
            statuses=statuses,
            query=self.search.text(),
            document_id=self.document.currentData(),
            deck_id=self.deck.currentData(),
            mistakes_only=mistakes,
            sort=self.sort.currentData(),
            limit=_PAGE_SIZE,
            offset=self.page * _PAGE_SIZE,
        )
        self.total = total
        if self.page and self.page * _PAGE_SIZE >= total:
            self.page = 0
            return self.reload()
        self.model.set_rows(rows)
        pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self.page_label.setText(f"第 {self.page + 1} / {pages} 页，共 {total} 个")
        self.prev.setEnabled(self.page > 0)
        self.next.setEnabled((self.page + 1) * _PAGE_SIZE < total)

    def _ids(self) -> list[int]:
        return [self.model.rows[index.row()]["id"] for index in self.view.selectionModel().selectedRows()]

    def _prev(self) -> None:
        if self.page:
            self.page -= 1
            self.reload()

    def _next(self) -> None:
        self.page += 1
        self.reload()

    def _add(self) -> None:
        if WordDialog(self.ctx, parent=self).exec():
            self.reload()

    def _batch(self) -> None:
        if BatchDialog(self.ctx, self).exec():
            self.reload()

    def _edit(self) -> None:
        ids = self._ids()
        if len(ids) != 1:
            tell(self, "请选择一个单词再编辑。", "warn")
            return
        if WordDialog(self.ctx, ids[0], self).exec():
            self.reload()

    def _move(self, status: str) -> None:
        ids = self._ids()
        if not ids:
            tell(self, "请先选择单词。", "warn")
            return
        move_words(self.ctx.store, ids, status)
        self.reload()

    def _delete(self) -> None:
        ids = self._ids()
        if not ids:
            tell(self, "请先选择单词。", "warn")
            return
        if confirm(self, f"确定删除选中的 {len(ids)} 个单词吗？学习记录会一起删除。"):
            self.ctx.store.delete_words(ids)
            self.reload()

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "导出 CSV", "wordflow.csv", "CSV (*.csv)")
        if not path:
            return
        statuses = None
        if self.kind == "learning":
            statuses = NEW_WORD_STATUSES
        elif self.kind == "mastered":
            statuses = (STATUS_MASTERED,)
        rows = self.ctx.store.export_rows(deck_id=self.deck.currentData(), statuses=statuses)
        export_csv(path, rows)
        tell(self, f"已导出 {len(rows)} 行。")

    def _review(self) -> None:
        ids = self._ids() or [row["id"] for row in self.model.rows]
        if not ids:
            tell(self, "当前没有可复习的错题。", "warn")
            return
        self.navigator.open_review_words(ids)


class ConfusionPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        layout = QVBoxLayout(self)
        note = QLabel("下面只对照本地词典里的真实释义和音标。词典没有的词会显示待补充，不会写一套看起来像词典的解释。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.body)
        layout.addStretch(1)

    def on_show(self) -> None:
        path = confusion_path()
        if path is None:
            self.body.setText("没有找到易混淆词表。")
            return
        if not self.ctx.dictionary.available:
            self.body.setText("本地词典未加载，无法显示可靠释义。")
            return
        blocks = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            left, right = [part.strip() for part in line.split("|", 1)]
            blocks.append(self._pair(left) + "\n" + self._pair(right))
        self.body.setText("\n\n".join(blocks))

    def _pair(self, word: str) -> str:
        entry = self.ctx.dictionary.lookup(word)
        if entry is None:
            return f"{word}：待补充"
        phonetic = format_phonetic(entry.phonetic)
        senses = "；".join(
            f"{sense.pos + '. ' if sense.pos else ''}{sense.gloss_zh}" for sense in entry.senses
        ) or "待补充"
        return f"{word}  {phonetic}\n{senses}"


class MistakePage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.words = WordListPage(ctx, navigator, "mistakes")
        self.confusion = ConfusionPage(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        tabs.addTab(self.words, "错题")
        tabs.addTab(self.confusion, "易混淆词")
        tabs.currentChanged.connect(self._changed)
        layout.addWidget(tabs)

    def on_show(self) -> None:
        self.words.on_show()
        self.confusion.on_show()

    def _changed(self, index: int) -> None:
        if index == 1:
            self.confusion.on_show()
