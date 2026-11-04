"""主窗口。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from wordflow import __version__
from wordflow.ui.articles import ArticlesPage
from wordflow.ui.assistant import AssistantPage
from wordflow.ui.common import app_icon
from wordflow.ui.dashboard import DashboardPage
from wordflow.ui.import_page import ImportPage
from wordflow.ui.listen import ListenPage
from wordflow.ui.plans import PlanPage
from wordflow.ui.practice import PracticePage
from wordflow.ui.reader import ReaderPage
from wordflow.ui.settings_page import SettingsPage
from wordflow.ui.stats_page import StatsPage
from wordflow.ui.theme import build_qss
from wordflow.ui.word_list import MistakePage, WordListPage

NAV = [
    ("home", "首页"),
    ("import", "导入文档"),
    ("articles", "英文文章"),
    ("plans", "学习计划"),
    ("listen", "语音朗读"),
    ("placement", "摸底测试"),
    ("learn", "学习新词"),
    ("review", "今日复习"),
    ("learning", "生词本"),
    ("mastered", "熟词本"),
    ("mistakes", "错题本"),
    ("stats", "学习统计"),
    ("assistant", "在线助手"),
    ("settings", "设置"),
]


class PageStack(QStackedWidget):
    """页面很高时仍允许窗口缩小，多出来的内容在滚动区域里看。"""

    def minimumSizeHint(self) -> QSize:
        return QSize(640, 420)

    def sizeHint(self) -> QSize:
        return QSize(960, 640)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"WordFlow 词流 {__version__}")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(920, 560)
        self.resize(self.ctx.settings.integer("window_width", 1180), self.ctx.settings.integer("window_height", 760))
        self.pages = {
            "home": DashboardPage(ctx, self),
            "import": ImportPage(ctx, self),
            "articles": ArticlesPage(ctx, self),
            "plans": PlanPage(ctx, self),
            "listen": ListenPage(ctx, self),
            "reader": ReaderPage(ctx, self),
            "placement": PracticePage(ctx, self, "placement"),
            "learn": PracticePage(ctx, self, "learn"),
            "review": PracticePage(ctx, self, "review"),
            "learning": WordListPage(ctx, self, "learning"),
            "mastered": WordListPage(ctx, self, "mastered"),
            "mistakes": MistakePage(ctx, self),
            "stats": StatsPage(ctx, self),
            "assistant": AssistantPage(ctx, self),
            "settings": SettingsPage(ctx, self),
        }
        self.nav_buttons = {}
        self._build()
        self._tray()
        self.go("home")

    def _build(self) -> None:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        title = QLabel("WordFlow")
        title.setObjectName("appTitle")
        subtitle = QLabel("词流")
        subtitle.setObjectName("muted")
        side.addWidget(title)
        side.addWidget(subtitle)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in NAV:
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, name=key: self.go(name))
            group.addButton(button)
            self.nav_buttons[key] = button
            side.addWidget(button)
        side.addStretch(1)
        self.dict_state = QLabel()
        self.dict_state.setWordWrap(True)
        self.dict_state.setObjectName("muted")
        side.addWidget(self.dict_state)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 18, 22, 18)
        self.hosts: dict[str, QScrollArea] = {}
        self.stack_widget = PageStack()
        self.stack_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for key, _label in NAV:
            self.stack_widget.addWidget(self._host(key))
        self.stack_widget.addWidget(self._host("reader"))
        content_layout.addWidget(self.stack_widget, 1)
        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        self.setCentralWidget(host)
        self._refresh_dict_state()

    def _host(self, key: str) -> QScrollArea:
        page = self.pages[key]
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setWidget(page)
        area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.hosts[key] = area
        return area

    def _refresh_dict_state(self) -> None:
        if self.ctx.dictionary.available:
            self.dict_state.setText(f"词典 {self.ctx.dictionary.entry_count} 词")
        else:
            self.dict_state.setText("词典未加载")

    def go(self, key: str) -> None:
        page = self.pages[key]
        self.stack_widget.setCurrentWidget(self.hosts[key])
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        refresher = getattr(page, "on_show", None)
        if refresher:
            refresher()

    def open_reader(self, document_id: int) -> None:
        self.pages["reader"].load(document_id)
        self.go("reader")

    def open_learn_words(self, word_ids: list[int]) -> None:
        self.go("learn")
        self.pages["learn"].start_with_words(word_ids)

    def open_review_words(self, word_ids: list[int]) -> None:
        self.go("review")
        self.pages["review"].start_with_words(word_ids)

    def apply_theme(self, mode: str) -> None:
        self.ctx.settings.set("theme", mode)
        self.window().setStyleSheet("")
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(build_qss(mode))
        page = self.stack_widget.currentWidget()
        if hasattr(page, "on_theme"):
            page.on_theme()

    def _tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("WordFlow")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            QTimer.singleShot(1200, self._remind)

    def _remind(self) -> None:
        if not self.ctx.settings.flag("reminder"):
            return
        data = self.ctx.store.dashboard(self.ctx.settings.integer("daily_new_limit", 20))
        if data["due_total"] and self.tray.isVisible():
            self.tray.showMessage("WordFlow", f"今天有 {data['due_total']} 个单词到了复习时间。", QSystemTrayIcon.Information, 4000)

    def closeEvent(self, event) -> None:
        self.ctx.settings.set("window_width", self.width())
        self.ctx.settings.set("window_height", self.height())
        for page in self.pages.values():
            shutdown = getattr(page, "shutdown", None)
            if shutdown:
                shutdown()
        try:
            self.pages["settings"].maybe_backup()
        except Exception:
            logging.getLogger("wordflow").exception("退出备份失败")
        event.accept()
