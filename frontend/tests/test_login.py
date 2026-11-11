import os

from wordflow.ui.login import LoginWindow


def test_login_accepts_any_account_name():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QDialog

    QApplication.instance() or QApplication([])
    window = LoginWindow()
    window.account.setText("  ada  ")
    window.password.setText("")
    window._submit()
    assert window.account_name == "ada"
    assert window.result() == QDialog.Accepted
