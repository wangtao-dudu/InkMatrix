# -*- coding: utf-8 -*-
"""
company_info_page.py  (UI层 - 公司信息设置页面)
====================================================
维护导出Word工单时用到的公司抬头信息（名称/联系方式/地址/Logo）。
"""

import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFormLayout,
    QFileDialog, QMessageBox
)

from ui_layer.widgets import Card, PrimaryButton, GhostButton

_LOGO_STORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "assets"
)


class CompanyInfoPage(QWidget):

    def __init__(self, company_repo, parent=None):
        super().__init__(parent)
        self.company_repo = company_repo
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("公司信息设置")
        title.setObjectName("PageTitle")
        subtitle = QLabel("填写公司名称、联系方式与Logo，导出Word工单时会自动打印在文档抬头")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        card = Card()
        lay = card.body_layout

        logo_row = QHBoxLayout()
        self.logo_preview = QLabel("暂无Logo")
        self.logo_preview.setFixedSize(120, 60)
        self.logo_preview.setStyleSheet("border:1px dashed #cbd5e1; border-radius:6px; color:#94a3b8;")
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_row.addWidget(self.logo_preview)

        logo_btn_col = QVBoxLayout()
        upload_logo_btn = PrimaryButton("上传Logo图片")
        upload_logo_btn.clicked.connect(self._on_upload_logo)
        clear_logo_btn = GhostButton("移除Logo")
        clear_logo_btn.clicked.connect(self._on_clear_logo)
        logo_btn_col.addWidget(upload_logo_btn)
        logo_btn_col.addWidget(clear_logo_btn)
        logo_row.addLayout(logo_btn_col)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：某某包装制品有限公司")
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("例如：0755-12345678")
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("例如：广东省深圳市XX区XX路88号")
        self.slogan_edit = QLineEdit()
        self.slogan_edit.setPlaceholderText("选填：公司口号/一句话简介")
        form.addRow("公司名称：", self.name_edit)
        form.addRow("联系电话：", self.phone_edit)
        form.addRow("地址：", self.address_edit)
        form.addRow("口号/简介：", self.slogan_edit)
        lay.addLayout(form)

        save_btn = PrimaryButton("💾 保存公司信息")
        save_btn.clicked.connect(self._on_save)
        lay.addWidget(save_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#16a34a; font-weight:600;")
        lay.addWidget(self.status_label)

        root.addWidget(card)

        # ── 关于与更新 ──────────────────────────────────────────────
        about_card = Card("关于与更新")
        alay = about_card.body_layout

        from hal_layer.update_service import APP_VERSION, DATA_SCHEMA_VERSION
        ver_label = QLabel(
            f"当前软件版本：<b>v{APP_VERSION}</b>　　数据格式版本：<b>v{DATA_SCHEMA_VERSION}</b>"
        )
        ver_label.setStyleSheet("font-size:13px;")
        alay.addWidget(ver_label)

        # 更新服务器地址：客户可以填自己的服务器/对象存储上那个 version.json 的地址。
        # 默认留空——填了才会去检查，不填就当作没有云端更新（纯单机用户不受打扰）。
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("更新检查地址："))
        self.update_url_edit = QLineEdit()
        self.update_url_edit.setPlaceholderText(
            "选填，例如 https://你的服务器/inkmatrix/version.json"
        )
        url_row.addWidget(self.update_url_edit, 1)
        alay.addLayout(url_row)

        check_btn = GhostButton("🔄 检查更新")
        check_btn.clicked.connect(self._on_check_update)
        alay.addWidget(check_btn)

        self.update_status = QLabel("")
        self.update_status.setWordWrap(True)
        self.update_status.setStyleSheet("font-size:12px; color:#475569;")
        alay.addWidget(self.update_status)

        root.addWidget(about_card, 1)

    def _on_check_update(self):
        """
        主动检查有没有新版本。

        只做检查+提示，不自动下载安装——桌面软件自动覆盖安装涉及权限、
        进程占用等一堆坑，是另一个工程。这里先把"能感知到更新"做出来：
        查到有新版就给个下载链接，让用户自己去下。
        """
        from hal_layer.update_service import check_for_update, summarize

        url = self.update_url_edit.text().strip()
        if not url:
            self.update_status.setText(
                "没有填更新检查地址。如果你上了云服务器，把服务器上 version.json 的"
                "网址填进去，就能检查更新了。纯单机使用可以忽略这一项。"
            )
            return

        self.update_status.setText("正在检查……")
        self.update_status.repaint()
        result = check_for_update(url)
        msg = summarize(result)

        if result.get("update_available") or result.get("force_update"):
            dl = result.get("download_url", "")
            notes = result.get("release_notes", "")
            full = msg
            if notes:
                full += f"\n\n更新内容：{notes}"
            if dl:
                full += f"\n\n下载地址：{dl}"
            self.update_status.setText(full)
            box = QMessageBox(self)
            box.setWindowTitle("发现新版本")
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(full)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
        else:
            self.update_status.setText(msg)

    def _load(self):
        info = self.company_repo.load()
        self.name_edit.setText(info.get("company_name", ""))
        self.phone_edit.setText(info.get("contact_phone", ""))
        self.address_edit.setText(info.get("address", ""))
        self.slogan_edit.setText(info.get("slogan", ""))
        self._logo_path = info.get("logo_path", "")
        self._refresh_logo_preview()

    def _refresh_logo_preview(self):
        if self._logo_path and os.path.exists(self._logo_path):
            pix = QPixmap(self._logo_path)
            if not pix.isNull():
                self.logo_preview.setPixmap(
                    pix.scaled(120, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                return
        self.logo_preview.setText("暂无Logo")
        self.logo_preview.setPixmap(QPixmap())

    def _on_upload_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择Logo图片", "", "图片文件 (*.png *.jpg *.jpeg)")
        if not path:
            return
        os.makedirs(_LOGO_STORE_DIR, exist_ok=True)
        ext = os.path.splitext(path)[1] or ".png"
        dest = os.path.join(_LOGO_STORE_DIR, f"company_logo{ext}")
        try:
            shutil.copy(path, dest)
        except Exception as exc:
            QMessageBox.warning(self, "上传失败", f"无法复制Logo文件：{exc}")
            return
        self._logo_path = dest
        self._refresh_logo_preview()

    def _on_clear_logo(self):
        self._logo_path = ""
        self._refresh_logo_preview()

    def _on_save(self):
        info = {
            "company_name": self.name_edit.text().strip(),
            "contact_phone": self.phone_edit.text().strip(),
            "address": self.address_edit.text().strip(),
            "slogan": self.slogan_edit.text().strip(),
            "logo_path": getattr(self, "_logo_path", ""),
        }
        self.company_repo.save(info)
        self.status_label.setText("✅ 已保存，导出工单时会使用这份抬头信息。")
