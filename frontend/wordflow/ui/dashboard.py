"""首页。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wordflow.ui.chart import BarChart
from wordflow.ui.common import card, fill_study_plan_combo, page_header, section_title, stat_card


class DashboardPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(page_header("今天", "先复习到期的词，再学习新词。学习记录都保存在这台电脑上。"), 1)
        scope = QVBoxLayout()
        scope.setSpacing(4)
        scope_label = QLabel("学习范围")
        scope_label.setObjectName("muted")
        self.plan = QComboBox()
        self.plan.setMinimumWidth(220)
        self.plan.currentIndexChanged.connect(lambda _index: self.on_show())
        scope.addWidget(scope_label)
        scope.addWidget(self.plan)
        top.addLayout(scope)
        layout.addLayout(top)
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)
        self.cards = {}
        hero = QFrame()
        hero.setObjectName("hero")
        shadow = QGraphicsDropShadowEffect(hero)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(80, 120, 180, 28))
        hero.setGraphicsEffect(shadow)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(28, 22, 32, 22)
        hero_layout.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(4)
        kicker = QLabel("今日待复习")
        kicker.setObjectName("heroKicker")
        due = QLabel("0")
        due.setObjectName("heroValue")
        self.cards["due"] = due
        self.average = QLabel("先复习到期的词，再学习新词。")
        self.average.setObjectName("heroNote")
        self.average.setWordWrap(True)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        review = QPushButton("开始复习")
        learn = QPushButton("学习新词")
        placement = QPushButton("摸底")
        review.setObjectName("heroPrimary")
        learn.setObjectName("heroGhost")
        placement.setObjectName("heroGhost")
        for button, key in ((review, "review"), (learn, "learn"), (placement, "placement")):
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, name=key: navigator.go(name))
            actions.addWidget(button)
        actions.addStretch(1)
        left.addWidget(kicker)
        left.addWidget(due)
        left.addWidget(self.average)
        left.addSpacing(10)
        left.addLayout(actions)
        right = QVBoxLayout()
        right.setSpacing(0)
        right.addStretch(1)
        streak_label = QLabel("连续学习")
        streak_label.setObjectName("heroKicker")
        streak_label.setAlignment(Qt.AlignRight)
        streak = QLabel("0")
        streak.setObjectName("heroValue")
        streak.setAlignment(Qt.AlignRight)
        days = QLabel("天")
        days.setObjectName("heroKicker")
        days.setAlignment(Qt.AlignRight)
        self.cards["streak"] = streak
        right.addWidget(streak_label)
        right.addWidget(streak)
        right.addWidget(days)
        right.addStretch(1)
        hero_layout.addLayout(left, 1)
        hero_layout.addLayout(right)
        layout.addWidget(hero)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        metrics = (
            ("goal", "今日计划"),
            ("studied", "今日已学"),
            ("total", "词库"),
            ("learning", "生词"),
            ("mastered", "熟词"),
            ("untested", "尚未测试"),
        )
        for index, (key, caption) in enumerate(metrics):
            frame, value = stat_card(caption)
            self.cards[key] = value
            grid.addWidget(frame, index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        charts = QHBoxLayout()
        charts.setSpacing(12)
        self.chart = BarChart()
        self.chart.setMinimumHeight(168)
        self.chart.setMaximumHeight(190)
        self.forecast = BarChart()
        self.forecast.setMinimumHeight(168)
        self.forecast.setMaximumHeight(190)
        charts.addWidget(self._chart_card("最近 7 天", self.chart))
        charts.addWidget(self._chart_card("未来 7 天到期", self.forecast))
        layout.addLayout(charts)
        wrong_frame, wrong_layout = card()
        wrong_layout.addWidget(section_title("容易出错"))
        self.wrong = QLabel()
        self.wrong.setWordWrap(True)
        wrong_layout.addWidget(self.wrong)
        layout.addWidget(wrong_frame)

    def _chart_card(self, title: str, chart: BarChart) -> QWidget:
        frame, inner = card()
        inner.addWidget(section_title(title))
        inner.addWidget(chart)
        return frame

    def on_show(self) -> None:
        fill_study_plan_combo(self.plan, self.ctx.store, self.plan.currentData(), all_label="全部")
        plan_id = self.plan.currentData()
        goal = self.ctx.settings.integer("daily_new_limit", 20)
        data = self.ctx.store.dashboard(goal)
        counts = data["counts"]
        if plan_id:
            coverage = self.ctx.store.coverage(int(plan_id))
            due = len(self.ctx.store.pick_word_ids(purpose="due", limit=500, document_id=int(plan_id)))
            self.cards["due"].setText(str(due))
            self.cards["total"].setText(str(int(coverage["unique_count"] or 0)))
            self.cards["learning"].setText(str(int(coverage["learning"] or 0)))
            self.cards["mastered"].setText(str(int(coverage["mastered"] or 0)))
            self.cards["untested"].setText(str(int(coverage["untested"] or 0)))
        else:
            self.cards["due"].setText(str(data["due_total"]))
            self.cards["total"].setText(str(counts["total"]))
            self.cards["learning"].setText(str(counts["learning"] + counts["reviewing"]))
            self.cards["mastered"].setText(str(counts["mastered"]))
            self.cards["untested"].setText(str(counts["untested"]))
        self.cards["goal"].setText(str(goal))
        self.cards["studied"].setText(str(data["studied_today"]))
        self.cards["streak"].setText(str(data["streak"]))
        leeches = self.ctx.store.leech_count()
        self.average.setText(
            f"平均掌握程度 {data['average_mastery']}。待确认 {counts['pending']} 个。多次遗忘 {leeches} 个。"
        )
        series = self.ctx.store.daily_series(7)
        self.chart.set_series([item["day"] for item in series], [item["studied"] for item in series])
        forecast = self.ctx.store.due_forecast(7)
        self.forecast.set_series([item["day"] for item in forecast], [item["count"] for item in forecast])
        wrong = self.ctx.store.top_wrong(5, int(plan_id) if plan_id else None)
        if wrong:
            text = "最近容易出错：" + "、".join(f"{item['lemma']}（{item['wrong_count']} 次）" for item in wrong)
        else:
            text = "还没有错题记录。"
        self.wrong.setText(text)
        if self.ctx.dictionary.available:
            self.banner.hide()
        else:
            self.banner.setText("还没有加载本地词典。单词可以先导入，释义会标记为待补充，不会编造。运行 scripts\\fetch_dict.ps1 可以下载开源词典。")
            self.banner.show()
