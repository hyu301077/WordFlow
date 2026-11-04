"""不依赖额外图表库的学习趋势图。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
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
        rect = self.rect().adjusted(8, 8, -8, -26)
        maximum = max(self.values) or 1
        gap = 8
        width = max(8, (rect.width() - gap * (len(self.values) - 1)) / len(self.values))
        for index, value in enumerate(self.values):
            height = rect.height() * (value / maximum) if maximum else 0
            left = rect.x() + index * (width + gap)
            top = rect.bottom() - height
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#2563EB"))
            painter.drawRoundedRect(QRectF(left, top, width, max(height, 2)), 4, 4)
            painter.setPen(self.palette().color(self.palette().ColorRole.Text))
            label = self.labels[index] if index < len(self.labels) else ""
            painter.drawText(QRectF(left - 4, rect.bottom() + 2, width + 8, 20), Qt.AlignCenter, label)
            if value:
                painter.drawText(QRectF(left - 6, max(0, top - 18), width + 12, 16), Qt.AlignCenter, str(int(value)))
