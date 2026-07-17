# -*- coding: utf-8 -*-
"""
login_dialog.py  (UI层 - 登录对话框)
========================================
本地单机多账户登录，进入软件前先验证身份，之后主窗口会根据角色
只显示对应权限的功能页面。
"""

from typing import Optional, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox
)

from ui_layer.widgets import PrimaryButton, GhostButton


class LoginDialog(QDialog):

    def __init__(self, user_repo, parent=None):
        super().__init__(parent)
        self.user_repo = user_repo
        self.authenticated_user: Optional[Dict] = None
        self.setWindowTitle("墨算 InkMatrix 登录")
        self.setMinimumWidth(360)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)

        title = QLabel("墨算 InkMatrix")
        title.setStyleSheet("font-size:20px; font-weight:800; color:#0d9488;")
        root.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        subtitle = QLabel("请登录后使用")
        subtitle.setStyleSheet("color:#64748b; font-size:12px;")
        root.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(10)
        root.addWidget(QLabel("用户名："))
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("首次使用请输入 admin")
        root.addWidget(self.username_edit)

        root.addWidget(QLabel("密码："))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.returnPressed.connect(self._on_login)
        root.addWidget(self.password_edit)

        hint = QLabel("首次使用默认账户：admin / admin123，登录后请到【账户管理】修改密码。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94a3b8; font-size:11px;")
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        cancel_btn = GhostButton("退出程序")
        cancel_btn.clicked.connect(self.reject)
        login_btn = PrimaryButton("登录")
        login_btn.clicked.connect(self._on_login)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(login_btn)
        root.addLayout(btn_row)

    def _on_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "提示", "请输入用户名和密码。")
            return

        locked_until = self.user_repo.is_locked(username)
        if locked_until:
            QMessageBox.warning(
                self, "账户已锁定",
                f"密码连续输错次数过多，账户已被临时锁定，请在 {locked_until} 之后再试。\n"
                f"（这是防止有人暴力猜密码的保护机制）"
            )
            return

        if not self.user_repo.verify_password(username, password):
            record = self.user_repo.get_by_username(username)
            remaining = None
            if record is not None:
                remaining = self.user_repo.MAX_FAILED_ATTEMPTS - record.get("failed_attempts", 0)
            msg = "用户名或密码不正确。"
            if remaining is not None and 0 < remaining <= 3:
                msg += f"\n还有 {remaining} 次机会，超过后账户会被临时锁定。"
            QMessageBox.warning(self, "登录失败", msg)
            self.password_edit.clear()
            return
        self.authenticated_user = self.user_repo.get_by_username(username)
        self.accept()
