"""界面上反复用到的小组件。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from wordflow.constants import STATUS_LABELS


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#004EA1"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(30)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "词")
    painter.end()
    return QIcon(pixmap)


def nav_icon(kind: str, off: str, on: str) -> QIcon:
    """侧栏小图标。选中和未选中用不同颜色，避免整条导航只剩文字。"""
    icon = QIcon()
    for state, paint in (
        (QIcon.State.Off, off),
        (QIcon.State.On, on),
    ):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(paint))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        _draw_nav(painter, kind, QColor(paint))
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
        icon.addPixmap(pixmap, QIcon.Mode.Active, state)
        icon.addPixmap(pixmap, QIcon.Mode.Selected, state)
    return icon


def _draw_nav(painter: QPainter, kind: str, color: QColor) -> None:
    if kind == "home":
        painter.drawPolyline([QPointF(3, 9), QPointF(10, 3), QPointF(17, 9)])
        painter.drawRoundedRect(QRectF(5.5, 9, 9, 8), 1.4, 1.4)
    elif kind == "plans":
        painter.drawRoundedRect(QRectF(3.5, 4.5, 13, 12), 2, 2)
        painter.drawLine(QPointF(3.5, 8.5), QPointF(16.5, 8.5))
        painter.drawLine(QPointF(7, 3), QPointF(7, 6.5))
        painter.drawLine(QPointF(13, 3), QPointF(13, 6.5))
    elif kind == "placement":
        painter.drawRoundedRect(QRectF(3, 3, 14, 14), 3, 3)
        painter.drawPolyline([QPointF(6, 10), QPointF(9, 13), QPointF(14.5, 6.5)])
    elif kind == "learn":
        painter.drawRoundedRect(QRectF(3, 3, 14, 14), 3, 3)
        painter.drawPolyline([QPointF(7, 13), QPointF(10, 6), QPointF(13, 13)])
        painter.drawLine(QPointF(8.2, 10.5), QPointF(11.8, 10.5))
    elif kind == "review":
        painter.drawEllipse(QRectF(3, 3, 14, 14))
        painter.drawPolyline([QPointF(10, 6.5), QPointF(10, 10.5), QPointF(13, 12.5)])
    elif kind == "import":
        painter.drawPolyline([QPointF(10, 3), QPointF(10, 12), QPointF(6.5, 8.5)])
        painter.drawLine(QPointF(10, 12), QPointF(13.5, 8.5))
        painter.drawLine(QPointF(4, 16), QPointF(16, 16))
    elif kind == "articles":
        painter.drawRoundedRect(QRectF(4, 2.5, 12, 15), 2, 2)
        painter.drawLine(QPointF(7, 7), QPointF(13, 7))
        painter.drawLine(QPointF(7, 10), QPointF(13, 10))
        painter.drawLine(QPointF(7, 13), QPointF(11, 13))
    elif kind == "listen":
        painter.drawPolygon([QPointF(3, 8), QPointF(7, 8), QPointF(12, 4), QPointF(12, 16), QPointF(7, 12), QPointF(3, 12)])
        painter.drawArc(QRectF(11, 6, 6, 8), -50 * 16, 100 * 16)
    elif kind == "learning":
        painter.drawRoundedRect(QRectF(3, 3, 14, 14), 2, 2)
        painter.drawLine(QPointF(6, 7.5), QPointF(14, 7.5))
        painter.drawLine(QPointF(6, 10.5), QPointF(14, 10.5))
        painter.drawLine(QPointF(6, 13.5), QPointF(11, 13.5))
    elif kind == "mastered":
        painter.drawEllipse(QRectF(3, 3, 14, 14))
        painter.drawPolyline([QPointF(6, 10), QPointF(9, 13), QPointF(14.5, 6.5)])
    elif kind == "mistakes":
        painter.drawEllipse(QRectF(3, 3, 14, 14))
        painter.drawLine(QPointF(7, 7), QPointF(13, 13))
        painter.drawLine(QPointF(13, 7), QPointF(7, 13))
    elif kind == "stats":
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(3.5, 11, 3.2, 5), 1, 1)
        painter.drawRoundedRect(QRectF(8.4, 6, 3.2, 10), 1, 1)
        painter.drawRoundedRect(QRectF(13.3, 8.5, 3.2, 7.5), 1, 1)
    elif kind == "assistant":
        painter.drawRoundedRect(QRectF(2.5, 3, 15, 10), 3, 3)
        painter.drawPolyline([QPointF(7, 13), QPointF(6, 17), QPointF(11, 13)])
    else:
        painter.drawLine(QPointF(4, 6), QPointF(16, 6))
        painter.drawLine(QPointF(4, 10), QPointF(16, 10))
        painter.drawLine(QPointF(4, 14), QPointF(16, 14))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(6, 4.4, 3.4, 3.4))
        painter.drawEllipse(QRectF(11, 8.4, 3.4, 3.4))
        painter.drawEllipse(QRectF(7.5, 12.4, 3.4, 3.4))


def format_phonetic(value: str | None) -> str:
    if not value or not str(value).strip():
        return "暂无音标"
    text = str(value).strip()
    if text.startswith("/") or text.startswith("["):
        return text
    return f"/{text}/"


def status_text(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "")


def fill_study_plan_combo(combo, store, current_id=None, all_label: str = "全部") -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(all_label, None)
    for plan in store.list_study_plans():
        combo.addItem(plan["title"], plan["id"])
    if current_id is not None:
        index = combo.findData(current_id)
        if index >= 0:
            combo.setCurrentIndex(index)
    combo.blockSignals(False)


def page_header(title: str, subtitle: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
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
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return frame, layout


def stat_card(caption: str, accent: bool = False) -> tuple[QFrame, QLabel]:
    frame, layout = card()
    frame.setObjectName("statCard")
    frame.setProperty("accent", "true" if accent else "false")
    label = QLabel(caption)
    label.setObjectName("muted")
    value = QLabel("—")
    value.setObjectName("statValue")
    layout.addWidget(label)
    layout.addWidget(value)
    return frame, value


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


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
