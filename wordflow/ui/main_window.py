"""主窗口。"""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QByteArray, QSize, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
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

from wordflow.ui.articles import ArticlesPage
from wordflow.ui.assistant import AssistantPage
from wordflow.ui.common import app_icon, nav_icon
from wordflow.ui.dashboard import DashboardPage
from wordflow.ui.import_page import ImportPage
from wordflow.ui.listen import ListenPage
from wordflow.ui.plans import PlanPage
from wordflow.ui.practice import PracticePage
from wordflow.ui.reader import ReaderPage
from wordflow.ui.settings_page import SettingsPage
from wordflow.ui.stats_page import StatsPage
from wordflow.ui.theme import build_qss, sidebar_color
from wordflow.ui.word_list import MistakePage, WordListPage

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

NAV_GROUPS = [
    ("学习", [("home", "首页"), ("plans", "学习计划"), ("placement", "摸底测试"), ("learn", "学习新词"), ("review", "今日复习")]),
    ("资料", [("import", "导入文档"), ("articles", "英文文章"), ("listen", "语音朗读")]),
    ("词库", [("learning", "生词本"), ("mastered", "熟词本"), ("mistakes", "错题本"), ("stats", "学习统计")]),
    ("更多", [("assistant", "在线助手"), ("settings", "设置")]),
]
NAV = [item for _title, items in NAV_GROUPS for item in items]


class PageStack(QStackedWidget):
    """页面很高时仍允许窗口缩小，多出来的内容在滚动区域里看。"""

    def minimumSizeHint(self) -> QSize:
        return QSize(420, 300)

    def sizeHint(self) -> QSize:
        return QSize(960, 640)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("WordFlow 词流")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(800, 480)
        self.resize(self.ctx.settings.integer("window_width", 1180), self.ctx.settings.integer("window_height", 760))
        saved_geometry = self.ctx.settings.get("window_geometry", "")
        if saved_geometry:
            self.restoreGeometry(QByteArray.fromHex(saved_geometry.encode("ascii", errors="ignore")))
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
        host.setObjectName("shell")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 14)
        side.setSpacing(2)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel("词")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(36, 36)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("WordFlow")
        title.setObjectName("appTitle")
        subtitle = QLabel("词流")
        subtitle.setObjectName("muted")
        names.addWidget(title)
        names.addWidget(subtitle)
        brand.addWidget(mark)
        brand.addLayout(names, 1)
        side.addLayout(brand)
        side.addSpacing(8)
        nav_host = QWidget()
        nav_host.setObjectName("navHost")
        nav_layout = QVBoxLayout(nav_host)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (section, items) in enumerate(NAV_GROUPS):
            caption = QLabel(section)
            caption.setObjectName("navSection")
            caption.setMinimumHeight(caption.fontMetrics().height() + 10)
            caption.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            if index == 0:
                caption.setContentsMargins(10, 2, 10, 0)
            nav_layout.addWidget(caption)
            for key, label in items:
                button = QPushButton(label)
                button.setObjectName("nav")
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                button.setIconSize(QSize(18, 18))
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                button.setMinimumHeight(max(30, button.fontMetrics().height() + 12))
                button.clicked.connect(lambda _checked=False, name=key: self.go(name))
                group.addButton(button)
                self.nav_buttons[key] = button
                nav_layout.addWidget(button)
        self.nav_scroll = QScrollArea()
        self.nav_scroll.setObjectName("sidebarScroll")
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setFrameShape(QFrame.NoFrame)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav_scroll.setWidget(nav_host)
        self.nav_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        side.addWidget(self.nav_scroll, 1)
        self._apply_nav_icons(self.ctx.settings.get("theme", "light"))
        self.dict_state = QLabel()
        self.dict_state.setWordWrap(True)
        self.dict_state.setObjectName("dictChip")
        self.dict_state.setMinimumHeight(self.dict_state.fontMetrics().height() + 18)
        side.addWidget(self.dict_state)
        stage_host = QWidget()
        stage_host.setObjectName("shell")
        stage_margin = QVBoxLayout(stage_host)
        stage_margin.setContentsMargins(10, 10, 12, 12)
        stage = QFrame()
        stage.setObjectName("stage")
        content_layout = QVBoxLayout(stage)
        content_layout.setContentsMargins(28, 22, 28, 22)
        self.hosts: dict[str, QScrollArea] = {}
        self.stack_widget = PageStack()
        self.stack_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for key, _label in NAV:
            self.stack_widget.addWidget(self._host(key))
        self.stack_widget.addWidget(self._host("reader"))
        content_layout.addWidget(self.stack_widget, 1)
        stage_margin.addWidget(stage)
        layout.addWidget(sidebar)
        layout.addWidget(stage_host, 1)
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
        if key in self.nav_buttons:
            self.nav_scroll.ensureWidgetVisible(self.nav_buttons[key], 0, 0)
        refresher = getattr(page, "on_show", None)
        if refresher:
            refresher()

    def open_listen(self, folder) -> None:
        self.pages["listen"].open_folder(folder)
        self.go("listen")

    def open_reader(self, document_id: int) -> None:
        self.pages["reader"].load(document_id)
        self.go("reader")

    def open_learn_words(self, word_ids: list[int]) -> None:
        self.go("learn")
        self.pages["learn"].start_with_words(word_ids)

    def open_review_words(self, word_ids: list[int]) -> None:
        self.go("review")
        self.pages["review"].start_with_words(word_ids)

    def _apply_nav_icons(self, mode: str) -> None:
        off = "#DDD9FF"
        on = "#FFFFFF" if mode == "dark" else "#004EA1"
        for key, button in self.nav_buttons.items():
            button.setIcon(nav_icon(key, off, on))

    def apply_theme(self, mode: str) -> None:
        self.ctx.settings.set("theme", mode)
        QApplication.instance().setStyleSheet(build_qss(mode))
        self._apply_nav_icons(mode)
        if self.isVisible():
            self._tint_title_bar(mode)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._tint_title_bar(self.ctx.settings.get("theme", "light"))

    def _tint_title_bar(self, mode: str) -> None:
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            return
        hwnd = ctypes.c_void_p(int(self.winId()))
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        color = QColor(sidebar_color(mode))
        colorref = color.red() | (color.green() << 8) | (color.blue() << 16)
        caption = ctypes.c_uint32(colorref)
        if set_attribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption), ctypes.sizeof(caption)) != 0:
            return
        for attribute, value in (
            (DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
            (DWMWA_BORDER_COLOR, colorref),
            (DWMWA_TEXT_COLOR, 0xFFFFFF),
        ):
            setting = ctypes.c_uint32(value)
            set_attribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting))
        self.setWindowTitle(" ")

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
        if self.pages["assistant"].cancel_talk_on_close():
            event.ignore()
            return
        self.ctx.settings.set("window_geometry", bytes(self.saveGeometry().toHex()).decode("ascii"))
        for page in self.pages.values():
            shutdown = getattr(page, "shutdown", None)
            if shutdown:
                shutdown()
        try:
            self.pages["settings"].maybe_backup()
        except Exception:
            logging.getLogger("wordflow").exception("退出备份失败")
        event.accept()
