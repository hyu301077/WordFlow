"""界面样式。浅色和深色都按常用学习应用的层次来排：侧栏、画布、卡片分开。"""

from __future__ import annotations


def build_qss(mode: str) -> str:
    if mode == "dark":
        canvas, sidebar, card, border = "#0E1320", "#121826", "#1B2436", "#2C3850"
        text, muted, primary, primary_hover = "#E8EDF7", "#93A0B8", "#818CF8", "#A5B4FC"
        soft, danger, ok, input = "#243049", "#FB7185", "#34D399", "#121826"
        selection, nav_text, chip = "#312E81", "#E4E2FF", "#1E293B"
        secondary_hover, accent_line = "#2A3654", "#6366F1"
        side_bg, side_muted = "#2C3A4F", "#C5D0E0"
        nav_on_bg, nav_on_text = "#3D5270", "#FFFFFF"
        hero_bg, hero_border, hero_text, hero_muted, hero_value = "#1B2436", "#2C3850", "#E8EDF7", "#93A0B8", "#C7D7F5"
        hero_ghost_bg, hero_ghost_text, hero_ghost_border = "rgba(255, 255, 255, 0.06)", "#E8EDF7", "#3A4A62"
    else:
        canvas, sidebar, card, border = "#FFFFFF", "#004EA1", "#FFFFFF", "#E6EBF3"
        text, muted, primary, primary_hover = "#1E2430", "#6B728A", "#004EA1", "#003E82"
        soft, danger, ok, input = "#F3F7FD", "#E11D48", "#059669", "#FFFFFF"
        selection, nav_text, chip = "#E7F0FF", "#F5F9FF", "#F4F7FB"
        secondary_hover, accent_line = "#E7F0FF", "#D5E3FA"
        side_bg, side_muted = "#004EA1", "#D4E6F7"
        nav_on_bg, nav_on_text = "#D6E7F5", "#004EA1"
        hero_bg, hero_border, hero_text, hero_muted, hero_value = "#F4F7FD", "#E4EAF4", "#1E2430", "#64748B", "#2F5FBF"
        hero_ghost_bg, hero_ghost_text, hero_ghost_border = "#FFFFFF", "#2F5FBF", "#D7E2F2"
    return f"""
    QWidget {{
        background: {canvas};
        color: {text};
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 14px;
    }}
    QMainWindow, QWidget#shell, QDialog#shell {{ background: {side_bg}; }}
    QDialog {{ background: {canvas}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QFrame#stage {{
        background: {canvas};
        border: none;
        border-radius: 16px;
    }}
    QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
    QFrame#sidebar {{
        background: {side_bg};
        border: none;
    }}
    QFrame#sidebar QLabel#appTitle {{ color: #F7F6FF; }}
    QFrame#sidebar QLabel#muted, QFrame#sidebar QLabel#navSection {{ color: {side_muted}; }}
    QFrame#sidebar QLabel#dictChip {{
        background: rgba(255, 255, 255, 0.08);
        color: #F4F3FF;
        border-radius: 10px;
        padding: 8px 10px;
    }}
    QFrame#card, QFrame#wordCard, QFrame#statCard {{
        background: {card};
        border: 1px solid {border};
        border-radius: 16px;
    }}
    QFrame#wordCard {{
        background: {card};
        border: 1px solid {border};
        border-radius: 28px;
    }}
    QFrame#hero {{
        background: {hero_bg};
        border: 1px solid {hero_border};
        border-radius: 20px;
    }}
    QFrame#hero QLabel {{ background: transparent; color: {hero_text}; }}
    QFrame#hero QLabel#heroKicker {{
        color: {hero_muted};
        font-size: 13px;
        font-weight: 600;
    }}
    QFrame#hero QLabel#heroValue {{
        color: {hero_value};
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 48px;
        font-weight: 700;
        background: transparent;
    }}
    QFrame#hero QLabel#heroNote {{
        color: {hero_muted};
        font-size: 13px;
        background: transparent;
    }}
    QFrame#player {{
        background: {card};
        border: 1px solid {border};
        border-radius: 22px;
    }}
    QFrame#statCard[accent="true"] {{
        background: {soft};
        border: 1px solid {accent_line};
    }}
    QLabel#brandMark {{
        background: #FFFFFF;
        color: #004EA1;
        border-radius: 12px;
        font-size: 16px;
        font-weight: 700;
    }}
    QLabel#appTitle {{
        font-size: 16px;
        font-weight: 700;
        background: transparent;
        color: {text};
    }}
    QLabel#pageTitle {{
        font-size: 26px;
        font-weight: 700;
        background: transparent;
        color: {text};
    }}
    QLabel#sectionTitle {{
        font-size: 15px;
        font-weight: 700;
        background: transparent;
        color: {text};
    }}
    QLabel#muted, QLabel#subtitle, QLabel#navSection, QLabel#progressLabel {{
        color: {muted};
        background: transparent;
        font-size: 13px;
    }}
    QWidget#navHost, QScrollArea#sidebarScroll, QScrollArea#sidebarScroll > QWidget {{
        background: {side_bg};
        border: none;
    }}
    QLabel#navSection {{
        font-size: 12px;
        font-weight: 700;
        padding: 8px 10px 2px 10px;
    }}
    QLabel#statValue {{
        font-size: 30px;
        font-weight: 700;
        background: transparent;
        color: {text};
    }}
    QLabel#wordTitle {{
        font-size: 52px;
        font-weight: 700;
        background: transparent;
        color: {text};
    }}
    QLabel#phonetic {{
        color: {primary};
        font-size: 16px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#sense {{
        font-size: 18px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#exampleLine {{
        font-size: 16px;
        background: transparent;
    }}
    QLabel#listenSentence {{
        font-size: 22px;
        font-weight: 600;
        background: transparent;
        color: {text};
    }}
    QLabel#banner {{
        background: {soft};
        color: {text};
        border: 1px solid {accent_line};
        border-radius: 12px;
        padding: 12px 14px;
    }}
    QLabel#dictChip {{
        background: {chip};
        color: {muted};
        border-radius: 10px;
        padding: 8px 10px;
        font-size: 12px;
    }}
    QPushButton {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 10px;
        padding: 8px 14px;
        min-height: 34px;
    }}
    QPushButton:hover {{
        border-color: {primary};
        background: {chip};
    }}
    QPushButton:disabled {{ color: {muted}; background: {chip}; }}
    QPushButton:checked {{
        background: {soft};
        color: {primary};
        border: 1px solid {accent_line};
        font-weight: 600;
    }}
    QPushButton#primary {{
        background: {primary};
        color: white;
        border: none;
        font-weight: 700;
        padding: 8px 18px;
    }}
    QPushButton#primary:hover {{ background: {primary_hover}; }}
    QPushButton#primary:disabled {{ background: #C7D2FE; color: white; }}
    QPushButton#secondary {{
        background: {soft};
        color: {primary};
        border: none;
        font-weight: 700;
    }}
    QPushButton#secondary:hover {{ background: {secondary_hover}; }}
    QPushButton#danger {{
        background: {danger};
        color: white;
        border: none;
        font-weight: 700;
    }}
    QPushButton#heroPrimary {{
        background: {primary};
        color: white;
        border: none;
        border-radius: 12px;
        font-weight: 700;
        padding: 8px 18px;
        min-width: 120px;
    }}
    QPushButton#heroPrimary:hover {{ background: {primary_hover}; }}
    QPushButton#heroGhost {{
        background: {hero_ghost_bg};
        color: {hero_ghost_text};
        border: 1px solid {hero_ghost_border};
        border-radius: 12px;
        font-weight: 600;
    }}
    QPushButton#heroGhost:hover {{ background: {soft}; }}
    QPushButton#nav {{
        text-align: left;
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 6px 10px;
        min-height: 28px;
        color: {nav_text};
        font-weight: 500;
    }}
    QPushButton#nav:hover {{ background: rgba(255, 255, 255, 0.08); color: white; }}
    QPushButton#nav:checked {{
        background: {nav_on_bg};
        color: {nav_on_text};
        font-weight: 700;
    }}
    QPushButton[state="correct"] {{ background: {ok}; color: white; border: none; }}
    QPushButton[state="wrong"] {{ background: {danger}; color: white; border: none; }}
    QPushButton[state="answer"] {{ background: {soft}; color: {text}; border: 1px solid {primary}; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTextBrowser {{
        background: {input};
        color: {text};
        border: 1px solid {border};
        border-radius: 10px;
        padding: 6px 8px;
        min-height: 28px;
        selection-background-color: {selection};
        selection-color: {text};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {primary};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        selection-background-color: {soft};
        selection-color: {text};
        outline: none;
    }}
    QTableView {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 12px;
        alternate-background-color: {chip};
        selection-background-color: {soft};
        selection-color: {text};
        gridline-color: transparent;
        padding: 4px;
    }}
    QTableView::item {{ padding: 8px 6px; border: none; }}
    QHeaderView::section {{
        background: {card};
        color: {muted};
        border: none;
        border-bottom: 1px solid {border};
        padding: 8px 6px;
        font-size: 12px;
        font-weight: 700;
    }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
    QListWidget::item:selected {{ background: {soft}; color: {text}; }}
    QTabWidget::pane {{
        border: 1px solid {border};
        border-radius: 12px;
        background: {card};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {muted};
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        margin-right: 4px;
    }}
    QTabBar::tab:selected {{
        background: {soft};
        color: {primary};
        font-weight: 700;
    }}
    QProgressBar {{
        border: none;
        border-radius: 7px;
        background: {border};
        text-align: center;
        min-height: 14px;
        color: {text};
    }}
    QProgressBar::chunk {{ background: {primary}; border-radius: 7px; }}
    QProgressBar#studyProgress {{
        border: none;
        background: {border};
        border-radius: 4px;
        min-height: 8px;
        max-height: 8px;
    }}
    QProgressBar#studyProgress::chunk {{ background: {primary}; border-radius: 4px; }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: {border};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        width: 16px;
        height: 16px;
        margin: -6px 0;
        background: {primary};
        border-radius: 8px;
    }}
    QScrollBar:vertical {{ width: 10px; background: transparent; margin: 4px 2px; }}
    QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px 4px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: #C5CAD6;
        border-radius: 5px;
        min-height: 24px;
        min-width: 24px;
    }}
    QScrollArea#sidebarScroll QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 0.45); }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QToolTip {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 6px 8px;
    }}
    """
