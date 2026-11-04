"""摸底、新词和复习三个入口。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wordflow.jobs import start_session
from wordflow.study import StudyService
from wordflow.ui.common import page_header, tell
from wordflow.ui.study_widget import StudyWidget
from wordflow.ui.workers import CallWorker


class PracticePage(QWidget):
    def __init__(self, ctx, navigator, kind: str):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.kind = kind
        self.worker: CallWorker | None = None
        self.preset_ids: list[int] | None = None
        self.study_widget: StudyWidget | None = None
        titles = {
            "placement": ("摸底测试", "先判断哪些词已经认识。答错会进入生词本，答对只记为初步认识。"),
            "learn": ("学习新词", "优先学习还没正式学过、掌握程度低、在你的材料里更常见的词。"),
            "review": ("今日复习", "到期的生词会排在新词前面。答错会缩短间隔，答对会逐渐拉长。"),
        }
        layout = QVBoxLayout(self)
        layout.addWidget(page_header(*titles[kind]))
        self.stack = QStackedWidget()
        self.setup = QWidget()
        self.session_host = QWidget()
        self.session_layout = QVBoxLayout(self.session_host)
        self.report = QWidget()
        self._build_setup()
        self._build_report()
        self.stack.addWidget(self.setup)
        self.stack.addWidget(self.session_host)
        self.stack.addWidget(self.report)
        layout.addWidget(self.stack)

    def _build_setup(self) -> None:
        layout = QVBoxLayout(self.setup)
        self.resume_label = QLabel()
        self.resume_label.setObjectName("banner")
        self.resume_label.setWordWrap(True)
        self.resume_label.hide()
        layout.addWidget(self.resume_label)
        resume_row = QHBoxLayout()
        self.resume_button = QPushButton("继续上次")
        self.resume_button.setObjectName("primary")
        self.resume_button.clicked.connect(self._resume)
        self.abandon_button = QPushButton("放弃上次")
        self.abandon_button.clicked.connect(self._abandon)
        resume_row.addWidget(self.resume_button)
        resume_row.addWidget(self.abandon_button)
        resume_row.addStretch(1)
        self.resume_button.hide()
        self.abandon_button.hide()
        layout.addLayout(resume_row)
        self.due_label = QLabel()
        self.due_label.setWordWrap(True)
        layout.addWidget(self.due_label)
        form = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("单词卡片", "card")
        self.mode.addItem("四选一", "quiz")
        self.mode.addItem("拼写", "spell")
        self.mode.addItem("语境填空", "cloze")
        self.mode.addItem("听音选义", "listen")
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.document = QComboBox()
        self.deck = QComboBox()
        self.pending = QCheckBox("包含待确认的词")
        self.pending.setChecked(True)
        self.mistakes = QCheckBox("只复习错题")
        if self.kind != "placement":
            form.addWidget(QLabel("方式"))
            form.addWidget(self.mode)
        form.addWidget(QLabel("数量"))
        form.addWidget(self.count)
        if self.kind != "review":
            form.addWidget(QLabel("文章"))
            form.addWidget(self.document)
        form.addWidget(QLabel("词库"))
        form.addWidget(self.deck)
        form.addStretch(1)
        layout.addLayout(form)
        if self.kind == "placement":
            layout.addWidget(self.pending)
        if self.kind == "review":
            layout.addWidget(self.mistakes)
        self.start_button = QPushButton("开始")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        layout.addWidget(self.start_button)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch(1)
        self.mode.setVisible(self.kind != "placement")

    def _build_report(self) -> None:
        layout = QVBoxLayout(self.report)
        self.report_title = QLabel("本次结果")
        self.report_title.setObjectName("pageTitle")
        self.report_body = QLabel()
        self.report_body.setWordWrap(True)
        layout.addWidget(self.report_title)
        layout.addWidget(self.report_body)
        row = QHBoxLayout()
        self.learn_button = QPushButton("学习本次生词")
        self.learn_button.setObjectName("primary")
        self.learn_button.clicked.connect(self._learn_wrong)
        back = QPushButton("返回")
        back.clicked.connect(self._back_to_setup)
        undo = QPushButton("撤销上一题")
        undo.clicked.connect(self._undo_last)
        row.addWidget(self.learn_button)
        row.addWidget(undo)
        row.addWidget(back)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self._learning_ids: list[int] = []

    def on_show(self) -> None:
        if self.study_widget is not None:
            return
        self._fill_filters()
        self._show_resume()
        if self.kind == "review":
            data = self.ctx.store.dashboard(self.ctx.settings.integer("daily_new_limit", 20))
            self.due_label.setText(
                f"到期生词 {data['due_learning']} 个，熟词抽查 {data['due_mastered']} 个。"
                "建议先完成复习，再学新词。"
            )
            self.count.setValue(self.ctx.settings.integer("review_limit", 50))
            saved = self.ctx.settings.get("review_mode", "card")
        elif self.kind == "learn":
            data = self.ctx.store.dashboard(self.ctx.settings.integer("daily_new_limit", 20))
            remain = max(0, data["daily_goal"] - data["new_today"])
            self.due_label.setText(f"今日新词目标 {data['daily_goal']} 个，已经学习 {data['new_today']} 个，还剩 {remain} 个。")
            self.count.setValue(max(1, remain or data["daily_goal"]))
            saved = self.ctx.settings.get("learn_mode", "card")
        else:
            self.due_label.setText("没有可靠中文释义的单词不会出题，也不会编造选项。")
            self.count.setValue(self.ctx.settings.integer("placement_count", 20))
            saved = "quiz"
        index = self.mode.findData(saved)
        if index >= 0:
            self.mode.setCurrentIndex(index)

    def start_with_words(self, word_ids: list[int]) -> None:
        self.preset_ids = list(word_ids)
        self._start()

    def _fill_filters(self) -> None:
        current_doc = self.document.currentData()
        current_deck = self.deck.currentData()
        self.document.blockSignals(True)
        self.deck.blockSignals(True)
        self.document.clear()
        self.deck.clear()
        self.document.addItem("全部文章", None)
        for document in self.ctx.store.list_documents():
            self.document.addItem(document["title"], document["id"])
        self.deck.addItem("全部词库", None)
        for deck in self.ctx.store.list_decks():
            self.deck.addItem(deck["name"], deck["id"])
        self._restore(self.document, current_doc)
        self._restore(self.deck, current_deck)
        self.document.blockSignals(False)
        self.deck.blockSignals(False)

    def _restore(self, combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _show_resume(self) -> None:
        active = self.ctx.store.get_active_session(self.kind)
        visible = active is not None
        self.resume_label.setVisible(visible)
        self.resume_button.setVisible(visible)
        self.abandon_button.setVisible(visible)
        self._active_id = active["id"] if active else None
        if active:
            self.resume_label.setText("有一份还没做完的练习，可以继续，也可以放弃后重新开始。已回答的题目已经保存。")

    def _resume(self) -> None:
        if self._active_id:
            self._mount(self._active_id)

    def _abandon(self) -> None:
        if self._active_id:
            StudyService(self.ctx.store, self.ctx.dictionary).abandon(self._active_id)
        self._show_resume()

    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        mode = self.mode.currentData() if self.kind != "placement" else "quiz"
        limit = self.count.value()
        document_id = self.document.currentData()
        deck_id = self.deck.currentData()
        preset = self.preset_ids
        self.preset_ids = None
        if self.kind == "placement":
            payload = {
                "limit": limit,
                "document_id": document_id,
                "deck_id": deck_id,
                "include_pending": self.pending.isChecked(),
            }
        elif self.kind == "learn":
            payload = {
                "mode": mode,
                "limit": limit,
                "document_id": document_id,
                "deck_id": deck_id,
                "word_ids": preset,
            }
            self.ctx.settings.set("learn_mode", mode)
        else:
            payload = {
                "mode": mode,
                "limit": max(limit, len(preset or [])),
                "deck_id": deck_id,
                "mistakes_only": self.mistakes.isChecked() and not preset,
                "word_ids": preset,
            }
            self.ctx.settings.set("review_mode", mode)
        self.start_button.setEnabled(False)
        self.note.setText("正在准备题目…")

        def job(_worker):
            return start_session(self.ctx.db_path, self.ctx.dict_path, self.kind, payload)

        self.worker = CallWorker(job, self)
        self.worker.succeeded.connect(self._started)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _started(self, result: dict) -> None:
        self.start_button.setEnabled(True)
        self.note.setText(result.get("message") or "")
        if not result.get("session_id"):
            tell(self, result.get("message") or "没有可开始的单词。", "warn")
            return
        self._mount(result["session_id"])

    def _failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        tell(self, message, "error")

    def _mount(self, session_id: int) -> None:
        while self.session_layout.count():
            item = self.session_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.study_widget = StudyWidget(self.ctx, session_id, self)
        self.study_widget.finished.connect(self._finished)
        self.study_widget.paused.connect(self._paused)
        self.session_layout.addWidget(self.study_widget)
        if self.study_widget.done:
            self._finished(StudyService(self.ctx.store, self.ctx.dictionary).report(session_id))
            return
        self.stack.setCurrentWidget(self.session_host)
        self.study_widget.setFocus()

    def _paused(self) -> None:
        self.study_widget = None
        self.stack.setCurrentWidget(self.setup)
        self._show_resume()

    def _finished(self, report: dict) -> None:
        self.study_widget = None
        self._learning_ids = report.get("learning_ids") or []
        lines = [
            f"题目 {report['total']} 道",
            f"正确 {report['correct']}，错误 {report['wrong']}，不认识 {report['unknown']}，跳过 {report['skip']}",
            f"正确率 {report['accuracy']}%（跳过不计入）",
            f"标记已掌握 {report['mastered']}，进入生词 {len(self._learning_ids)}",
        ]
        if report["frequent_wrong"]:
            lines.append("")
            lines.append("出现较多的错词：")
            for item in report["frequent_wrong"]:
                lines.append(f"· {item['lemma']}  {item['gloss']}  （出现 {item['frequency']} 次）")
        self.report_body.setText("\n".join(lines))
        self.learn_button.setVisible(self.kind == "placement" and bool(self._learning_ids))
        self.stack.setCurrentWidget(self.report)

    def _undo_last(self) -> None:
        result = StudyService(self.ctx.store, self.ctx.dictionary).undo_last()
        if not result:
            tell(self, "没有可以撤销的作答。", "warn")
            return
        tell(self, f"已撤销 {result['lemma']} 的最近一次作答。学习记录已恢复。", "info")

    def _learn_wrong(self) -> None:
        if self._learning_ids:
            self.navigator.open_learn_words(self._learning_ids)

    def _back_to_setup(self) -> None:
        self.stack.setCurrentWidget(self.setup)
        self.on_show()

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.wait(1500)
