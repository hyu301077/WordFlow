"""摸底、学习和复习共用的答题界面。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from wordflow.constants import RATING_AGAIN, RATING_GOOD, RATING_HARD, RATING_MASTERED
from wordflow.gloss import norm_gloss
from wordflow.study import StudyService
from wordflow.ui.common import card, format_phonetic, mark_button, tell
from wordflow.ui.dialogs import WordDialog

_CARD_RATINGS = [
    (RATING_AGAIN, "1  不认识"),
    (RATING_HARD, "2  模糊"),
    (RATING_GOOD, "3  认识"),
    (RATING_MASTERED, "4  已熟练掌握"),
]
_REVIEW_RATINGS = [
    (RATING_AGAIN, "1  不认识"),
    (RATING_HARD, "2  模糊"),
    (RATING_GOOD, "3  认识"),
    ("easy", "4  非常熟悉"),
]


class StudyWidget(QWidget):
    finished = Signal(object)
    paused = Signal()

    def __init__(self, ctx, session_id: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.service = StudyService(ctx.store, ctx.dictionary)
        self.session = ctx.store.get_session(session_id)
        self.items = ctx.store.session_items(session_id)
        self.index = 0
        while self.index < len(self.items) and self.items[self.index]["result"]:
            self.index += 1
        self.phase = "ask"
        self.record = None
        self.option_buttons: list[QPushButton] = []
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        self.done = self.index >= len(self.items)
        if not self.done:
            self._render()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        outer.addWidget(self.progress)
        frame, layout = card()
        frame.setObjectName("wordCard")
        self.word = QLabel()
        self.word.setObjectName("wordTitle")
        self.word.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.word)
        meta = QHBoxLayout()
        self.phonetic = QLabel()
        self.phonetic.setAlignment(Qt.AlignCenter)
        self.speak_button = QPushButton("朗读")
        self.speak_button.clicked.connect(lambda: self._speak(True))
        meta.addStretch(1)
        meta.addWidget(self.phonetic)
        meta.addWidget(self.speak_button)
        meta.addStretch(1)
        layout.addLayout(meta)
        self.pos_label = QLabel()
        self.pos_label.setAlignment(Qt.AlignCenter)
        self.pos_label.setObjectName("muted")
        layout.addWidget(self.pos_label)
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.prompt)
        self.answer_box = QLabel()
        self.answer_box.setWordWrap(True)
        self.answer_box.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.answer_box)
        self.example = QLabel()
        self.example.setWordWrap(True)
        self.example.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.example)
        self.spell = QLineEdit()
        self.spell.setPlaceholderText("输入英文单词后按 Enter")
        self.spell.returnPressed.connect(self._submit_spelling)
        layout.addWidget(self.spell)
        self.option_host = QVBoxLayout()
        layout.addLayout(self.option_host)
        self.extra = QHBoxLayout()
        layout.addLayout(self.extra)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.feedback)
        outer.addWidget(frame)
        hint = QLabel("1–4 选择或评分    Space 朗读    Enter 确认 / 下一题    S 生词    F 熟词    Esc 退出")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint)
        actions = QHBoxLayout()
        self.reveal_button = QPushButton("显示释义")
        self.reveal_button.clicked.connect(self._reveal_card)
        self.next_button = QPushButton("下一题")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self._next)
        edit = QPushButton("编辑释义")
        edit.clicked.connect(self._edit)
        leave = QPushButton("暂停并退出")
        leave.clicked.connect(self.paused.emit)
        actions.addWidget(self.reveal_button)
        actions.addWidget(self.next_button)
        actions.addWidget(edit)
        actions.addStretch(1)
        actions.addWidget(leave)
        outer.addLayout(actions)

    @property
    def current(self) -> dict:
        return self.items[self.index]

    def _mode(self) -> str:
        if self.session["kind"] == "placement":
            return "placement"
        return self.session["mode"] or "card"

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self) -> None:
        item = self.current
        mode = self._mode()
        self.progress.setText(f"{self.index + 1} / {len(self.items)}")
        self.word.setText(item["display"] or item["lemma"])
        self.phonetic.setText(format_phonetic(item["phonetic"]))
        self.pos_label.setText(f"词性：{item['prompt_pos']}" if item.get("prompt_pos") else "")
        self.example.setText(item["example"] or "")
        show_answer = self.phase in {"rate", "feedback"} or (mode == "spell" and self.phase == "feedback")
        self.answer_box.setText(self._sense_text() if show_answer else "")
        if mode == "card" and self.phase == "ask":
            self.prompt.setText("先回忆词义，再显示释义。")
        elif mode == "spell" and self.phase == "ask":
            self.prompt.setText(item["correct_gloss"] or "待补充")
        elif mode == "placement":
            self.prompt.setText("请选择这个词性下的中文意思。只有一个选项是正确的。")
        elif mode == "quiz" and self.phase == "ask":
            self.prompt.setText("请选择正确的中文意思。")
        else:
            self.prompt.setText("")
        self.spell.setVisible(mode == "spell" and self.phase == "ask")
        if self.spell.isVisible():
            self.spell.clear()
        self.reveal_button.setVisible(mode == "card" and self.phase == "ask")
        self.next_button.setVisible(self.phase == "feedback")
        self._clear(self.option_host)
        self._clear(self.extra)
        self.option_buttons = []
        if mode in {"placement", "quiz"} and self.phase in {"ask", "feedback"}:
            chosen = (self.record or {}).get("chosen")
            for index, option in enumerate(item["options"]):
                button = QPushButton(f"{chr(65 + index)}.  {option}")
                if self.phase == "ask":
                    button.clicked.connect(lambda _checked=False, number=index: self._choose(number))
                else:
                    button.setEnabled(False)
                    if norm_gloss(option) == norm_gloss(item.get("correct_gloss")):
                        mark_button(button, "correct")
                    elif chosen and norm_gloss(option) == norm_gloss(chosen):
                        mark_button(button, "wrong")
                self.option_host.addWidget(button)
                self.option_buttons.append(button)
        if mode == "placement" and self.phase == "ask":
            for label, handler in (
                ("不认识", lambda: self._placement("unknown")),
                ("跳过", lambda: self._placement("skip")),
                ("已熟练掌握", lambda: self._placement("mastered")),
            ):
                button = QPushButton(label)
                button.clicked.connect(handler)
                self.extra.addWidget(button)
        if mode == "card" and self.phase == "rate":
            ratings = _REVIEW_RATINGS if self.session["kind"] == "review" else _CARD_RATINGS
            for rating, label in ratings:
                button = QPushButton(label)
                button.clicked.connect(lambda _checked=False, value=rating: self._rate(value))
                self.option_host.addWidget(button)
        if self.phase == "feedback" and mode == "quiz" and self.record and self.record["result"] == "correct":
            for rating, label in (("hard", "改为模糊"), ("good", "保持认识"), ("mastered", "已熟练掌握")):
                button = QPushButton(label)
                button.clicked.connect(lambda _checked=False, value=rating: self._amend(value))
                self.extra.addWidget(button)
        if self.phase == "feedback" and self.record:
            result = self.record["result"]
            gloss = item.get("correct_gloss") or "待补充"
            if result == "correct":
                self.feedback.setText(f"答对了。{gloss}")
            elif result in {"wrong", "unknown"}:
                chosen = self.record.get("chosen") or ""
                extra = f"你选择了：{chosen}。 " if chosen else ""
                self.feedback.setText(f"正确答案：{gloss}。{extra}")
            elif result == "mastered":
                self.feedback.setText("已加入熟词本。")
            else:
                self.feedback.setText("")
        else:
            self.feedback.setText("")
        if self.phase == "ask" and self.ctx.settings.flag("auto_speak"):
            self._speak(False)
        if self.spell.isVisible():
            self.spell.setFocus()
        else:
            self.setFocus()

    def _sense_text(self) -> str:
        senses = self.current.get("senses") or []
        if not senses:
            return "待补充"
        lines = []
        for sense in senses:
            prefix = f"{sense['pos']}. " if sense.get("pos") else ""
            lines.append(prefix + sense["gloss_zh"])
        return "\n".join(lines)

    def _speak(self, manual: bool) -> None:
        text = self.current["display"] or self.current["lemma"]
        if self.phase != "ask" and self.current.get("example"):
            text = self.current["example"]
        ok, message = self.ctx.speech.speak(text)
        if manual and not ok:
            tell(self, message, "warn")

    def _choose(self, index: int) -> None:
        if self.phase != "ask" or index >= len(self.current["options"]):
            return
        chosen = self.current["options"][index]
        correct = norm_gloss(chosen) == norm_gloss(self.current.get("correct_gloss"))
        result = "correct" if correct else "wrong"
        self._save(result=result, rating=RATING_GOOD if correct else RATING_AGAIN, chosen=chosen)
        self.phase = "feedback"
        self._render()

    def _placement(self, result: str) -> None:
        if result == "skip":
            self._save(result="skip", rating="skip", chosen=None)
            self._next()
            return
        rating = RATING_MASTERED if result == "mastered" else RATING_AGAIN
        self._save(result=result, rating=rating, chosen=None)
        self.phase = "feedback"
        self._render()

    def _reveal_card(self) -> None:
        if self._mode() == "card" and self.phase == "ask":
            self.phase = "rate"
            self._render()

    def _rate(self, rating: str) -> None:
        self._save(result=None, rating=rating, chosen=None)
        self._next()

    def _submit_spelling(self) -> None:
        if self._mode() != "spell" or self.phase != "ask":
            return
        typed = self.spell.text().strip().lower().replace("\u2019", "'")
        accepted = {self.current["lemma"].lower()}
        for source in self.ctx.store.sources_of(self.current["word_id"]):
            accepted.add(str(source["surface"]).lower())
        correct = typed in accepted
        self._save(
            result="correct" if correct else "wrong",
            rating=RATING_GOOD if correct else RATING_AGAIN,
            chosen=typed,
        )
        self.phase = "feedback"
        self._render()

    def _amend(self, rating: str) -> None:
        if not self.record:
            return
        when = self.record["state_after"].last_review_at
        self.service.amend(
            self.record["log_id"],
            self.current["word_id"],
            self.record["state_before"],
            rating,
            kind=self.session["kind"],
            when=when,
        )
        self.feedback.setText("已按你的熟悉度调整复习安排。")

    def _save(self, *, result, rating, chosen) -> None:
        if self.session["kind"] == "placement" and rating == "skip":
            payload = self.service.answer(self.session["id"], self.current, result="skip", rating=None, chosen=None)
        else:
            payload = self.service.answer(
                self.session["id"],
                self.current,
                result=result,
                rating=rating,
                chosen=chosen,
            )
        payload["chosen"] = chosen
        self.record = payload
        self.current["result"] = payload["result"]

    def _next(self) -> None:
        self.record = None
        self.phase = "ask"
        self.index += 1
        if self.index >= len(self.items):
            self.finished.emit(self.service.report(self.session["id"]))
            return
        self._render()

    def _edit(self) -> None:
        dialog = WordDialog(self.ctx, self.current["word_id"], self)
        if dialog.exec():
            detail = self.ctx.store.word_detail(self.current["word_id"])
            self.current["senses"] = detail["senses"]
            self.current["phonetic"] = detail["word"]["phonetic"]
            self._render()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.paused.emit()
            return
        if event.key() == Qt.Key_Space and not self.spell.hasFocus():
            self._speak(True)
            return
        text = event.text()
        mode = self._mode()
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and not self.spell.hasFocus():
            if mode == "card" and self.phase == "ask":
                self._reveal_card()
            elif self.phase == "feedback":
                self._next()
            return
        if text in "1234" and mode in {"placement", "quiz"} and self.phase == "ask":
            self._choose(int(text) - 1)
            return
        if text in "1234" and mode == "card" and self.phase == "rate":
            ratings = [RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_MASTERED]
            if self.session["kind"] == "review":
                ratings = [item[0] for item in _REVIEW_RATINGS]
            self._rate(ratings[int(text) - 1])
            return
        if text.lower() == "s" and mode == "card" and self.phase == "rate":
            self._rate(RATING_AGAIN)
            return
        if text.lower() == "f" and mode == "card" and self.phase == "rate":
            self._rate(RATING_MASTERED)
            return
        if text.lower() == "s" and mode == "placement" and self.phase == "ask":
            self._placement("unknown")
            return
        if text.lower() == "f" and mode == "placement" and self.phase == "ask":
            self._placement("mastered")
            return
        super().keyPressEvent(event)
