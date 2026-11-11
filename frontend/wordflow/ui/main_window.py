"""主窗口。"""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QCursor, QGuiApplication
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
from wordflow.ui.theme import build_qss
from wordflow.ui.word_list import MistakePage, WordListPage

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
        return QSize(640, 420)

    def sizeHint(self) -> QSize:
        return QSize(960, 640)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(" ")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(800, 480)
        self._placed = False
        self._applying_geometry = False
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(400)
        self._geometry_timer.timeout.connect(self._store_geometry)
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
        nav_scroll = QScrollArea()
        nav_scroll.setObjectName("sidebarScroll")
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        nav_scroll.setWidget(nav_host)
        nav_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        side.addWidget(nav_scroll, 1)
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
        refresher = getattr(page, "on_show", None)
        if refresher:
            refresher()

    def open_listen(self, folder) -> None:
        from pathlib import Path

        page = self.pages["listen"]
        path = Path(folder)
        self.ctx.settings.set("listen_folder", str(path))
        page._restored = True
        page.scan(path)
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
        self.window().setStyleSheet("")
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(build_qss(mode))
        self._apply_nav_icons(mode)
        self._tint_titlebar()
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._placed:
            self._placed = True
            self._restore_or_default()
        self._tint_titlebar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._remember_geometry()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._remember_geometry()

    def _remember_geometry(self) -> None:
        if self._applying_geometry or not self._placed:
            return
        self._geometry_timer.start()

    def _target_screen(self):
        if self.ctx.settings.get("window_custom", "") == "1":
            saved = QPoint(self.ctx.settings.integer("window_x", 0) + 40, self.ctx.settings.integer("window_y", 0) + 40)
            screen = QGuiApplication.screenAt(saved)
            if screen is not None:
                return screen
        screen = QGuiApplication.screenAt(QCursor.pos())
        return screen or self.screen() or QGuiApplication.primaryScreen()

    def _landscape_size(self, area: QRect) -> tuple[int, int]:
        """没有用户记录时，用 16:10 的横向窗口，并留出屏幕边距。"""
        width = min(1680, max(self.minimumWidth(), area.width() - 48))
        height = int(width * 10 / 16)
        if height > area.height() - 48:
            height = max(self.minimumHeight(), area.height() - 48)
            width = min(area.width() - 24, int(height * 16 / 10))
        return self._clamp_size(width, height, area)

    def _clamp_size(self, width: int, height: int, area: QRect) -> tuple[int, int]:
        max_width = max(self.minimumWidth(), area.width() - 16)
        max_height = max(self.minimumHeight(), area.height() - 16)
        scale = min(1.0, max_width / max(width, 1), max_height / max(height, 1))
        width = min(max_width, max(self.minimumWidth(), int(width * scale)))
        height = min(max_height, max(self.minimumHeight(), int(height * scale)))
        return width, height

    def _clamp_position(self, x: int, y: int, width: int, height: int, area: QRect) -> tuple[int, int]:
        x = min(max(area.left(), x), max(area.left(), area.right() - width + 1))
        y = min(max(area.top(), y), max(area.top(), area.bottom() - height + 1))
        return x, y

    def _restore_or_default(self) -> None:
        screen = self._target_screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        custom = self.ctx.settings.get("window_custom", "") == "1"
        if custom:
            width = self.ctx.settings.integer("window_width", 0)
            height = self.ctx.settings.integer("window_height", 0)
            x = self.ctx.settings.integer("window_x", area.x())
            y = self.ctx.settings.integer("window_y", area.y())
            if width < self.minimumWidth() or height < self.minimumHeight():
                width, height = self._landscape_size(area)
                x = area.x() + max(0, (area.width() - width) // 2)
                y = area.y() + max(0, (area.height() - height) // 2)
        else:
            width, height = self._landscape_size(area)
            x = area.x() + max(0, (area.width() - width) // 2)
            y = area.y() + max(0, (area.height() - height) // 2)
        width, height = self._clamp_size(width, height, area)
        x, y = self._clamp_position(x, y, width, height, area)
        maximized = custom and self.ctx.settings.get("window_maximized", "") == "1"
        self._applying_geometry = True
        self.resize(width, height)
        self.move(x, y)
        if maximized:
            self.showMaximized()
        QTimer.singleShot(0, self._finish_apply)

    def _finish_apply(self) -> None:
        self._applying_geometry = False

    def _store_geometry(self) -> None:
        if self._applying_geometry or not self._placed:
            return
        normal = self.normalGeometry()
        if normal.width() < self.minimumWidth() or normal.height() < self.minimumHeight():
            return
        self.ctx.settings.set("window_custom", "1")
        self.ctx.settings.set("window_maximized", "1" if self.isMaximized() else "0")
        self.ctx.settings.set("window_width", normal.width())
        self.ctx.settings.set("window_height", normal.height())
        self.ctx.settings.set("window_x", normal.x())
        self.ctx.settings.set("window_y", normal.y())

    def _tint_titlebar(self) -> None:
        """把系统标题栏涂成侧栏的深色，并去掉标题文字。"""
        self.setWindowTitle(" ")
        if sys.platform != "win32":
            return
        mode = self.ctx.settings.get("theme", "light")
        hex_color = "#2C3A4F" if mode == "dark" else "#004EA1"
        red = int(hex_color[1:3], 16)
        green = int(hex_color[3:5], 16)
        blue = int(hex_color[5:7], 16)
        colorref = (blue << 16) | (green << 8) | red
        try:
            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi

            def paint(index: int, value: int) -> None:
                holder = ctypes.c_int(value)
                dwm.DwmSetWindowAttribute(hwnd, index, ctypes.byref(holder), ctypes.sizeof(holder))

            paint(20, 1)
            paint(34, colorref)
            paint(35, colorref)
            paint(36, 0x00FFFFFF)
        except Exception:
            logging.getLogger("wordflow").debug("标题栏着色失败", exc_info=True)

    def closeEvent(self, event) -> None:
        self._geometry_timer.stop()
        self._store_geometry()
        for page in self.pages.values():
            shutdown = getattr(page, "shutdown", None)
            if shutdown:
                shutdown()
        try:
            self.pages["settings"].maybe_backup()
        except Exception:
            logging.getLogger("wordflow").exception("退出备份失败")
        event.accept()
