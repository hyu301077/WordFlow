"""学习统计。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from wordflow.ui.chart import BarChart
from wordflow.ui.common import card, fill_study_plan_combo, page_header, section_title, stat_card


class StatsPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.addWidget(page_header("学习统计", "按学习范围查看练习次数、正确率和掌握情况。"), 1)
        scope = QVBoxLayout()
        label = QLabel("学习范围")
        label.setObjectName("muted")
        self.plan = QComboBox()
        self.plan.setMinimumWidth(150)
        self.plan.setMaximumWidth(240)
        self.plan.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.plan.currentIndexChanged.connect(self.on_show)
        label.setBuddy(self.plan)
        scope.addWidget(label)
        scope.addWidget(self.plan)
        header.addLayout(scope)
        layout.addLayout(header)

        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metrics = []
        for title in ("近 30 天练习", "近 30 天正确率", "已掌握单词"):
            frame, value = stat_card(title, accent=not self.metrics)
            detail = QLabel()
            detail.setWordWrap(True)
            detail.setObjectName("muted")
            frame.layout().addWidget(detail)
            metrics.addWidget(frame, 1)
            self.metrics.append((value, detail))
        layout.addLayout(metrics)

        activity_card, inner = card()
        inner.addWidget(section_title("最近 30 天学习量"))
        self.activity = BarChart(empty_text="完成练习后，这里会按天显示作答次数")
        self.activity.setAccessibleName("最近 30 天学习量")
        inner.addWidget(self.activity)
        layout.addWidget(activity_card)

        self.details = QBoxLayout(QBoxLayout.LeftToRight)
        self.details.setSpacing(12)
        accuracy_card, inner = card()
        inner.addWidget(section_title("摸底正确率"))
        self.accuracy = BarChart(percent=True, empty_text="完成一次有评分的摸底后，这里会显示正确率")
        self.accuracy.setAccessibleName("最近 12 次摸底正确率")
        inner.addWidget(self.accuracy)
        self.details.addWidget(accuracy_card, 3)

        wrong_card, inner = card()
        inner.addWidget(section_title("常错词"))
        self.wrong_empty = QLabel("当前范围还没有错题。")
        self.wrong_empty.setObjectName("muted")
        inner.addWidget(self.wrong_empty)
        ranking = QGridLayout()
        ranking.setColumnStretch(0, 1)
        ranking.setVerticalSpacing(7)
        self.wrong_rows = []
        for index in range(10):
            word, count = QLabel(), QLabel()
            word.setTextFormat(Qt.PlainText)
            word.setWordWrap(True)
            count.setObjectName("muted")
            ranking.addWidget(word, index, 0)
            ranking.addWidget(count, index, 1, Qt.AlignRight)
            self.wrong_rows.append((word, count))
        inner.addLayout(ranking)
        inner.addStretch()
        self.details.addWidget(wrong_card, 2)
        layout.addLayout(self.details)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        layout.addStretch()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.details.setDirection(QBoxLayout.LeftToRight if self.width() >= 780 else QBoxLayout.TopToBottom)

    def on_show(self) -> None:
        store = self.ctx.store
        fill_study_plan_combo(self.plan, store, self.plan.currentData())
        plan_id = self.plan.currentData()
        self.plan.setToolTip(self.plan.currentText())
        counts = store.status_counts(plan_id)
        series = store.daily_series(30, plan_id)
        studied = sum(row["studied"] for row in series)
        correct = sum(row["correct"] for row in series)
        graded = correct + sum(row["wrong"] for row in series)
        metric_data = (
            (f"{studied:,}", f"共练习 {sum(row['studied'] > 0 for row in series)} 天"),
            (f"{correct / graded:.1%}" if graded else "—", f"答对 {correct:,} / {graded:,} 题" if graded else "暂无评分"),
            (f"{counts['mastered']:,}", f"范围内共 {counts['total']:,} 词"),
        )
        for (value, detail), (number, note) in zip(self.metrics, metric_data):
            value.setText(number)
            detail.setText(note)
        self.activity.set_series([row["day"] for row in series], [row["studied"] for row in series])
        trend = store.placement_trend(document_id=plan_id)
        self.accuracy.set_series([row["label"] for row in trend], [row["accuracy"] for row in trend])
        wrong = store.top_wrong(10, plan_id)
        self.wrong_empty.setVisible(not wrong)
        for index, (word, count) in enumerate(self.wrong_rows):
            visible = index < len(wrong)
            word.setVisible(visible)
            count.setVisible(visible)
            if visible:
                word.setText(wrong[index]["lemma"])
                count.setText(f"{wrong[index]['wrong_count']} 次")
        self.summary.setText(
            f"学习中 {counts['learning'] + counts['reviewing']} 词    ·    尚未测试 {counts['untested']} 词"
            f"    ·    待确认 {counts['pending']} 词    ·    平均掌握程度 {store.average_mastery(plan_id):.1f}"
        )
