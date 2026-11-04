"""界面上反复用到的小组件。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from wordflow.constants import STATUS_LABELS


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#2563EB"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, 64, 64, 16, 16)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(34)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "W")
    painter.end()
    return QIcon(pixmap)


def format_phonetic(value: str | None) -> str:
    if not value or not str(value).strip():
        return "暂无音标"
    text = str(value).strip()
    if text.startswith("/") or text.startswith("["):
        return text
    return f"/{text}/"


def status_text(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "")


def page_header(title: str, subtitle: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    layout.addWidget(heading)
    if subtitle:
        note = QLabel(subtitle)
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        layout.addWidget(note)
    return box


def card(parent=None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


def stat_card(caption: str) -> tuple[QFrame, QLabel]:
    frame, layout = card()
    label = QLabel(caption)
    label.setObjectName("muted")
    value = QLabel("—")
    value.setObjectName("statValue")
    layout.addWidget(label)
    layout.addWidget(value)
    return frame, value


def row(widgets: list[QWidget], stretch_last: bool = False) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch_last:
        layout.addStretch(1)
    return host


def tell(parent, text: str, kind: str = "info") -> None:
    if kind == "warn":
        QMessageBox.warning(parent, "WordFlow", text)
    elif kind == "error":
        QMessageBox.critical(parent, "WordFlow", text)
    else:
        QMessageBox.information(parent, "WordFlow", text)


def confirm(parent, text: str) -> bool:
    answer = QMessageBox.question(parent, "WordFlow", text, QMessageBox.Yes | QMessageBox.No)
    return answer == QMessageBox.Yes


def mark_button(button, state: str) -> None:
    button.setProperty("state", state)
    button.style().unpolish(button)
    button.style().polish(button)
