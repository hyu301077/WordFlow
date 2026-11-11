"""不依赖额外图表库的学习趋势图。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels: list[str] = []
        self.values: list[float] = []
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_series(self, labels: list[str], values: list[float]) -> None:
        self.labels = labels
        self.values = values
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.values:
            painter.setPen(self.palette().color(self.palette().ColorRole.PlaceholderText))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无数据")
            return
        rect = self.rect().adjusted(8, 12, -8, -24)
        maximum = max(self.values) or 1
        gap = 10
        width = max(10, (rect.width() - gap * (len(self.values) - 1)) / len(self.values))
        window = self.palette().color(self.palette().ColorRole.Window)
        dark = window.lightness() < 140
        for index, value in enumerate(self.values):
            height = rect.height() * (value / maximum) if maximum else 0
            left = rect.x() + index * (width + gap)
            bar_height = max(height, 4)
            top = rect.bottom() - bar_height
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 78, 161, 28) if dark else QColor(0, 78, 161, 14))
            painter.drawRoundedRect(QRectF(left, rect.top(), width, rect.height()), 7, 7)
            gradient = QLinearGradient(left, top, left, rect.bottom())
            gradient.setColorAt(0, QColor("#4E86C4") if dark else QColor("#3D7CC2"))
            gradient.setColorAt(1, QColor("#2A6498") if dark else QColor("#004EA1"))
            painter.setBrush(gradient)
            painter.drawRoundedRect(QRectF(left, top, width, bar_height), 7, 7)
            painter.setPen(self.palette().color(self.palette().ColorRole.Text))
            label = self.labels[index] if index < len(self.labels) else ""
            if len(label) >= 10 and label[4] == "-":
                label = label[5:]
            painter.drawText(QRectF(left - 6, rect.bottom() + 4, width + 12, 18), Qt.AlignCenter, label)
            if value:
                painter.drawText(QRectF(left - 8, max(rect.top(), top - 18), width + 16, 16), Qt.AlignCenter, str(int(value)))
