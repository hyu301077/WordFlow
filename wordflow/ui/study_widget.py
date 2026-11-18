"""摸底、学习和复习共用的答题界面。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wordflow.collocation import phrases_in_sentences
from wordflow.constants import RATING_AGAIN, RATING_GOOD, RATING_HARD, RATING_MASTERED
from wordflow.gloss import norm_gloss
from wordflow.playback import ClipPlayer
from wordflow.srs import clamp_retention, format_interval, preview_intervals, retrievability
from wordflow.study import StudyService
from wordflow.timeutil import now_local
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
        self.sentence_rate = 1.0
        self._sentence_text = ""
        self._sentence_wav: Path | None = None
        self._tts_files: list[Path] = []
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        self.done = self.index >= len(self.items)
        if not self.done:
            self._render()

    def _build(self) -> None:
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        host = QWidget()
        host.setMaximumWidth(780)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        self.progress = QLabel()
        self.progress.setObjectName("progressLabel")
        self.progress.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.progress)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("studyProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        outer.addWidget(self.progress_bar)
        frame, layout = card()
        frame.setObjectName("wordCard")
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(12)
        self.word = QLabel()
        self.word.setObjectName("wordTitle")
        self.word.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.word)
        meta = QHBoxLayout()
        self.phonetic = QLabel()
        self.phonetic.setObjectName("phonetic")
        self.phonetic.setAlignment(Qt.AlignCenter)
        self.speak_button = QPushButton("朗读")
        self.speak_button.clicked.connect(lambda: self._speak(True))
        self.speak_sentence = QPushButton("朗读例句")
        self.speak_sentence.clicked.connect(lambda: self._speak_sentence(True))
        self.sentence_rate_group = QButtonGroup(self)
        self.sentence_rate_group.setExclusive(True)
        self.sentence_rate_buttons: dict[float, QPushButton] = {}
        for rate in (1.0, 0.75):
            button = QPushButton(f"{rate:g}×")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=rate: self._choose_sentence_rate(value))
            self.sentence_rate_group.addButton(button)
            self.sentence_rate_buttons[rate] = button
        meta.addStretch(1)
        meta.addWidget(self.phonetic)
        meta.addWidget(self.speak_button)
        meta.addWidget(self.speak_sentence)
        for button in self.sentence_rate_buttons.values():
            meta.addWidget(button)
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
        self.answer_box.setObjectName("sense")
        self.answer_box.setWordWrap(True)
        self.answer_box.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.answer_box)
        self.example = QLabel()
        self.example.setObjectName("exampleLine")
        self.example.setWordWrap(True)
        self.example.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.example)
        self.phrases = QLabel()
        self.phrases.setWordWrap(True)
        self.phrases.setAlignment(Qt.AlignCenter)
        self.phrases.setObjectName("muted")
        layout.addWidget(self.phrases)
        self.recall = QLabel()
        self.recall.setAlignment(Qt.AlignCenter)
        self.recall.setObjectName("muted")
        layout.addWidget(self.recall)
        self.spell = QLineEdit()
        self.spell.setPlaceholderText("输入英文单词后按 Enter")
        self.spell.setMinimumWidth(260)
        self.spell.setMaximumWidth(460)
        self.spell.setAlignment(Qt.AlignCenter)
        self.spell.returnPressed.connect(self._submit_spelling)
        spell_row = QHBoxLayout()
        spell_row.addStretch(1)
        spell_row.addWidget(self.spell)
        spell_row.addStretch(1)
        layout.addLayout(spell_row)
        self.option_host = QVBoxLayout()
        layout.addLayout(self.option_host)
        self.extra = QHBoxLayout()
        layout.addLayout(self.extra)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.reveal_button = QPushButton("显示释义")
        self.reveal_button.clicked.connect(self._reveal_card)
        self.next_button = QPushButton("下一题")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self._next)
        edit = QPushButton("编辑释义")
        edit.clicked.connect(self._edit)
        undo = QPushButton("撤销上一题")
        undo.clicked.connect(self._undo)
        leave = QPushButton("暂停并退出")
        leave.clicked.connect(self.paused.emit)
        actions.addWidget(self.reveal_button)
        actions.addWidget(self.next_button)
        actions.addWidget(edit)
        actions.addWidget(undo)
        actions.addStretch(1)
        actions.addWidget(leave)
        layout.addSpacing(8)
        layout.addLayout(actions)
        outer.addWidget(frame)
        hint = QLabel("1–4 选择或评分    Space 朗读单词    Enter 确认或下一题    Ctrl+Z 撤销    S 不认识    F 加入熟词本    Esc 退出")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint)
        row.addStretch(1)
        row.addWidget(host, 4)
        row.addStretch(1)
        shell.addLayout(row)
        shell.addStretch(1)
        self.sentence_player = ClipPlayer(self)
        self.sentence_player.failed.connect(self._sentence_failed)
        self._restore_sentence_rate()

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
                widget.hide()
                widget.deleteLater()

    def _render(self) -> None:
        item = self.current
        mode = self._mode()
        prompts = {"spell": "拼写", "cloze": "填空", "listen": "听音"}
        hide_word = mode in prompts and self.phase == "ask"
        self.progress.setText(f"{self.index + 1} / {len(self.items)}")
        self.progress_bar.setMaximum(max(1, len(self.items)))
        self.progress_bar.setValue(self.index + 1)
        self.word.setText(prompts[mode] if hide_word else item["display"] or item["lemma"])
        self.phonetic.setText("" if hide_word else format_phonetic(item["phonetic"]))
        placement = mode == "placement"
        self.speak_button.setText("朗读单词" if placement else "朗读")
        self.speak_button.setVisible(not (mode == "cloze" and self.phase == "ask"))
        self.speak_sentence.setVisible(placement)
        for button in self.sentence_rate_buttons.values():
            button.setVisible(placement)
        self.pos_label.setText("" if hide_word else f"词性：{item['prompt_pos']}" if item.get("prompt_pos") else "")
        self.example.setText("" if hide_word and mode != "cloze" else item["example"] or "")
        show_answer = self.phase in {"rate", "feedback"}
        self.answer_box.setText(self._sense_text() if show_answer and mode != "cloze" else item["lemma"] if mode == "cloze" and self.phase == "feedback" else "")
        if mode == "card" and self.phase == "ask":
            self.prompt.setText("先回忆词义，再显示释义。")
        elif mode == "spell" and self.phase == "ask":
            self.prompt.setText(item["correct_gloss"] or "待补充")
        elif mode == "cloze" and self.phase == "ask":
            self.prompt.setText("根据你文章里的句子，填出空缺的单词。不会朗读这个词。")
        elif mode == "listen" and self.phase == "ask":
            self.prompt.setText("听读音，选择中文意思。作答前不显示单词。")
        elif mode == "placement":
            self.prompt.setText("请选择这个词性下的中文意思。只有一个选项是正确的。")
        elif mode == "quiz" and self.phase == "ask":
            self.prompt.setText("请选择正确的中文意思。")
        else:
            self.prompt.setText("")
        self.spell.setVisible(mode in {"spell", "cloze"} and self.phase == "ask")
        if not self.spell.isHidden():
            self.spell.clear()
        self.reveal_button.setVisible(mode == "card" and self.phase == "ask")
        self.next_button.setVisible(self.phase == "feedback")
        self._clear(self.option_host)
        self._clear(self.extra)
        self.option_buttons = []
        if mode in {"placement", "quiz", "listen"} and self.phase in {"ask", "feedback"}:
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
        if mode == "placement" and self.phase in {"ask", "feedback"}:
            actions = [("加入生词本", "unknown"), ("加入熟词本", "mastered")]
            if self.phase == "ask":
                actions = [("不认识", "unknown"), ("跳过", "skip"), *actions]
            for label, value in actions:
                button = QPushButton(label)
                button.clicked.connect(lambda _checked=False, outcome=value: self._placement(outcome))
                self.extra.addWidget(button)
        if mode == "card" and self.phase == "rate":
            ratings = _REVIEW_RATINGS if self.session["kind"] == "review" else _CARD_RATINGS
            intervals = self._intervals()
            for rating, label in ratings:
                button = QPushButton(f"{label}    {intervals.get(rating, '')}".rstrip())
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
            scheduled = self._scheduled_text()
            if result == "correct":
                self.feedback.setText(f"答对了。{gloss}{scheduled}")
            elif result == "unknown":
                self.feedback.setText(f"已加入生词本。正确答案：{gloss}。{scheduled}")
            elif result == "wrong":
                chosen = self.record.get("chosen") or ""
                if mode in {"spell", "cloze"}:
                    self.feedback.setText(f"正确拼写：{item['lemma']}。你的输入：{chosen or '（空白）'}。{scheduled}")
                else:
                    extra = f"你选择了：{chosen}。 " if chosen else ""
                    self.feedback.setText(f"正确答案：{gloss}。{extra}{scheduled}")
            elif result == "mastered":
                self.feedback.setText(f"已加入熟词本。{gloss}。{scheduled}")
            else:
                self.feedback.setText(scheduled)
        else:
            self.feedback.setText("")
        self._show_memory(hide_word)
        if mode == "listen" and self.phase == "ask":
            self._speak(False)
        elif self.phase == "ask" and mode != "cloze" and self.ctx.settings.flag("auto_speak"):
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
        if self._mode() == "cloze" and self.phase == "ask":
            return
        self.sentence_player.stop()
        text = self.current["display"] or self.current["lemma"]
        if self._mode() != "placement" and self.phase != "ask" and self.current.get("example"):
            text = self.current["example"]
        ok, message = self.ctx.speech.speak(text)
        if manual and not ok:
            tell(self, message, "warn")

    def _restore_sentence_rate(self) -> None:
        rate = self.ctx.settings.real("placement_sentence_rate", 1.0)
        if not any(abs(rate - item) < 0.001 for item in self.sentence_rate_buttons):
            rate = 1.0
        self._choose_sentence_rate(rate, replay=False)

    def _choose_sentence_rate(self, rate: float, replay: bool = True) -> None:
        self.sentence_rate = rate
        self.ctx.settings.set("placement_sentence_rate", f"{rate:g}")
        button = self.sentence_rate_buttons.get(rate)
        if button:
            button.setChecked(True)
        example = (self.current.get("example") or "").strip() if self.items and 0 <= self.index < len(self.items) else ""
        if replay and example and example == self._sentence_text and (self.sentence_player._playing or self.sentence_player._paused):
            self.sentence_player.set_rate(rate)

    def _speak_sentence(self, manual: bool) -> None:
        text = (self.current.get("example") or "").strip()
        if not text:
            if manual:
                tell(self, "这个单词没有实例句子。", "warn")
            return
        self.sentence_player.stop()
        if text != self._sentence_text or self._sentence_wav is None or not self._sentence_wav.is_file():
            path, message = self.ctx.speech.synthesize(text)
            if path is None:
                if manual:
                    tell(self, message, "warn")
                return
            self._forget_tts(path)
            self._sentence_text = text
            self._sentence_wav = path
            self._tts_files.append(path)
        self.sentence_player.rate = self.sentence_rate
        self.sentence_player.play_file(str(self._sentence_wav))

    def _forget_tts(self, keep: Path) -> None:
        for path in list(self._tts_files):
            if path == keep:
                continue
            path.unlink(missing_ok=True)
            self._tts_files.remove(path)

    def _sentence_failed(self, message: str) -> None:
        if message:
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
            if self.phase != "ask":
                return
            self._save(result="skip", rating="skip", chosen=None)
            self._next()
            return
        if self.phase == "feedback" and self.record:
            if self.record.get("result") == result:
                return
            when = self.record["state_after"].last_review_at or now_local()
            payload = self.service.refile_placement(self.record["log_id"], self.current, result, self.record["state_before"], when)
            payload["chosen"] = self.record.get("chosen")
            self.record = payload
            self.current["result"] = payload["result"]
            self._render()
            return
        if self.phase != "ask":
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
        if self.phase != "rate":
            return
        self._save(result=None, rating=rating, chosen=None)
        self._next()

    def _submit_spelling(self) -> None:
        if self._mode() not in {"spell", "cloze"} or self.phase != "ask":
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
            desired_retention=self._retention(),
            leech_threshold=self._leech_limit(),
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
                desired_retention=self._retention(),
                leech_threshold=self._leech_limit(),
            )
        payload["chosen"] = chosen
        self.record = payload
        self.current["result"] = payload["result"]

    def _next(self) -> None:
        self.sentence_player.stop()
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

    def _retention(self) -> float:
        return clamp_retention(self.ctx.settings.real("desired_retention", 0.9))

    def _leech_limit(self) -> int:
        return self.ctx.settings.integer("leech_threshold", 8)

    def _intervals(self) -> dict[str, str]:
        state = self.ctx.store.load_state(self.current["word_id"])
        return preview_intervals(
            state,
            now_local(),
            desired_retention=self._retention(),
            leech_threshold=self._leech_limit(),
        )

    def _scheduled_text(self) -> str:
        after = (self.record or {}).get("state_after")
        if not after or after.next_review_at is None:
            return ""
        return f" 下次大约 {format_interval(after.interval_days)}后。"

    def _show_memory(self, hide_word: bool) -> None:
        state = self.ctx.store.load_state(self.current["word_id"])
        notes = []
        if state.leech:
            notes.append("多次遗忘")
        if not hide_word:
            chance = retrievability(state, now_local(), self._retention())
            if chance is not None:
                notes.append(f"当前可提取性 {round(chance * 100)}%")
        self.recall.setText(" · ".join(notes))
        if hide_word and self.phase == "ask":
            self.phrases.setText("")
            return
        sentences = [row["sentence"] for row in self.ctx.store.examples_of(self.current["word_id"])]
        found = phrases_in_sentences(self.current["lemma"], sentences)
        self.phrases.setText("来自你的文章：" + "；".join(found) if found else "")

    def _undo(self) -> None:
        result = self.service.undo_last(self.session["id"])
        if not result:
            tell(self, "这场练习没有可撤销的作答，或该词已有更新的学习记录。", "warn")
            return
        self.items = self.ctx.store.session_items(self.session["id"])
        self.session = self.ctx.store.get_session(self.session["id"])
        for index, item in enumerate(self.items):
            if item["word_id"] == result["word_id"] and not item["result"]:
                self.index = index
                break
        self.record = None
        self.phase = "ask"
        self.done = self.index >= len(self.items)
        if self.done:
            return
        self._render()
        tell(self, f"已撤销 {result['lemma']} 的最近一次作答。", "info")

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Undo) and not self.spell.hasFocus():
            self._undo()
            return
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
        if text in {"1", "2", "3", "4"} and mode in {"placement", "quiz", "listen"} and self.phase == "ask":
            self._choose(int(text) - 1)
            return
        if text in {"1", "2", "3", "4"} and mode == "card" and self.phase == "rate":
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
        if text.lower() == "s" and mode == "placement" and self.phase in {"ask", "feedback"}:
            self._placement("unknown")
            return
        if text.lower() == "f" and mode == "placement" and self.phase in {"ask", "feedback"}:
            self._placement("mastered")
            return
        super().keyPressEvent(event)
