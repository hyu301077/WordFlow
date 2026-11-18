"""首页和统计页共用的趋势图。"""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget


class BarChart(QWidget):
    def __init__(self, parent=None, *, percent=False, empty_text="暂无数据"):
        super().__init__(parent)
        self.labels: list[str] = []
        self.values: list[float] = []
        self.percent = percent
        self.empty_text = empty_text
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_series(self, labels: list[str], values: list[float]) -> None:
        self.labels = labels
        self.values = values
        self.setAccessibleDescription("，".join(
            f"{label} {self._value_text(value)}" for label, value in zip(labels, values)
        ) or self.empty_text)
        self.update()

    def _value_text(self, value: float) -> str:
        return f"{value:g}%" if self.percent else f"{value:g}"

    def _plot(self) -> QRectF:
        maximum = 100 if self.percent else max(self.values, default=0)
        gutter = self.fontMetrics().horizontalAdvance(self._value_text(maximum)) + 12
        return QRectF(self.rect()).adjusted(gutter, self.fontMetrics().height() + 2, -8, -self.fontMetrics().height() - 6)

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip and self.values:
            plot = self._plot()
            if plot.contains(event.pos()) and plot.width() > 0:
                index = min(len(self.values) - 1, int((event.pos().x() - plot.left()) * len(self.values) / plot.width()))
                if index < len(self.labels):
                    QToolTip.showText(event.globalPos(), f"{self.labels[index]}  ·  {self._value_text(self.values[index])}", self)
                    return True
        return super().event(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        ink = self.palette().windowText().color()
        muted = QColor(ink)
        muted.setAlpha(180)
        painter.setPen(muted)
        if not self.values or (not self.percent and not any(self.values)):
            painter.drawText(self.rect(), Qt.AlignCenter, self.empty_text)
            return

        plot = self._plot()
        if plot.width() <= 0 or plot.height() <= 0:
            return
        maximum = 100 if self.percent else max(self.values)
        grid = QColor(ink)
        grid.setAlpha(35)
        accent = QColor("#818CF8" if self.palette().window().color().lightness() < 140 else "#004EA1")
        label_height = self.fontMetrics().height()
        for value in sorted({0, maximum // 2, maximum}):
            y = plot.bottom() - plot.height() * value / maximum
            painter.setPen(grid)
            painter.drawLine(int(plot.left()), round(y), int(plot.right()), round(y))
            painter.setPen(muted)
            painter.drawText(QRectF(0, y - label_height / 2, plot.left() - 7, label_height),
                             Qt.AlignRight | Qt.AlignVCenter, self._value_text(value))

        step = plot.width() / len(self.values)
        width = min(42, step * 0.62)
        label_width = max((self.fontMetrics().horizontalAdvance(label) for label in self.labels), default=0)
        stride = max(1, ceil((label_width + 10) / step))
        last = len(self.values) - 1
        for index, value in enumerate(self.values):
            center = plot.left() + (index + 0.5) * step
            height = plot.height() * value / maximum
            if height > 0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(accent)
                painter.drawRoundedRect(QRectF(center - width / 2, plot.bottom() - height, width, height),
                                        min(4, width / 2), min(4, height / 2))
            painter.setPen(muted)
            if index < len(self.labels) and (index == last or (index % stride == 0 and last - index >= stride)):
                left = max(0, min(center - label_width / 2, self.width() - label_width))
                painter.drawText(QRectF(left, plot.bottom() + 4, label_width, label_height), Qt.AlignCenter, self.labels[index])
            value_text = self._value_text(value)
            if step >= self.fontMetrics().horizontalAdvance(value_text) + 10 and (value or self.percent):
                painter.setPen(ink)
                painter.drawText(QRectF(center - step / 2, plot.bottom() - height - label_height, step, label_height),
                                 Qt.AlignCenter, value_text)
