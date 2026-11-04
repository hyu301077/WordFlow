"""学习统计。"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from wordflow.ui.chart import BarChart
from wordflow.ui.common import page_header


class StatsPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        layout = QVBoxLayout(self)
        layout.addWidget(page_header("学习统计", "这些数字来自你自己的答题记录。"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel("最近 30 天学习量"))
        self.activity = BarChart()
        layout.addWidget(self.activity)
        layout.addWidget(QLabel("摸底正确率"))
        self.accuracy = BarChart()
        layout.addWidget(self.accuracy)
        self.wrong = QLabel()
        self.wrong.setWordWrap(True)
        layout.addWidget(self.wrong)

    def on_show(self) -> None:
        counts = self.ctx.store.status_counts()
        data = self.ctx.store.dashboard(self.ctx.settings.integer("daily_new_limit", 20))
        series = self.ctx.store.daily_series(30)
        studied = sum(item["studied"] for item in series)
        correct = sum(item["correct"] for item in series)
        wrong = sum(item["wrong"] for item in series)
        graded = correct + wrong
        rate = round(correct / graded * 100, 1) if graded else 0
        self.summary.setText(
            f"词库 {counts['total']}。生词 {counts['learning'] + counts['reviewing']}，"
            f"熟词 {counts['mastered']}，未测试 {counts['untested']}，待确认 {counts['pending']}。\n"
            f"平均掌握 {data['average_mastery']}。近 30 天学习 {studied} 次，答题正确率 {rate}%。"
        )
        recent = series[-14:]
        self.activity.set_series([item["day"] for item in recent], [item["studied"] for item in recent])
        trend = self.ctx.store.placement_trend()
        self.accuracy.set_series(
            [item["label"] or "-" for item in trend],
            [item["accuracy"] for item in trend],
        )
        rows = self.ctx.store.top_wrong(10)
        if rows:
            self.wrong.setText(
                "反复出错：" + "、".join(f"{item['lemma']}（{item['wrong_count']}）" for item in rows)
            )
        else:
            self.wrong.setText("还没有反复出错的单词。")
