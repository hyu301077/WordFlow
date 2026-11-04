"""界面样式。浅色和深色都保证正文与按钮有足够对比。"""

from __future__ import annotations


def build_qss(mode: str) -> str:
    if mode == "dark":
        bg, sidebar, card, border = "#0F1419", "#171C24", "#1E2633", "#2C3644"
        text, muted, primary, primary_hover = "#E8EEF5", "#A7B4C2", "#5B9BFF", "#3B82F6"
        soft, danger, ok, input = "#243044", "#F07178", "#3DDC97", "#121820"
        selection, nav_text = "#1E3A5F", "#C5D0DC"
    else:
        bg, sidebar, card, border = "#F4F6F8", "#FFFFFF", "#FFFFFF", "#E6E8EC"
        text, muted, primary, primary_hover = "#1F2937", "#6B7280", "#2563EB", "#1D4ED8"
        soft, danger, ok, input = "#E8F0FE", "#DC2626", "#059669", "#FFFFFF"
        selection, nav_text = "#DBEAFE", "#374151"
    return f"""
    QWidget {{
        background: {bg};
        color: {text};
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 14px;
    }}
    QMainWindow, QDialog, QScrollArea {{ background: {bg}; }}
    QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
    QFrame#card, QFrame#wordCard {{
        background: {card};
        border: 1px solid {border};
        border-radius: 14px;
    }}
    QLabel#appTitle {{ font-size: 22px; font-weight: 700; background: transparent; }}
    QLabel#pageTitle {{ font-size: 24px; font-weight: 700; background: transparent; }}
    QLabel#muted, QLabel#subtitle {{ color: {muted}; background: transparent; }}
    QLabel#statValue {{ font-size: 28px; font-weight: 700; background: transparent; }}
    QLabel#wordTitle {{ font-size: 42px; font-weight: 700; background: transparent; }}
    QLabel#banner {{
        background: {soft};
        border-radius: 10px;
        padding: 10px 12px;
        color: {text};
    }}
    QPushButton {{
        background: {card};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 8px 14px;
        min-height: 22px;
    }}
    QPushButton:hover {{ border-color: {primary}; }}
    QPushButton:disabled {{ color: {muted}; }}
    QPushButton#primary {{
        background: {primary};
        color: white;
        border: none;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {primary_hover}; }}
    QPushButton#danger {{
        background: {danger};
        color: white;
        border: none;
    }}
    QPushButton#nav {{
        text-align: left;
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 9px 12px;
        color: {nav_text};
    }}
    QPushButton#nav:checked {{
        background: {soft};
        color: {primary};
        font-weight: 700;
    }}
    QPushButton[state="correct"] {{ background: {ok}; color: white; border: none; }}
    QPushButton[state="wrong"] {{ background: {danger}; color: white; border: none; }}
    QPushButton[state="answer"] {{ background: {soft}; border: 1px solid {primary}; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QTableView, QListWidget, QTextBrowser {{
        background: {input};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 6px;
        selection-background-color: {selection};
        selection-color: {text};
    }}
    QTableView::item {{ padding: 4px; }}
    QHeaderView::section {{
        background: {bg};
        color: {muted};
        border: none;
        border-bottom: 1px solid {border};
        padding: 6px;
        font-weight: 600;
    }}
    QProgressBar {{
        border: 1px solid {border};
        border-radius: 6px;
        background: {input};
        text-align: center;
        min-height: 16px;
    }}
    QProgressBar::chunk {{ background: {primary}; border-radius: 6px; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; }}
    QCheckBox, QRadioButton {{ background: transparent; }}
    QToolTip {{ background: {card}; color: {text}; border: 1px solid {border}; }}
    """
