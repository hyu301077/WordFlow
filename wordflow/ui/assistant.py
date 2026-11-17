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
    client_from_settings,
    confusion_prompt,
    example_prompt,
    explain_prompt,
    mnemonic_prompt,
    plan_prompt,
    reading_prompt,
)
from wordflow.talk_clips import TalkResult, build_talk
from wordflow.ui.common import card, page_header, tell
from wordflow.ui.workers import CallWorker


class AssistantPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.worker: CallWorker | None = None
        self.pending: dict | None = None
        self.talk_folder: Path | None = None
        self.close_after_talk = False
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

    def _talk_card(self) -> QWidget:
        frame, body = card()
        body.addWidget(page_header("视频文案", "在本机识别英语音视频，按完整句子剪出 MP3，并生成英文稿。"))
        self.talk_path = QLineEdit()
        self.talk_path.setReadOnly(True)
        self.talk_path.setAccessibleName("所选音视频文件")
        self.talk_path.setPlaceholderText("还没有选择文件")
        pick = QPushButton("选择音视频")
        pick.clicked.connect(self._pick_talk)
        path_row = QHBoxLayout()
        path_row.addWidget(pick)
        path_row.addWidget(self.talk_path, 1)
        body.addLayout(path_row)
        self.talk_name = QLineEdit()
        self.talk_name.setAccessibleName("结果文件夹名称")
        self.talk_name.setPlaceholderText("结果文件夹名称，可以留空")
        self.talk_model = QComboBox()
        self.talk_model.setAccessibleName("英文识别模型")
        self.talk_model.addItem("小模型，较快", "small")
        self.talk_model.addItem("中模型，更准", "medium")
        name_row = QHBoxLayout()
        name_row.addWidget(self.talk_name, 1)
        name_row.addWidget(self.talk_model)
        body.addLayout(name_row)
        self.talk_translate = QCheckBox("将本次识别出的英文发给已配置的在线助手生成中文参考译文")
        body.addWidget(self.talk_translate)
        self.talk_start = QPushButton("开始整理")
        self.talk_start.clicked.connect(self._start_talk)
        self.talk_cancel = QPushButton("取消")
        self.talk_cancel.clicked.connect(self._cancel_talk)
        self.talk_open = QPushButton("打开结果")
        self.talk_open.clicked.connect(self._open_talk_folder)
        self.talk_listen = QPushButton("送到语音朗读")
        self.talk_listen.clicked.connect(self._open_talk_listen)
        actions = QHBoxLayout()
        for button in (self.talk_start, self.talk_cancel, self.talk_open, self.talk_listen):
            button.setEnabled(False)
            actions.addWidget(button)
        body.addLayout(actions)
        self.talk_status = QLabel("首次识别需联网下载模型。")
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
        self.base_url.setText(self.ctx.settings.get("ai_base_url", ""))
        self.model.setText(self.ctx.settings.get("ai_model", ""))
        self.api_key.setText(self.ctx.settings.get("ai_api_key", ""))
        index = self.talk_model.findData(self.ctx.settings.get("talk_model", "small"))
        self.talk_model.setCurrentIndex(max(index, 0))
        self._reload_history()

    def _save_flags(self) -> None:
        self.ctx.settings.set("ai_enabled", int(self.enabled.isChecked()))
        self.ctx.settings.set("ai_consent", int(self.consent.isChecked()))

    def _save_connection(self) -> None:
        self.ctx.settings.set("ai_base_url", self.base_url.text().strip())
        self.ctx.settings.set("ai_model", self.model.text().strip())
        self.ctx.settings.set("ai_api_key", self.api_key.text().strip())

    def _run(self, kind: str) -> None:
        if self.talk_cancel.isEnabled() or (self.worker and self.worker.isRunning()):
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
            self.talk_path.text() or str(Path.home()),
            "视频和音频 (*.mp4 *.mkv *.mov *.webm *.mp3 *.wav *.m4a *.aac *.flac);;所有文件 (*.*)",
        )
        if chosen:
            self.talk_path.setText(chosen)
            self.talk_start.setEnabled(not self.talk_cancel.isEnabled())

    def _start_talk(self) -> None:
        if self.worker and self.worker.isRunning():
            tell(self, "上一个请求还没结束。", "warn")
            return
        source = Path(self.talk_path.text())
        folder_name = self.talk_name.text().strip()
        model_size = self.talk_model.currentData()
        client = None
        if self.talk_translate.isChecked():
            self._save_flags()
            self._save_connection()
            try:
                client = client_from_settings(self.ctx.settings)
            except AIError as exc:
                self.talk_status.setText(str(exc))
                return
        self.ctx.settings.set("talk_model", model_size)
        self.talk_translate.setChecked(False)
        self.pending = {"kind": "talk", "preview": str(source), "model": client.model if client else "local"}
        self.talk_start.setEnabled(False)
        self.talk_cancel.setEnabled(True)
        self.talk_status.setText("正在整理音视频。")
        data_dir = self.ctx.data_dir

        def job(worker):
            return build_talk(
                source, data_dir / "talks", folder_name, model_size, data_dir / "models",
                client=client,
                progress=lambda message: worker.progress.emit(0, 0, message),
                cancelled=worker.cancelled,
            )

        self.worker = CallWorker(job, self)
        self.worker.progress.connect(self._talk_progress)
        self.worker.succeeded.connect(self._talk_done)
        self.worker.failed.connect(self.talk_status.setText)
        self.worker.finished.connect(self._talk_finished)
        self.worker.start()

    def _talk_progress(self, _done: int, _total: int, message: str) -> None:
        if not self.worker.cancelled():
            self.talk_status.setText(message)

    def _cancel_talk(self) -> None:
        self.worker.cancel()
        self.talk_status.setText("正在取消，当前处理步骤结束后停止。")

    def cancel_talk_on_close(self) -> bool:
        if self.talk_cancel.isEnabled():
            self.close_after_talk = True
            self._cancel_talk()
        return self.close_after_talk

    def _talk_finished(self) -> None:
        self.talk_cancel.setEnabled(False)
        self.talk_start.setEnabled(True)
        if self.close_after_talk:
            self.close_after_talk = False
            self.navigator.close()

    def _talk_done(self, result: TalkResult) -> None:
        self.talk_folder = result.folder
        self.talk_open.setEnabled(True)
        self.talk_listen.setEnabled(True)
        chinese = "已生成参考译文" if result.translated else "中文标为「待补充」"
        summary = f"已生成 {result.clips} 段 MP3，合并 {result.merged} 段短片段。{chinese}。\n{result.folder}"
        if result.warning:
            summary += f"\n{result.warning}"
        self.talk_status.setText(summary)
        self.ctx.store.add_ai_record(
            kind="talk", title=result.folder.name, preview=self.pending["preview"],
            content=summary, model=self.pending["model"] if result.translated else "local",
        )
        self._reload_history()

    def _open_talk_folder(self) -> None:
        try:
            os.startfile(self.talk_folder)
        except OSError as exc:
            tell(self, f"无法打开结果文件夹。{exc}", "warn")

    def _open_talk_listen(self) -> None:
        folder = self.talk_folder / "sentences_by_sentence"
        if folder.is_dir():
            self.navigator.open_listen(folder)
        else:
            tell(self, "结果文件夹已移动或删除。", "warn")

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
        if record["kind"] == "talk":
            self.output.setPlainText(record["content"])
            return
        self.output.setPlainText(
            "以下内容由在线模型生成，只供参考，没有写入释义，也不会作为测验答案。\n\n" + record["content"]
        )

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.wait(1500)
