"""首页。"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from wordflow.ui.chart import BarChart
from wordflow.ui.common import fill_study_plan_combo, page_header, stat_card


class DashboardPage(QWidget):
    def __init__(self, ctx, navigator):
        super().__init__()
        self.ctx = ctx
        self.navigator = navigator
        layout = QVBoxLayout(self)
        layout.addWidget(page_header("今天", "先复习到期的词，再学习新词。数据都保存在这台电脑上。"))
        plan_row = QHBoxLayout()
        plan_row.addWidget(QLabel("学习计划"))
        self.plan = QComboBox()
        self.plan.currentIndexChanged.connect(lambda _index: self.on_show())
        plan_row.addWidget(self.plan, 1)
        layout.addLayout(plan_row)
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)
        self.cards = {}
        grid = QGridLayout()
        for index, (key, caption) in enumerate(
            (
                ("due", "今日待复习"),
                ("goal", "今日计划新词"),
                ("studied", "今日已学习"),
                ("streak", "连续学习天数"),
                ("total", "词库总词数"),
                ("learning", "生词"),
                ("mastered", "熟词"),
                ("untested", "尚未测试"),
            )
        ):
            frame, value = stat_card(caption)
            self.cards[key] = value
            grid.addWidget(frame, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        buttons = QHBoxLayout()
        review = QPushButton("开始今日复习")
        learn = QPushButton("学习新词")
        placement = QPushButton("摸底测试")
        review.setObjectName("primary")
        review.clicked.connect(lambda: navigator.go("review"))
        learn.clicked.connect(lambda: navigator.go("learn"))
        placement.clicked.connect(lambda: navigator.go("placement"))
        buttons.addWidget(review)
        buttons.addWidget(learn)
        buttons.addWidget(placement)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.average = QLabel()
        self.average.setObjectName("muted")
        layout.addWidget(self.average)
        layout.addWidget(QLabel("最近 7 天学习单词数"))
        self.chart = BarChart()
        layout.addWidget(self.chart, 1)
        layout.addWidget(QLabel("未来 7 天到期单词数（逾期算在今天）"))
        self.forecast = BarChart()
        layout.addWidget(self.forecast, 1)
        self.wrong = QLabel()
        self.wrong.setWordWrap(True)
        layout.addWidget(self.wrong)

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
