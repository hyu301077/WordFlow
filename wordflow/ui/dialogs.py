"""添加、编辑和点词卡片。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wordflow.ai import AIError, client_from_settings, explain_prompt
from wordflow.collocation import phrases_in_sentences
from wordflow.constants import STATUS_LABELS
from wordflow.ui.common import format_phonetic, tell
from wordflow.ui.workers import CallWorker
from wordflow.vocab import add_manual_word, batch_add, save_word_edit

_STATUSES = [
    ("learning", "学习中（生词本）"),
    ("reviewing", "复习中（生词本）"),
    ("mastered", "已掌握（熟词本）"),
    ("pending", "待确认"),
    ("untested", "未测试"),
]


class WordDialog(QDialog):
    def __init__(self, ctx, word_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.word_id = word_id
        self.detail = ctx.store.word_detail(word_id) if word_id else None
        self.setWindowTitle("编辑单词" if word_id else "添加单词")
        self.resize(640, 560)
        self.lemma = QLineEdit()
        self.lookup_button = QPushButton("从词典补齐")
        self.lookup_button.clicked.connect(self._lookup)
        self.phonetic = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setFixedHeight(70)
        self.example = QLineEdit()
        self.example.setPlaceholderText("可选，添加一条自己的英文例句")
        self.status = QComboBox()
        for key, label in _STATUSES:
            self.status.addItem(label, key)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["主要", "词性", "中文释义", "英文释义"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.deck_box = QVBoxLayout()
        self.deck_checks: list[tuple[int, QCheckBox]] = []
        self._build()
        if self.detail:
            self._fill()
        else:
            self._add_sense_row(True, "", "", "")
            self._check_default_decks()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        hint = QLabel("词典里没有的音标和释义会保持空白，保存后显示为待补充，不会自动编造。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        lemma_row = QWidget()
        lemma_layout = QHBoxLayout(lemma_row)
        lemma_layout.setContentsMargins(0, 0, 0, 0)
        lemma_layout.addWidget(self.lemma)
        lemma_layout.addWidget(self.lookup_button)
        form.addRow("单词", lemma_row)
        form.addRow("音标", self.phonetic)
        form.addRow("状态", self.status)
        layout.addLayout(form)
        layout.addWidget(QLabel("义项"))
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        add_row = QPushButton("添加义项")
        remove_row = QPushButton("删除义项")
        restore = QPushButton("恢复词典释义")
        add_row.clicked.connect(lambda: self._add_sense_row(False, "", "", ""))
        remove_row.clicked.connect(self._remove_row)
        restore.clicked.connect(self._restore)
        buttons.addWidget(add_row)
        buttons.addWidget(remove_row)
        buttons.addWidget(restore)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("个人笔记"))
        layout.addWidget(self.notes)
        layout.addWidget(QLabel("补充例句"))
        layout.addWidget(self.example)
        self.phrases = QLabel()
        self.phrases.setWordWrap(True)
        self.phrases.setObjectName("muted")
        layout.addWidget(self.phrases)
        explain = QPushButton("用在线助手解释例句")
        explain.clicked.connect(self._explain)
        self.ai_note = QLabel("在线解释只显示在这里，不会写入释义，也不会成为测验答案。")
        self.ai_note.setWordWrap(True)
        self.ai_note.setObjectName("muted")
        layout.addWidget(explain)
        layout.addWidget(self.ai_note)
        layout.addWidget(QLabel("所属词库"))
        deck_host = QWidget()
        deck_host.setLayout(self.deck_box)
        for deck in self.ctx.store.list_decks():
            box = QCheckBox(deck["name"])
            self.deck_box.addWidget(box)
            self.deck_checks.append((deck["id"], box))
        layout.addWidget(deck_host)
        if self.detail:
            source = "；".join(f"{item['title']} ×{item['frequency']}" for item in self.detail["sources"]) or "没有来源文档"
            source_label = QLabel("来源：" + source)
            source_label.setWordWrap(True)
            layout.addWidget(source_label)
            if self.detail["errors"]:
                latest = self.detail["errors"][0]
                layout.addWidget(QLabel(f"最近一次答错：{latest['chosen_gloss'] or '未作答'} / 正确 {latest['correct_gloss'] or ''}"))
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(self._save)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def _fill(self) -> None:
        word = self.detail["word"]
        state = self.detail["state"]
        self.lemma.setText(word["display"] or word["lemma"])
        self.lemma.setReadOnly(True)
        self.lookup_button.setEnabled(False)
        self.phonetic.setText(word["phonetic"] or "")
        self.notes.setPlainText(state["notes"] or "")
        sentences = [row["sentence"] for row in self.detail["examples"]]
        found = phrases_in_sentences(word["lemma"], sentences)
        self.phrases.setText("来自你的文章：" + "；".join(found) if found else "")
        index = self.status.findData(state["status"])
        if index >= 0:
            self.status.setCurrentIndex(index)
        senses = self.detail["senses"]
        if not senses:
            self._add_sense_row(True, "", "", "")
        for sense in senses:
            self._add_sense_row(bool(sense["is_primary"]), sense["pos"] or "", sense["gloss_zh"], sense["gloss_en"] or "")
        selected = set(self.detail["decks"])
        for deck_id, box in self.deck_checks:
            box.setChecked(deck_id in selected)

    def _check_default_decks(self) -> None:
        for deck in self.ctx.store.list_decks():
            if deck["is_default"]:
                for deck_id, box in self.deck_checks:
                    if deck_id == deck["id"]:
                        box.setChecked(True)

    def _add_sense_row(self, primary: bool, pos: str, gloss: str, gloss_en: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        flag = QTableWidgetItem()
        flag.setFlags(flag.flags() | Qt.ItemIsUserCheckable)
        flag.setCheckState(Qt.Checked if primary else Qt.Unchecked)
        self.table.setItem(row, 0, flag)
        self.table.setItem(row, 1, QTableWidgetItem(pos))
        self.table.setItem(row, 2, QTableWidgetItem(gloss))
        self.table.setItem(row, 3, QTableWidgetItem(gloss_en))

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _explain(self) -> None:
        if getattr(self, "_ai_worker", None) and self._ai_worker.isRunning():
            return
        lemma = self.lemma.text().strip()
        sentence = self.example.text().strip()
        if not sentence and self.detail and self.detail["examples"]:
            sentence = self.detail["examples"][0]["sentence"]
        gloss = ""
        if self.table.rowCount() and self.table.item(0, 2):
            gloss = self.table.item(0, 2).text().strip()
        try:
            client = client_from_settings(self.ctx.settings)
            system, user = explain_prompt(lemma, sentence, gloss)
        except AIError as exc:
            tell(self, str(exc), "warn")
            return
        self.ai_note.setText("正在请求模型…")

        def job(_worker):
            return client.complete(system, user)

        self._ai_worker = CallWorker(job, self)
        self._ai_worker.succeeded.connect(lambda text: self._explain_done(lemma, sentence, text))
        self._ai_worker.failed.connect(lambda message: tell(self, message, "error"))
        self._ai_worker.start()

    def _explain_done(self, lemma: str, sentence: str, text: str) -> None:
        self.ai_note.setText("参考：" + text)
        word_id = self.detail["word"]["id"] if self.detail else None
        self.ctx.store.add_ai_record(
            kind="explain",
            title=lemma,
            preview=sentence,
            content=text,
            model=self.ctx.settings.get("ai_model", ""),
            word_id=word_id,
        )

    def _lookup(self) -> None:
        token = self.lemma.text().strip()
        if not token:
            tell(self, "请先输入英文单词。", "warn")
            return
        if not self.ctx.dictionary.available:
            tell(self, "本地词典还没有就绪，可以手动填写，或稍后运行词典下载脚本。", "warn")
            return
        lemma = self.ctx.dictionary.resolve_lemma(token)
        entry = self.ctx.dictionary.lookup(lemma) or self.ctx.dictionary.lookup(token)
        if entry is None or not entry.senses:
            tell(self, "词典里没有这个单词的可靠释义。可以留空保存为待补充，也可以自己填写。")
            if entry and entry.phonetic and not self.phonetic.text().strip():
                self.phonetic.setText(entry.phonetic)
            return
        if entry.phonetic and not self.phonetic.text().strip():
            self.phonetic.setText(entry.phonetic)
        if self.table.rowCount() == 1 and not self.table.item(0, 2).text().strip():
            self.table.removeRow(0)
        if self.table.rowCount() == 0:
            for index, sense in enumerate(entry.senses):
                self._add_sense_row(index == 0, sense.pos, sense.gloss_zh, sense.gloss_en)

    def _restore(self) -> None:
        token = self.lemma.text().strip()
        entry = None
        if self.ctx.dictionary.available and token:
            lemma = token if self.detail is None else self.detail["word"]["lemma"]
            entry = self.ctx.dictionary.lookup(lemma)
        if entry is None or not entry.senses:
            tell(self, "词典里没有可恢复的释义。", "warn")
            return
        self.table.setRowCount(0)
        for index, sense in enumerate(entry.senses):
            self._add_sense_row(index == 0, sense.pos, sense.gloss_zh, sense.gloss_en)
        if entry.phonetic:
            self.phonetic.setText(entry.phonetic)

    def _collect_senses(self) -> list[dict]:
        senses = []
        primary_seen = False
        for row in range(self.table.rowCount()):
            gloss = self.table.item(row, 2).text().strip() if self.table.item(row, 2) else ""
            if not gloss:
                continue
            primary = self.table.item(row, 0).checkState() == Qt.Checked
            if primary and primary_seen:
                primary = False
            primary_seen = primary_seen or primary
            senses.append(
                {
                    "pos": self.table.item(row, 1).text().strip() if self.table.item(row, 1) else "",
                    "gloss_zh": gloss,
                    "gloss_en": self.table.item(row, 3).text().strip() if self.table.item(row, 3) else "",
                    "is_primary": primary,
                }
            )
        if senses and not any(item["is_primary"] for item in senses):
            senses[0]["is_primary"] = True
        return senses

    def _selected_decks(self) -> list[int]:
        return [deck_id for deck_id, box in self.deck_checks if box.isChecked()]

    def _save(self) -> None:
        try:
            senses = self._collect_senses()
            decks = self._selected_decks() or [self.ctx.store.get_default_deck_id()]
            if self.word_id:
                save_word_edit(
                    self.ctx.store,
                    self.word_id,
                    display=self.lemma.text(),
                    phonetic=self.phonetic.text(),
                    senses=senses,
                    notes=self.notes.toPlainText(),
                    status=self.status.currentData(),
                    deck_ids=decks,
                    example=self.example.text(),
                )
            else:
                gloss = senses[0] if senses else {"pos": "", "gloss_zh": "", "gloss_en": ""}
                word_id, _created = add_manual_word(
                    self.ctx.store,
                    self.ctx.dictionary,
                    text=self.lemma.text(),
                    phonetic=self.phonetic.text(),
                    pos=gloss.get("pos", ""),
                    gloss_zh=gloss.get("gloss_zh", ""),
                    gloss_en=gloss.get("gloss_en", ""),
                    notes=self.notes.toPlainText(),
                    status=self.status.currentData(),
                )
                if len(senses) > 1:
                    save_word_edit(
                        self.ctx.store,
                        word_id,
                        display=self.lemma.text(),
                        phonetic=self.phonetic.text(),
                        senses=senses,
                        notes=self.notes.toPlainText(),
                        status=self.status.currentData(),
                        deck_ids=decks,
                        example=self.example.text(),
                    )
                else:
                    self.ctx.store.set_word_decks(word_id, decks)
                    if self.example.text().strip():
                        self.ctx.store.add_example(word_id, None, self.example.text().strip(), source="user")
        except Exception as exc:
            tell(self, str(exc), "warn")
            return
        self.accept()


class BatchDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("批量添加单词")
        self.resize(480, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("每行一个英文单词，也可以用逗号或空格分隔。能在词典里找到的会自动补齐。"))
        self.text = QTextEdit()
        layout.addWidget(self.text)
        self.status = QComboBox()
        self.status.addItem("加入生词本", "learning")
        self.status.addItem("标记为未测试", "untested")
        layout.addWidget(self.status)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(self._save)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def _save(self) -> None:
        result = batch_add(self.ctx.store, self.ctx.dictionary, self.text.toPlainText(), self.status.currentData())
        tell(
            self,
            f"新加入 {result['added']} 个，已存在 {result['existed']} 个，"
            f"待补充释义 {result['pending']} 个，无法识别 {result['invalid']} 个。",
        )
        self.accept()


class LookupDialog(QDialog):
    def __init__(self, ctx, lemma: str, document_id: int | None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.lemma = lemma.lower()
        self.document_id = document_id
        self.setWindowTitle(self.lemma)
        self.resize(420, 320)
        word = ctx.store.get_word_by_lemma(self.lemma)
        entry = ctx.dictionary.lookup(self.lemma) if ctx.dictionary.available else None
        layout = QVBoxLayout(self)
        title = QLabel(word["display"] if word else self.lemma)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        phonetic = word["phonetic"] if word and word["phonetic"] else (entry.phonetic if entry else None)
        phonetic_row = QHBoxLayout()
        phonetic_row.addWidget(QLabel(format_phonetic(phonetic)))
        speak = QPushButton("朗读")
        speak.clicked.connect(lambda: self._speak(word["display"] if word else self.lemma))
        phonetic_row.addWidget(speak)
        phonetic_row.addStretch(1)
        layout.addLayout(phonetic_row)
        if word:
            senses = ctx.store.senses_of(word["id"])
            state = ctx.store.load_state(word["id"])
            layout.addWidget(QLabel(f"当前状态：{STATUS_LABELS.get(state.status, state.status)}"))
        else:
            senses = []
            layout.addWidget(QLabel("这个词还没有收入词库。"))
        if senses:
            for sense in senses:
                pos = f"{sense['pos']}. " if sense["pos"] else ""
                layout.addWidget(QLabel(pos + sense["gloss_zh"]))
        elif entry and entry.senses:
            for sense in entry.senses:
                pos = f"{sense.pos}. " if sense.pos else ""
                layout.addWidget(QLabel("词典：" + pos + sense.gloss_zh))
        else:
            layout.addWidget(QLabel("待补充：没有可靠释义。"))
        if word:
            examples = ctx.store.examples_of(word["id"], document_id)
            if examples:
                sample = QLabel(examples[0]["sentence"])
                sample.setWordWrap(True)
                layout.addWidget(sample)
        buttons = QHBoxLayout()
        learn = QPushButton("加入生词本")
        known = QPushButton("加入熟词本")
        learn.clicked.connect(lambda: self._move("learning"))
        known.clicked.connect(lambda: self._move("mastered"))
        buttons.addWidget(learn)
        buttons.addWidget(known)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _speak(self, text: str) -> None:
        ok, message = self.ctx.speech.speak(text)
        if not ok:
            tell(self, message, "warn")

    def _move(self, status: str) -> None:
        from wordflow.vocab import move_words

        word = self.ctx.store.get_word_by_lemma(self.lemma)
        if word is None:
            try:
                add_manual_word(
                    self.ctx.store,
                    self.ctx.dictionary,
                    text=self.lemma,
                    status=status,
                    keep_dictionary_senses=True,
                )
            except ValueError as exc:
                tell(self, str(exc), "warn")
                return
        else:
            move_words(self.ctx.store, [word["id"]], status)
        self.accept()
