"""设置、词库、备份和快捷键说明。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QDoubleSpinBox,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wordflow.backup import BackupError, backup_database, maybe_auto_backup, restore_database
from wordflow.timeutil import now_local
from wordflow.ui.common import confirm, page_header, tell
from wordflow.vocab import export_csv, export_json, import_table


class SettingsPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        layout = QVBoxLayout(self)
        layout.addWidget(page_header("设置", "基础学习不需要登录，也不需要联网。"))
        self.theme = QComboBox()
        self.theme.addItem("浅色", "light")
        self.theme.addItem("深色", "dark")
        self.theme.currentIndexChanged.connect(self._theme)
        self.goal = QSpinBox()
        self.goal.setRange(1, 200)
        self.goal.valueChanged.connect(lambda value: self.ctx.settings.set("daily_new_limit", value))
        self.retention = QDoubleSpinBox()
        self.retention.setRange(0.80, 0.95)
        self.retention.setSingleStep(0.01)
        self.retention.setDecimals(2)
        self.retention.valueChanged.connect(lambda value: self.ctx.settings.set("desired_retention", f"{value:.2f}"))
        self.leech = QSpinBox()
        self.leech.setRange(4, 20)
        self.leech.valueChanged.connect(lambda value: self.ctx.settings.set("leech_threshold", value))
        self.auto_speak = QCheckBox("打开题目时自动朗读")
        self.auto_speak.toggled.connect(lambda checked: self.ctx.settings.set("auto_speak", int(checked)))
        self.voice = QComboBox()
        self.voice.currentIndexChanged.connect(self._voice)
        self.rate = QSlider()
        self.rate.setOrientation(Qt.Horizontal)
        self.rate.setRange(-5, 5)
        self.rate.valueChanged.connect(self._speech)
        self.volume = QSlider()
        self.volume.setOrientation(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.valueChanged.connect(self._speech)
        speak = QPushButton("试听 apple")
        speak.clicked.connect(self._speak)
        self.speech_label = QLabel()
        self.speech_label.setWordWrap(True)
        self.stopwords = QCheckBox("过滤常见功能词（a、the、of 等）")
        self.proper = QCheckBox("过滤专有名词")
        self.acronyms = QCheckBox("过滤全大写缩写")
        self.stopwords.toggled.connect(lambda checked: self.ctx.settings.set("filter_stopwords", int(checked)))
        self.proper.toggled.connect(lambda checked: self.ctx.settings.set("filter_proper", int(checked)))
        self.acronyms.toggled.connect(lambda checked: self.ctx.settings.set("filter_acronyms", int(checked)))
        self.reminder = QCheckBox("启动时如果有到期单词，显示提醒")
        self.reminder.toggled.connect(lambda checked: self.ctx.settings.set("reminder", int(checked)))
        layout.addWidget(QLabel("外观"))
        layout.addWidget(self.theme)
        layout.addWidget(QLabel("每天计划学习的新词数量"))
        layout.addWidget(self.goal)
        layout.addWidget(QLabel("希望记住的比例（只影响之后的复习，不会改已经排好的日期）"))
        layout.addWidget(self.retention)
        layout.addWidget(QLabel("遗忘达到几次后标记为多次遗忘"))
        layout.addWidget(self.leech)
        layout.addWidget(self.auto_speak)
        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("英语语音"))
        voice_row.addWidget(self.voice, 1)
        voice_row.addWidget(QLabel("语速"))
        voice_row.addWidget(self.rate)
        voice_row.addWidget(QLabel("音量"))
        voice_row.addWidget(self.volume)
        voice_row.addWidget(speak)
        layout.addLayout(voice_row)
        layout.addWidget(self.speech_label)
        layout.addWidget(self.stopwords)
        layout.addWidget(self.proper)
        layout.addWidget(self.acronyms)
        layout.addWidget(self.reminder)
        layout.addWidget(QLabel(
            "快捷键：1/2/3/4 选择或评分，Space 朗读，Enter 确认或下一题，S 记为生词，F 记为熟词，Esc 退出当前练习。"
            "拼写输入框里按 Space 会输入空格，请用朗读按钮。"
        ))
        self.dict_label = QLabel()
        self.dict_label.setWordWrap(True)
        layout.addWidget(self.dict_label)
        self.data_label = QLabel()
        self.data_label.setWordWrap(True)
        self.data_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.data_label)
        open_dir = QPushButton("打开数据文件夹")
        open_dir.clicked.connect(lambda: os.startfile(self.ctx.data_dir))
        layout.addWidget(open_dir)
        layout.addWidget(QLabel("词库"))
        self.decks = QListWidget()
        layout.addWidget(self.decks)
        deck_row = QHBoxLayout()
        for label, slot in (("新建词库", self._add_deck), ("删除所选词库", self._delete_deck)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            deck_row.addWidget(button)
        deck_row.addStretch(1)
        layout.addLayout(deck_row)
        data_row = QHBoxLayout()
        for label, slot in (
            ("导出 CSV", self._export_csv),
            ("导出 JSON", self._export_json),
            ("导入词表", self._import_table),
            ("立即备份", self._backup),
            ("恢复备份", self._restore),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            data_row.addWidget(button)
        layout.addLayout(data_row)
        layout.addWidget(QLabel("恢复前会先自动另存当前数据库。自动备份每天保留一份，最多 10 份。"))

    def on_show(self) -> None:
        self._set_combo(self.theme, self.ctx.settings.get("theme", "light"))
        self.goal.blockSignals(True)
        self.goal.setValue(self.ctx.settings.integer("daily_new_limit", 20))
        self.goal.blockSignals(False)
        self.retention.blockSignals(True)
        self.retention.setValue(self.ctx.settings.real("desired_retention", 0.9))
        self.retention.blockSignals(False)
        self.leech.blockSignals(True)
        self.leech.setValue(self.ctx.settings.integer("leech_threshold", 8))
        self.leech.blockSignals(False)
        self.auto_speak.setChecked(self.ctx.settings.flag("auto_speak"))
        self.stopwords.setChecked(self.ctx.settings.flag("filter_stopwords"))
        self.proper.setChecked(self.ctx.settings.flag("filter_proper"))
        self.acronyms.setChecked(self.ctx.settings.flag("filter_acronyms"))
        self.reminder.setChecked(self.ctx.settings.flag("reminder"))
        self.rate.blockSignals(True)
        self.volume.blockSignals(True)
        self.rate.setValue(self.ctx.settings.integer("speech_rate", 0))
        self.volume.setValue(self.ctx.settings.integer("speech_volume", 80))
        self.rate.blockSignals(False)
        self.volume.blockSignals(False)
        self.voice.blockSignals(True)
        self.voice.clear()
        for item in self.ctx.speech.english_voices():
            self.voice.addItem(f"{item['name']} ({item['language']})", item["language"])
        if self.voice.count() == 0:
            self.voice.addItem("没有英语语音", "")
        self._set_combo(self.voice, self.ctx.settings.get("voice_pref", "en-US"))
        self.voice.blockSignals(False)
        self.speech_label.setText(self.ctx.speech.error or f"可用英语语音 {self.ctx.speech.english_voices().__len__()} 个。")
        if self.ctx.dictionary.available:
            self.dict_label.setText(
                f"本地词典已加载：{self.ctx.dictionary.entry_count} 个词条。{self.ctx.dictionary.path}"
            )
        else:
            self.dict_label.setText(f"本地词典未加载。{self.ctx.dictionary.error}")
        self.data_label.setText(f"学习数据：{self.ctx.db_path}")
        self.decks.clear()
        for deck in self.ctx.store.list_decks():
            suffix = "（默认）" if deck["is_default"] else ""
            self.decks.addItem(f"{deck['id']}|{deck['name']}{suffix}")

    def _set_combo(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = 0
        combo.setCurrentIndex(index)

    def _theme(self) -> None:
        self.navigator.apply_theme(self.theme.currentData())

    def _voice(self) -> None:
        value = self.voice.currentData()
        if value:
            self.ctx.settings.set("voice_pref", value)
            self.ctx.apply_speech()

    def _speech(self) -> None:
        self.ctx.settings.set("speech_rate", self.rate.value())
        self.ctx.settings.set("speech_volume", self.volume.value())
        self.ctx.apply_speech()

    def _speak(self) -> None:
        self.ctx.apply_speech()
        ok, message = self.ctx.speech.speak("apple")
        if not ok:
            tell(self, message, "warn")

    def _add_deck(self) -> None:
        name, ok = QInputDialog.getText(self, "新建词库", "词库名称")
        if not ok or not name.strip():
            return
        try:
            self.ctx.store.create_deck(name.strip())
        except Exception as exc:
            tell(self, f"没有建成：{exc}", "warn")
            return
        self.on_show()

    def _delete_deck(self) -> None:
        current = self.decks.currentItem()
        if current is None:
            return
        deck_id = int(current.text().split("|", 1)[0])
        if confirm(self, "删除这个词库？单词本身和学习记录都会保留。"):
            self.ctx.store.delete_deck(deck_id)
            self.on_show()

    def _export_csv(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "导出 CSV", "wordflow.csv", "CSV (*.csv)")
        if path:
            rows = self.ctx.store.export_rows()
            export_csv(path, rows)
            tell(self, f"已导出 {len(rows)} 行。")

    def _export_json(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "导出 JSON", "wordflow.json", "JSON (*.json)")
        if path:
            rows = self.ctx.store.export_rows()
            export_json(path, rows)
            tell(self, f"已导出 {len(rows)} 行。")

    def _import_table(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "导入词表", "", "词表 (*.csv *.json)")
        if not path:
            return
        try:
            result = import_table(self.ctx.store, self.ctx.dictionary, path)
        except Exception as exc:
            tell(self, f"导入失败：{exc}", "error")
            return
        tell(self, f"新增 {result['added']}，更新 {result['updated']}，无法识别 {result['invalid']}。")

    def _backup(self) -> None:
        default = str(self.ctx.backup_path / f"wordflow-{now_local().strftime('%Y%m%d-%H%M%S')}.db")
        path, _filter = QFileDialog.getSaveFileName(self, "备份数据库", default, "数据库 (*.db)")
        if not path:
            return
        try:
            backup_database(self.ctx.store, path)
        except BackupError as exc:
            tell(self, str(exc), "error")
            return
        tell(self, f"备份已保存到：\n{path}")

    def _restore(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择备份", str(self.ctx.backup_path), "数据库 (*.db)")
        if not path:
            return
        if not confirm(self, "恢复会替换当前学习数据。开始前会先自动保留一份当前数据。确定继续？"):
            return
        try:
            safety = restore_database(self.ctx.store, path, self.ctx.db_path, self.ctx.backup_path)
        except Exception as exc:
            self.ctx.reopen_store()
            tell(self, f"恢复失败，已尝试回到恢复前的数据。\n{exc}", "error")
            return
        self.ctx.reopen_store()
        self.on_show()
        tell(self, f"已经恢复。恢复前的数据在：\n{safety}")

    def maybe_backup(self) -> None:
        try:
            maybe_auto_backup(self.ctx.store, self.ctx.backup_path)
        except Exception:
            pass
