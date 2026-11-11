"""登录预览。账号只在本机确认，还不会连接服务器。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout

from wordflow.ui.common import tell


class LoginWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("登录")
        self.setObjectName("shell")
        self.setModal(True)
        self.setFixedSize(420, 520)
        self.account_name = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 28, 22, 22)
        frame = QFrame()
        frame.setObjectName("stage")
        card = QVBoxLayout(frame)
        card.setContentsMargins(28, 28, 28, 24)
        card.setSpacing(12)
        mark = QLabel("词")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(56, 56)
        title = QLabel("WordFlow")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("登录后进入词流")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        self.account = QLineEdit()
        self.account.setPlaceholderText("账号")
        self.password = QLineEdit()
        self.password.setPlaceholderText("密码")
        self.password.setEchoMode(QLineEdit.Password)
        self.account.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        enter = QPushButton("登录")
        enter.setObjectName("heroPrimary")
        enter.clicked.connect(self._submit)
        hint = QLabel("当前是本地预览。填写任意账号即可进入，密码可以留空。服务器登录以后再接。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        card.addWidget(mark, 0, Qt.AlignHCenter)
        card.addWidget(title)
        card.addWidget(subtitle)
        card.addSpacing(8)
        card.addWidget(self.account)
        card.addWidget(self.password)
        card.addWidget(enter)
        card.addWidget(hint)
        layout.addWidget(frame)

    def _submit(self) -> None:
        name = self.account.text().strip()
        if not name:
            tell(self, "请先填写账号。", "warn")
            return
        self.account_name = name
        self.accept()
