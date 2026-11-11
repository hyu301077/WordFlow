"""学习计划：把一篇文章或一个导入文件里的单词学到全部掌握。"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from wordflow.ui.common import fill_study_plan_combo, format_phonetic, page_header, status_text, tell


class PlanWordModel(QAbstractTableModel):
    HEADERS = ["单词", "音标", "释义", "词频", "状态"]

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
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


class PlanPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self._plan_id: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            page_header(
                "学习计划",
                "一份计划对应一篇英文文章或一个导入文件。目标是把这份材料里检出的单词全部掌握。",
            )
        )
        row = QHBoxLayout()
        row.addWidget(QLabel("当前计划"))
        self.plan = QComboBox()
        self.plan.currentIndexChanged.connect(self._changed)
        rename = QPushButton("重命名")
        rename.clicked.connect(self._rename)
        row.addWidget(self.plan, 1)
        row.addWidget(rename)
        layout.addLayout(row)
        self.progress_label = QLabel("还没有学习计划。导入文档或英文文章后，点「导入学习计划」。")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        layout.addWidget(self.bar)
        actions = QHBoxLayout()
        for label, slot in (
            ("摸底未测词", self._place),
            ("学习未掌握", self._learn),
            ("复习到期", self._review),
            ("阅读原文", self._read),
            ("移出计划", self._remove),
        ):
            button = QPushButton(label)
            if label == "学习未掌握":
                button.setObjectName("primary")
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.model = PlanWordModel()
        self.view = QTableView()
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.view.setMinimumHeight(160)
        layout.addWidget(self.view, 1)

    def on_show(self) -> None:
        current = self.plan.currentData()
        if self._plan_id is not None:
            current = self._plan_id
        fill_study_plan_combo(self.plan, self.ctx.store, current, all_label="选择一份计划")
        if self.plan.currentData() is None and self.plan.count() > 1:
            self.plan.setCurrentIndex(1)
        self._reload()

    def select_plan(self, document_id: int) -> None:
        self._plan_id = document_id
        fill_study_plan_combo(self.plan, self.ctx.store, document_id, all_label="选择一份计划")
        if self.plan.findData(document_id) < 0:
            document = self.ctx.store.get_document(document_id)
            if document:
                self.plan.addItem(document["title"], document["id"])
                self.plan.setCurrentIndex(self.plan.findData(document_id))
        self._reload()

    def _changed(self) -> None:
        self._plan_id = self.plan.currentData()
        self._reload()

    def _rename(self) -> None:
        plan_id = self._selected()
        if not plan_id:
            return
        document = self.ctx.store.get_document(plan_id)
        current = document["title"] if document else ""
        name, ok = QInputDialog.getText(self, "重命名学习计划", "计划名称", text=current)
        if ok:
            self.apply_name(name)

    def apply_name(self, name: str) -> bool:
        plan_id = self.plan.currentData()
        if not plan_id:
            tell(self, "请先选择一份学习计划。", "warn")
            return False
        title = name.strip()
        if not title:
            tell(self, "计划名称不能为空。", "warn")
            return False
        document = self.ctx.store.get_document(int(plan_id))
        tags = (document or {}).get("tags") or ""
        self.ctx.store.update_document_meta(int(plan_id), title, tags)
        self._plan_id = int(plan_id)
        fill_study_plan_combo(self.plan, self.ctx.store, self._plan_id, all_label="选择一份计划")
        self._reload()
        return True

    def _selected(self) -> int | None:
        plan_id = self.plan.currentData()
        if not plan_id:
            tell(self, "请先选择一份学习计划。", "warn")
            return None
        return int(plan_id)

    def _reload(self) -> None:
        plan_id = self.plan.currentData()
        if not plan_id:
            self.model.set_rows([])
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            self.progress_label.setText("还没有学习计划。导入文档或英文文章后，点「导入学习计划」。")
            return
        rows = self.ctx.store.document_words(int(plan_id))
        rows.sort(key=lambda row: (row.get("status") == "mastered", -(row.get("frequency") or 0), row["lemma"]))
        self.model.set_rows(rows)
        total = len(rows)
        mastered = sum(1 for row in rows if row.get("status") == "mastered")
        document = self.ctx.store.get_document(int(plan_id))
        title = document["title"] if document else "这份计划"
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(mastered)
        if total and mastered == total:
            self.progress_label.setText(f"「{title}」的 {total} 个单词已经全部掌握。")
        else:
            self.progress_label.setText(f"「{title}」已掌握 {mastered} / {total}。未掌握的词排在前面。")

    def _place(self) -> None:
        plan_id = self._selected()
        if not plan_id:
            return
        count = len(self.ctx.store.pick_word_ids(purpose="untested", limit=500, document_id=plan_id, include_pending=True))
        if not count:
            tell(self, "这份计划里没有还没摸底的单词。", "warn")
            return
        self.navigator.go("placement")
        self.navigator.pages["placement"].focus_document(plan_id, count)

    def _learn(self) -> None:
        plan_id = self._selected()
        if not plan_id:
            return
        count = len(self.ctx.store.pick_word_ids(purpose="new", limit=500, document_id=plan_id))
        if not count:
            tell(self, "这份计划里没有还没正式学过的单词。可以复习到期的词。", "warn")
            return
        self.navigator.go("learn")
        self.navigator.pages["learn"].focus_document(plan_id, count)

    def _review(self) -> None:
        plan_id = self._selected()
        if not plan_id:
            return
        count = len(self.ctx.store.pick_word_ids(purpose="due", limit=500, document_id=plan_id))
        if not count:
            tell(self, "这份计划里现在没有到期的单词。", "warn")
            return
        self.navigator.go("review")
        self.navigator.pages["review"].focus_document(plan_id, count)

    def _read(self) -> None:
        plan_id = self._selected()
        if plan_id:
            self.navigator.open_reader(plan_id)

    def _remove(self) -> None:
        plan_id = self._selected()
        if not plan_id:
            return
        self.ctx.store.set_study_plan(plan_id, False)
        self._plan_id = None
        self.on_show()
        tell(self, "已移出学习计划。文档和单词都还在。")
