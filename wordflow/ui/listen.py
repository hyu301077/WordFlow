"""选择文件夹，列出其中的 MP3 并按倍速朗读。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QSize, Qt, QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from wordflow.listen import list_clips
from wordflow.playback import ClipPlayer, device_key
from wordflow.ui.common import page_header

RATES = (0.5, 0.75, 1.0, 1.5, 2.0)


class SentenceDelegate(QStyledItemDelegate):
    """句子列按单元格宽度换行，不省略后面的单词。"""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = Qt.ElideNone
        option.features |= QStyleOptionViewItem.ViewItemFeature.WrapText

    def sizeHint(self, option, index) -> QSize:
        self.initStyleOption(option, index)
        text = option.text or ""
        if not text:
            return super().sizeHint(option, index)
        width = 240
        view = self.parent()
        if isinstance(view, QTableView):
            column_width = view.columnWidth(index.column())
            if column_width > 40:
                width = column_width
        width = max(40, width - 16)
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setPlainText(text)
        document.setTextWidth(width)
        return QSize(int(width), int(document.size().height()) + 12)


class ClipModel(QAbstractTableModel):
    HEADERS = ["文件", "句子", "时长"]

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
        duration = row.get("duration")
        values = [
            row["name"],
            row.get("text") or "",
            _clock(int(duration * 1000)) if isinstance(duration, (int, float)) else "",
        ]
        return values[index.column()]


class ListenPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        self.folder: Path | None = None
        self.current = -1
        self.rate = 1.0
        self._sliding = False
        self._restored = False
        self._advancing = False
        layout = QVBoxLayout(self)
        layout.addWidget(page_header("语音朗读", "选择包含 MP3 的文件夹，点击列表里的句子开始播放。"))
        picker = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("还没有选择文件夹")
        choose = QPushButton("选择文件夹")
        choose.clicked.connect(self._choose)
        refresh = QPushButton("重新检索")
        refresh.clicked.connect(self._refresh)
        picker.addWidget(self.folder_edit, 1)
        picker.addWidget(choose)
        picker.addWidget(refresh)
        layout.addLayout(picker)
        player = QFrame()
        player.setObjectName("player")
        player_layout = QVBoxLayout(player)
        player_layout.setContentsMargins(22, 18, 22, 18)
        player_layout.setSpacing(12)
        self.status = QLabel("选择文件夹后，这里会列出检索到的 MP3。")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        player_layout.addWidget(self.status)
        speeds = QHBoxLayout()
        speeds.addWidget(QLabel("倍速"))
        self.rate_group = QButtonGroup(self)
        self.rate_group.setExclusive(True)
        self.rate_buttons: dict[float, QPushButton] = {}
        for rate in RATES:
            button = QPushButton(f"{rate:g}×")
            button.setObjectName("speedButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=rate: self._set_rate(value))
            self.rate_group.addButton(button)
            self.rate_buttons[rate] = button
            speeds.addWidget(button)
        speeds.addStretch(1)
        device_row = QHBoxLayout()
        device_label = QLabel("播放设备")
        self.device = QComboBox()
        self.device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.device.setMinimumContentsLength(8)
        self.device.currentIndexChanged.connect(self._device_changed)
        self.device.currentTextChanged.connect(self.device.setToolTip)
        device_label.setBuddy(self.device)
        device_row.addWidget(device_label)
        device_row.addWidget(self.device, 1)
        self.playback_options = QBoxLayout(QBoxLayout.TopToBottom)
        self.playback_options.addLayout(speeds)
        self.playback_options.addLayout(device_row, 1)
        player_layout.addLayout(self.playback_options)
        transport = QHBoxLayout()
        previous = QPushButton("上一句")
        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("primary")
        next_button = QPushButton("下一句")
        stop = QPushButton("停止")
        previous.clicked.connect(self._previous)
        self.play_button.clicked.connect(self._toggle)
        next_button.clicked.connect(self._next)
        stop.clicked.connect(self._stop)
        self.auto_next = QCheckBox("播完继续下一句")
        self.auto_next.setChecked(True)
        self.auto_next.toggled.connect(self._auto_toggled)
        self.loop = QCheckBox("循环当前")
        self.loop.toggled.connect(self._loop_toggled)
        transport.addWidget(previous)
        transport.addWidget(self.play_button)
        transport.addWidget(next_button)
        transport.addWidget(stop)
        transport.addStretch(1)
        player_layout.addLayout(transport)
        modes = QHBoxLayout()
        modes.addWidget(self.auto_next)
        modes.addWidget(self.loop)
        modes.addStretch(1)
        player_layout.addLayout(modes)
        self.now = QLabel("还没有开始朗读。")
        self.now.setWordWrap(True)
        self.now.setObjectName("muted")
        player_layout.addWidget(self.now)
        self.sentence = QLabel("选择一行后，这里显示完整英文句子。")
        self.sentence.setObjectName("listenSentence")
        self.sentence.setWordWrap(True)
        self.sentence.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sentence_font = self.sentence.font()
        sentence_font.setPointSize(sentence_font.pointSize() + 3)
        self.sentence.setFont(sentence_font)
        player_layout.addWidget(self.sentence)
        progress = QHBoxLayout()
        self.elapsed = QLabel("0:00")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.total = QLabel("0:00")
        progress.addWidget(self.elapsed)
        progress.addWidget(self.slider, 1)
        progress.addWidget(self.total)
        player_layout.addLayout(progress)
        layout.addWidget(player)
        self.model = ClipModel()
        self.view = QTableView()
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        self.view.setSelectionMode(QTableView.SingleSelection)
        self.view.setWordWrap(True)
        self.view.setTextElideMode(Qt.ElideNone)
        self.view.setItemDelegateForColumn(1, SentenceDelegate(self.view))
        self.view.verticalHeader().setVisible(False)
        header = self.view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        header.sectionResized.connect(lambda *_args: self.view.resizeRowsToContents())
        self.view.clicked.connect(self._clicked)
        self.view.setMinimumHeight(180)
        layout.addWidget(self.view, 1)
        self.player = ClipPlayer(self)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(self._duration)
        self.player.stateChanged.connect(self._state)
        self.player.failed.connect(self._error)
        self.player.finished.connect(self._finished)
        self._fill_devices()
        self._restore_rate()
        if self.ctx.settings.flag("listen_loop"):
            self.loop.setChecked(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        direction = QBoxLayout.LeftToRight if event.size().width() >= 840 else QBoxLayout.TopToBottom
        self.playback_options.setDirection(direction)
        text = self.sentence.text()
        width = self.sentence.width()
        if width < 80 or not text:
            return
        height = self.sentence.heightForWidth(width)
        if height > 0 and abs(self.sentence.minimumHeight() - height) > 2:
            self.sentence.setMinimumHeight(height)

    def on_show(self) -> None:
        self._fill_devices()
        if self._restored:
            return
        self._restored = True
        saved = self.ctx.settings.get("listen_folder", "")
        if saved and Path(saved).is_dir():
            self.scan(Path(saved))

    def _choose(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择要检索的文件夹", start)
        if chosen:
            self.open_folder(Path(chosen))

    def open_folder(self, folder: Path) -> None:
        self._restored = True
        self.ctx.settings.set("listen_folder", str(folder))
        self._stop()
        self.scan(folder)

    def _refresh(self) -> None:
        if self.folder:
            self.scan(self.folder)

    def scan(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.folder_edit.setText(str(self.folder))
        rows = list_clips(self.folder)
        self.model.set_rows(rows)
        self.current = -1
        if rows:
            self.status.setText(f"检索到 {len(rows)} 个 MP3。点击一行开始朗读。")
        else:
            self.status.setText("这个文件夹里没有找到 MP3。")
        self.now.setText("还没有开始朗读。")
        self._show_sentence("选择一行后，这里显示完整英文句子。")
        QTimer.singleShot(0, self.view.resizeRowsToContents)

    def _clicked(self, index) -> None:
        if index.isValid():
            self.play_row(index.row())

    def play_row(self, row: int) -> None:
        if row < 0 or row >= len(self.model.rows):
            return
        item = self.model.rows[row]
        self.current = row
        self.view.selectRow(row)
        self.view.scrollTo(self.model.index(row, 0))
        self._apply_rate()
        self.player.play_file(str(item["path"]))
        text = (item.get("text") or "").strip()
        device_name = self.device.currentText() or "默认设备"
        self.now.setText(f"正在用「{device_name}」朗读：{item['name']}")
        self._show_sentence(text or "这个音频没有配套英文句子。")

    def _toggle(self) -> None:
        if self.player._playing:
            self.player.pause()
            return
        if self.player._paused:
            self.player.resume()
            return
        if self.current >= 0:
            self.play_row(self.current)
        elif self.model.rows:
            self.play_row(0)

    def _previous(self) -> None:
        if not self.model.rows:
            return
        row = self.current - 1 if self.current > 0 else 0
        self.play_row(row)

    def _next(self) -> None:
        if not self.model.rows:
            return
        row = self.current + 1 if self.current >= 0 else 0
        if row >= len(self.model.rows):
            return
        self.play_row(row)

    def _stop(self) -> None:
        self.player.stop()
        self.play_button.setText("播放")

    def _show_sentence(self, text: str) -> None:
        self.sentence.setText(text)
        width = self.sentence.width()
        if width < 80:
            return
        height = self.sentence.heightForWidth(width)
        if height > 0:
            self.sentence.setMinimumHeight(height)

    def _loop_toggled(self, checked: bool) -> None:
        self.ctx.settings.set("listen_loop", "1" if checked else "0")
        if checked and self.auto_next.isChecked():
            self.auto_next.blockSignals(True)
            self.auto_next.setChecked(False)
            self.auto_next.blockSignals(False)

    def _auto_toggled(self, checked: bool) -> None:
        if checked and self.loop.isChecked():
            self.loop.blockSignals(True)
            self.loop.setChecked(False)
            self.loop.blockSignals(False)
            self.ctx.settings.set("listen_loop", "0")

    def _set_rate(self, rate: float) -> None:
        self.rate = rate
        self.ctx.settings.set("listen_rate", f"{rate:g}")
        self._apply_rate()
        button = self.rate_buttons.get(rate)
        if button:
            button.setChecked(True)

    def _restore_rate(self) -> None:
        rate = self.ctx.settings.real("listen_rate", 1.0)
        if not any(abs(rate - item) < 0.001 for item in RATES):
            rate = 1.0
        self._set_rate(rate)

    def _apply_rate(self) -> None:
        self.player.set_rate(self.rate)

    def _fill_devices(self) -> None:
        current = self.device.currentData()
        saved = current or self.ctx.settings.get("listen_device", "")
        self.device.blockSignals(True)
        self.device.clear()
        chosen = None
        for item in QMediaDevices.audioOutputs():
            key = device_key(item)
            self.device.addItem(item.description(), key)
            if key and key == saved:
                chosen = key
            elif chosen is None and item.isDefault():
                chosen = key
        if chosen:
            index = self.device.findData(chosen)
            if index >= 0:
                self.device.setCurrentIndex(index)
        self.device.blockSignals(False)
        self._use_device()

    def _device_changed(self) -> None:
        key = self.device.currentData()
        if key:
            self.ctx.settings.set("listen_device", key)
        self._use_device()

    def _use_device(self) -> None:
        key = self.device.currentData()
        for item in QMediaDevices.audioOutputs():
            if device_key(item) == key:
                self.player.set_output(item)
                return

    def _state(self, state: str) -> None:
        self.play_button.setText("暂停" if state == "playing" else "播放")

    def _finished(self) -> None:
        if self.loop.isChecked() and 0 <= self.current < len(self.model.rows):
            if self.player.replay():
                return
            self.play_row(self.current)
            return
        if self.auto_next.isChecked() and not self._advancing:
            self._advancing = True
            try:
                self._next()
            finally:
                self._advancing = False

    def _position(self, position: int) -> None:
        if not self._sliding:
            self.slider.setValue(int(position))
        self.elapsed.setText(_clock(int(position)))

    def _duration(self, duration: int) -> None:
        self.slider.setRange(0, max(0, int(duration)))
        self.total.setText(_clock(int(duration)))

    def _slider_pressed(self) -> None:
        self._sliding = True

    def _slider_released(self) -> None:
        self._sliding = False
        self.player.seek(self.slider.value())

    def _error(self, message: str) -> None:
        if message:
            self.status.setText(message)


def _clock(milliseconds: int) -> str:
    total = max(0, milliseconds) // 1000
    return f"{total // 60}:{total % 60:02d}"
