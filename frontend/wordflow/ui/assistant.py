"""可选在线助手。请求只在用户点击后发出，结果不进入词典和测验。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
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
    PRESETS,
    active_model,
    client_from_settings,
    provider_of,
    confusion_prompt,
    example_prompt,
    explain_prompt,
    mnemonic_prompt,
    plan_prompt,
    reading_prompt,
)
from wordflow.paths import user_data_dir
from wordflow.talk_clips import TalkResult, build_talk
from wordflow.ui.common import card, page_header, section_title, tell
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
                "默认关闭。只有你点击按钮时，才会把当前单词、例句、学习数量，或你指定视频的识别文案发到你自己填写的服务。"
                "生成内容只供参考，不会变成词典释义，也不会当作测验答案。",
            )
        )
        self.enabled = QCheckBox("启用在线助手")
        self.consent = QCheckBox("我确认允许发送本次所选的单词、例句、学习数量或视频文案。不会自动上传本地文档。")
        self.enabled.toggled.connect(self._save_flags)
        self.consent.toggled.connect(self._save_flags)
        self.provider = QComboBox()
        for key, preset in PRESETS.items():
            self.provider.addItem(preset.label, key)
        self.provider.addItem("自定义", "custom")
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.provider_hint = QLabel("")
        self.provider_hint.setObjectName("muted")
        self.provider_hint.setWordWrap(True)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("http://127.0.0.1:11434/v1 或兼容 OpenAI 的地址")
        self.model = QLineEdit()
        self.model.setPlaceholderText("模型名称，例如 llama3.1")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("API Key")
        for box in (self.base_url, self.model, self.api_key):
            box.editingFinished.connect(self._save_connection)
        layout.addWidget(self.enabled)
        layout.addWidget(self.consent)
        layout.addWidget(self.provider)
        layout.addWidget(self.provider_hint)
        layout.addWidget(self.api_key)
        layout.addWidget(self.base_url)
        layout.addWidget(self.model)
        self._shown_provider = "deepseek"
        ping = QPushButton("测试连接")
        ping.clicked.connect(lambda: self._run("ping"))
        layout.addWidget(ping)
        layout.addWidget(self._talk_card())
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
        self.talk_source = ""
        self.talk_folder = ""

    def _talk_card(self) -> QWidget:
        frame, body = card()
        body.addWidget(section_title("视频文案"))
        note = QLabel(
            "选择一个本机上的英语视频或音频。程序在这台电脑上识别英文，按完整句子切成 MP3，并写出英文稿。"
            "只有上面的开关都打开时，点击开始才会把识别出的英文发给你的模型来写参考译文；否则中文写「待补充」。"
        )
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        body.addWidget(note)
        pick = QPushButton("选择视频")
        pick.clicked.connect(self._pick_talk)
        self.talk_path = QLineEdit()
        self.talk_path.setReadOnly(True)
        self.talk_path.setPlaceholderText("还没有选择文件")
        path_row = QHBoxLayout()
        path_row.addWidget(pick)
        path_row.addWidget(self.talk_path, 1)
        body.addLayout(path_row)
        self.talk_name = QLineEdit()
        self.talk_name.setPlaceholderText("结果文件夹名称，可以留空")
        self.talk_model = QComboBox()
        self.talk_model.addItem("小模型，较快", "small")
        self.talk_model.addItem("中模型，更准", "medium")
        name_row = QHBoxLayout()
        name_row.addWidget(self.talk_name, 1)
        name_row.addWidget(self.talk_model)
        body.addLayout(name_row)
        start = QPushButton("开始整理")
        start.clicked.connect(self._start_talk)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self._cancel_talk)
        open_folder = QPushButton("打开结果")
        open_folder.clicked.connect(self._open_talk_folder)
        listen = QPushButton("送到语音朗读")
        listen.clicked.connect(self._open_talk_listen)
        actions = QHBoxLayout()
        for button in (start, cancel, open_folder, listen):
            actions.addWidget(button)
        body.addLayout(actions)
        self.talk_status = QLabel("整理完成后，英文稿、中英对照稿和 MP3 会放在本机的 WordFlow 目录里。")
        self.talk_status.setObjectName("muted")
        self.talk_status.setWordWrap(True)
        body.addWidget(self.talk_status)
        return frame

    def on_show(self) -> None:
        self.enabled.blockSignals(True)
        self.consent.blockSignals(True)
        self.enabled.setChecked(self.ctx.settings.flag("ai_enabled"))
        self.consent.setChecked(self.ctx.settings.flag("ai_consent"))
        self.enabled.blockSignals(False)
        self.consent.blockSignals(False)
        provider = provider_of(self.ctx.settings)
        self.provider.blockSignals(True)
        provider_index = self.provider.findData(provider)
        self.provider.setCurrentIndex(provider_index if provider_index >= 0 else 0)
        self.provider.blockSignals(False)
        self._shown_provider = self.provider.currentData()
        self._load_connection(self._shown_provider)
        saved_model = self.ctx.settings.get("talk_model", "small")
        index = self.talk_model.findData(saved_model)
        self.talk_model.setCurrentIndex(index if index >= 0 else 0)
        self._reload_history()

    def _save_flags(self) -> None:
        self.ctx.settings.set("ai_enabled", int(self.enabled.isChecked()))
        self.ctx.settings.set("ai_consent", int(self.consent.isChecked()))

    def _provider_changed(self) -> None:
        self._store_key(self._shown_provider)
        self._shown_provider = self.provider.currentData()
        self.ctx.settings.set("ai_provider", self._shown_provider)
        self._load_connection(self._shown_provider)

    def _load_connection(self, provider: str) -> None:
        custom = provider == "custom"
        self.base_url.setVisible(custom)
        self.model.setVisible(custom)
        self.provider_hint.setVisible(not custom)
        if custom:
            self.base_url.setText(self.ctx.settings.get("ai_base_url", ""))
            self.model.setText(self.ctx.settings.get("ai_model", ""))
            self.api_key.setText(self.ctx.settings.get("ai_api_key", ""))
            self.api_key.setPlaceholderText("API Key。本地服务不需要时可以留空")
            return
        preset = PRESETS[provider]
        self.api_key.setText(self.ctx.settings.get(f"ai_key_{provider}", ""))
        self.api_key.setPlaceholderText("API Key")
        self.provider_hint.setText(f"使用{preset.label}接口，模型 {preset.model}。只需填写 API Key。")

    def _store_key(self, provider: str) -> None:
        key = self.api_key.text().strip()
        if provider == "custom":
            self.ctx.settings.set("ai_api_key", key)
        elif provider in PRESETS:
            self.ctx.settings.set(f"ai_key_{provider}", key)

    def _save_connection(self) -> None:
        provider = self.provider.currentData()
        self.ctx.settings.set("ai_provider", provider)
        self._store_key(provider)
        if provider == "custom":
            self.ctx.settings.set("ai_base_url", self.base_url.text().strip())
            self.ctx.settings.set("ai_model", self.model.text().strip())

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

    def _pick_talk(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self,
            "选择英语视频或音频",
            self.talk_source or str(user_data_dir()),
            "视频和音频 (*.mp4 *.mkv *.mov *.webm *.mp3 *.wav *.m4a *.aac *.flac);;所有文件 (*.*)",
        )
        if not chosen:
            return
        self.talk_source = chosen
        self.talk_path.setText(chosen)

    def _start_talk(self) -> None:
        if self.worker and self.worker.isRunning():
            tell(self, "上一个请求还没结束。", "warn")
            return
        if not self.talk_source:
            tell(self, "请先选择一个本机上的英语视频或音频。", "warn")
            return
        self._save_flags()
        self._save_connection()
        self.ctx.settings.set("talk_model", self.talk_model.currentData() or "small")
        client = None
        if self.ctx.settings.flag("ai_enabled") and self.ctx.settings.flag("ai_consent"):
            try:
                client = client_from_settings(self.ctx.settings)
            except AIError as exc:
                tell(self, str(exc), "warn")
                return
        source = self.talk_source
        folder_name = self.talk_name.text().strip()
        model_size = self.talk_model.currentData() or "small"
        root = user_data_dir() / "talks"
        model_dir = user_data_dir() / "models"
        self.pending = {"kind": "talk", "title": folder_name or source, "preview": source, "word_id": None}
        self.talk_status.setText("正在整理，视频较长时需要一些时间。")

        def job(worker):
            return build_talk(
                source,
                root,
                folder_name,
                model_size,
                model_dir,
                client=client,
                progress=lambda message: worker.progress.emit(0, 0, message),
                cancelled=worker.cancelled,
            )

        self.worker = CallWorker(job, self)
        self.worker.progress.connect(self._talk_progress)
        self.worker.succeeded.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _talk_progress(self, _done: int, _total: int, message: str) -> None:
        if message:
            self.talk_status.setText(message)

    def _cancel_talk(self) -> None:
        if self.worker and self.worker.isRunning() and (self.pending or {}).get("kind") == "talk":
            self.worker.cancel()
            self.talk_status.setText("正在取消。")

    def _open_talk_folder(self) -> None:
        if not self.talk_folder:
            tell(self, "还没有可打开的结果。", "warn")
            return
        os.startfile(self.talk_folder)

    def _open_talk_listen(self) -> None:
        folder = Path(self.talk_folder) / "sentences_by_sentence" if self.talk_folder else None
        if folder is None or not folder.is_dir():
            tell(self, "还没有可朗读的句子音频。", "warn")
            return
        opener = getattr(self.navigator, "open_listen", None)
        if opener:
            opener(folder)

    def _done(self, text) -> None:
        if isinstance(text, TalkResult):
            self._talk_done(text)
            return
        prepared = self.pending or {}
        notice = "以下内容由在线模型生成，只供参考，没有写入释义，也不会作为测验答案。\n\n"
        self.output.setPlainText(notice + text)
        self.ctx.store.add_ai_record(
            kind=prepared.get("kind", ""),
            title=prepared.get("title", ""),
            preview=prepared.get("preview", ""),
            content=text,
            model=active_model(self.ctx.settings),
            word_id=prepared.get("word_id"),
        )
        self._reload_history()

    def _talk_done(self, result: TalkResult) -> None:
        self.talk_folder = str(result.folder)
        chinese = "已生成参考译文" if result.translated else "中文写的是「待补充」"
        summary = (
            f"整理完成：{result.clips} 段句子，合并了 {result.merged} 段过短片段，英文约 {result.english_words} 词，{chinese}。\n"
            f"结果目录：{result.folder}\n"
            "英文稿和中英对照稿在 output 里，MP3 在 sentences_by_sentence 里。"
        )
        if result.warning:
            summary += f"\n{result.warning}"
        self.talk_status.setText(summary)
        self.output.setPlainText(summary)
        self.ctx.store.add_ai_record(
            kind="talk",
            title=result.folder.name,
            preview=self.talk_source,
            content=summary,
            model=active_model(self.ctx.settings) if result.translated else "local",
        )
        self._reload_history()

    def _failed(self, message: str) -> None:
        if (self.pending or {}).get("kind") == "talk":
            self.talk_status.setText(message)
            tell(self, message, "warn" if message.startswith("已取消") else "error")
            return
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
