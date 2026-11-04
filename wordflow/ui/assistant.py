"""可选在线助手。请求只在用户点击后发出，结果不进入词典和测验。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wordflow.ai import (
    AIError,
    client_from_settings,
    confusion_prompt,
    example_prompt,
    explain_prompt,
    mnemonic_prompt,
    plan_prompt,
    reading_prompt,
)
from wordflow.ui.common import page_header, tell
from wordflow.ui.workers import CallWorker


class AssistantPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.worker: CallWorker | None = None
        self.pending: dict | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            page_header(
                "在线助手",
                "默认关闭。只有你点击下面的按钮时，才会把当前单词、例句或学习数量发到你自己填写的服务。"
                "生成内容只供参考，不会变成词典释义，也不会当作测验答案。",
            )
        )
        self.enabled = QCheckBox("启用在线助手")
        self.consent = QCheckBox("我确认允许发送本次所选的单词、例句或学习数量。不会自动上传本地文档。")
        self.enabled.toggled.connect(self._save_flags)
        self.consent.toggled.connect(self._save_flags)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("http://127.0.0.1:11434/v1 或兼容 OpenAI 的地址")
        self.model = QLineEdit()
        self.model.setPlaceholderText("模型名称，例如 llama3.1 或 deepseek-chat")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("API 密钥。本地服务不需要时可以留空")
        for box in (self.base_url, self.model, self.api_key):
            box.editingFinished.connect(self._save_connection)
        layout.addWidget(self.enabled)
        layout.addWidget(self.consent)
        layout.addWidget(self.base_url)
        layout.addWidget(self.model)
        layout.addWidget(self.api_key)
        ping = QPushButton("测试连接")
        ping.clicked.connect(lambda: self._run("ping"))
        layout.addWidget(ping)
        form = QHBoxLayout()
        self.lemma = QLineEdit()
        self.lemma.setPlaceholderText("单词")
        self.sentence = QLineEdit()
        self.sentence.setPlaceholderText("这个词所在的英文句子")
        form.addWidget(self.lemma)
        form.addWidget(self.sentence, 1)
        layout.addLayout(form)
        actions = QHBoxLayout()
        for label, kind in (
            ("解释句中词义", "explain"),
            ("记忆提示", "mnemonic"),
            ("生成例句", "example"),
            ("分析错词", "confusion"),
            ("生成短文", "reading"),
            ("一周安排", "plan"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=kind: self._run(name))
            actions.addWidget(button)
        layout.addLayout(actions)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("这里显示模型返回的参考内容。")
        layout.addWidget(self.output, 1)
        self.history = QListWidget()
        self.history.setMinimumHeight(96)
        self.history.currentRowChanged.connect(self._show_history)
        layout.addWidget(QLabel("最近的参考记录"))
        layout.addWidget(self.history, 1)
        self.records: list[dict] = []

    def on_show(self) -> None:
        self.enabled.blockSignals(True)
        self.consent.blockSignals(True)
        self.enabled.setChecked(self.ctx.settings.flag("ai_enabled"))
        self.consent.setChecked(self.ctx.settings.flag("ai_consent"))
        self.enabled.blockSignals(False)
        self.consent.blockSignals(False)
        self.base_url.setText(self.ctx.settings.get("ai_base_url", ""))
        self.model.setText(self.ctx.settings.get("ai_model", ""))
        self.api_key.setText(self.ctx.settings.get("ai_api_key", ""))
        self._reload_history()

    def _save_flags(self) -> None:
        self.ctx.settings.set("ai_enabled", int(self.enabled.isChecked()))
        self.ctx.settings.set("ai_consent", int(self.consent.isChecked()))

    def _save_connection(self) -> None:
        self.ctx.settings.set("ai_base_url", self.base_url.text().strip())
        self.ctx.settings.set("ai_model", self.model.text().strip())
        self.ctx.settings.set("ai_api_key", self.api_key.text().strip())

    def _run(self, kind: str) -> None:
        if self.worker and self.worker.isRunning():
            tell(self, "上一个请求还没结束。", "warn")
            return
        self._save_flags()
        self._save_connection()
        try:
            client = client_from_settings(self.ctx.settings)
            prepared = self._prepare(kind)
        except AIError as exc:
            tell(self, str(exc), "warn")
            return
        self.pending = prepared
        self.output.setPlainText("正在请求模型…")

        def job(_worker):
            return client.complete(prepared["system"], prepared["user"])

        self.worker = CallWorker(job, self)
        self.worker.succeeded.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _prepare(self, kind: str) -> dict:
        lemma = self.lemma.text().strip()
        sentence = self.sentence.text().strip()
        gloss = self._gloss(lemma)
        word = self.ctx.store.get_word_by_lemma(lemma) if lemma else None
        word_id = word["id"] if word else None
        if kind == "ping":
            system, user = "你是连接测试。", "只回复 OK。"
            title, preview = "连接测试", "OK"
        elif kind == "explain":
            system, user = explain_prompt(lemma, sentence, gloss)
            title, preview = lemma, sentence
        elif kind == "mnemonic":
            system, user = mnemonic_prompt(lemma, gloss)
            title, preview = lemma, gloss
        elif kind == "example":
            system, user = example_prompt(lemma, gloss)
            title, preview = lemma, gloss
        elif kind == "confusion":
            rows = self.ctx.store.top_wrong(12)
            system, user = confusion_prompt(rows)
            title, preview = "错词对照", "、".join(row["lemma"] for row in rows[:12])
            word_id = None
        elif kind == "reading":
            learning, _total = self.ctx.store.list_words(statuses=("learning", "reviewing"), sort="freq", limit=20)
            known, _known_total = self.ctx.store.list_words(statuses=("mastered",), sort="alpha", limit=16)
            learning = [row for row in learning if row.get("gloss")]
            system, user = reading_prompt(learning, known)
            title, preview = "短文", "、".join(row["lemma"] for row in learning[:12])
            word_id = None
        elif kind == "plan":
            data = self.ctx.store.dashboard(self.ctx.settings.integer("daily_new_limit", 20))
            counts = data["counts"]
            system, user = plan_prompt(
                {
                    "due_total": data["due_total"],
                    "learning": counts["learning"] + counts["reviewing"],
                    "mastered": counts["mastered"],
                    "untested": counts["untested"],
                    "daily_goal": data["daily_goal"],
                    "studied_today": data["studied_today"],
                }
            )
            title, preview = "一周安排", f"到期 {data['due_total']}"
            word_id = None
        else:
            raise AIError("未知的助手功能。")
        return {"kind": kind, "system": system, "user": user, "title": title, "preview": preview, "word_id": word_id}

    def _gloss(self, lemma: str) -> str:
        if not lemma:
            return ""
        word = self.ctx.store.get_word_by_lemma(lemma)
        if word:
            senses = self.ctx.store.senses_of(word["id"])
            if senses:
                return senses[0]["gloss_zh"]
        if self.ctx.dictionary.available:
            entry = self.ctx.dictionary.lookup(lemma)
            if entry and entry.senses:
                return entry.senses[0].gloss_zh
        return ""

    def _done(self, text: str) -> None:
        prepared = self.pending or {}
        notice = "以下内容由在线模型生成，只供参考，没有写入释义，也不会作为测验答案。\n\n"
        self.output.setPlainText(notice + text)
        self.ctx.store.add_ai_record(
            kind=prepared.get("kind", ""),
            title=prepared.get("title", ""),
            preview=prepared.get("preview", ""),
            content=text,
            model=self.ctx.settings.get("ai_model", ""),
            word_id=prepared.get("word_id"),
        )
        self._reload_history()

    def _failed(self, message: str) -> None:
        self.output.clear()
        tell(self, message, "error")

    def _reload_history(self) -> None:
        self.records = self.ctx.store.recent_ai_records(20)
        self.history.blockSignals(True)
        self.history.clear()
        for record in self.records:
            self.history.addItem(f"{record['created_at'][:16]}  {record['title'] or record['kind']}")
        self.history.blockSignals(False)

    def _show_history(self, row: int) -> None:
        if row < 0 or row >= len(self.records):
            return
        record = self.records[row]
        self.output.setPlainText(
            "以下内容由在线模型生成，只供参考，没有写入释义，也不会作为测验答案。\n\n" + record["content"]
        )

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.wait(1500)
