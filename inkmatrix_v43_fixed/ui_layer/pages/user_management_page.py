# -*- coding: utf-8 -*-
"""
user_management_page.py  (UI层 - 账户管理，层级账户体系版 v40)
================================================================
重做了两件事：

【1】修掉一个严重的权限漏洞
    旧版本里，所有拥有"账户管理"权限的账户地位完全平等——任何一个管理员
    都能修改主账户 admin 的权限。这是设计缺陷。

    现在是三级层级账户：
      · 主账户 (super)   ——  admin。最高权限，任何人都动不了它。可以创建
                            子管理员，并给每个子管理员分配"能建几个子账户"配额。
      · 子管理员 (admin) ——  admin 创建的下级管理员。【只能看到、只能管理
                            自己创建的账户】，看不到 admin、也看不到别的子
                            管理员。而且【不能再创建管理员】——防止无限繁殖。
      · 员工 (staff)     ——  普通账户，进不了这个页面。

【2】重新设计界面
    从"一张挤满字段的表格"改成：左边清爽的账户卡片列表（类型徽章 + 归属 +
    配额），右边分组清晰的资料面板。子管理员登录时，主账户专属功能自动隐藏。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QMessageBox, QCheckBox, QGridLayout, QScrollArea, QDoubleSpinBox,
    QSpinBox, QFrame, QButtonGroup, QRadioButton,
)

from dal_layer.data_manager import ROLE_LIST, ROLE_PERMISSIONS, PAGE_LABELS, UserRepository
from ui_layer.widgets import Card, PrimaryButton, GhostButton, DangerButton


_TYPE_STYLE = {
    "super": ("#7c3aed", "主账户"),
    "admin": ("#0d9488", "管理员"),
    "staff": ("#64748b", "员工"),
}


class _AccountRow(QFrame):
    """账户列表里的一行——卡片式，一眼看清是谁、什么类型、归属、状态。"""

    clicked = pyqtSignal(str)

    def __init__(self, record: dict, subtitle: str, selected: bool, parent=None):
        super().__init__(parent)
        self._username = record.get("username", "")
        self.setObjectName("AccountRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        atype = UserRepository.account_type_of(record)
        color, type_label = _TYPE_STYLE.get(atype, _TYPE_STYLE["staff"])
        border = color if selected else "#e2e8f0"
        bg = "#f8fafc" if selected else "#ffffff"
        self.setStyleSheet(
            f"#AccountRow {{ background:{bg}; border:1px solid {border}; "
            f"border-left:4px solid {color}; border-radius:10px; }}"
            f"#AccountRow:hover {{ background:#f1f5f9; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        avatar = QLabel((record.get("display_name") or "?")[:1])
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background:{color}; color:white; border-radius:19px; "
            f"font-size:16px; font-weight:700;"
        )
        lay.addWidget(avatar)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel(record.get("display_name", ""))
        name.setStyleSheet("font-size:14px; font-weight:700; color:#0f172a;")
        name_row.addWidget(name)
        type_badge = QLabel(type_label)
        type_badge.setStyleSheet(
            f"background:{color}; color:white; border-radius:8px; "
            f"padding:1px 8px; font-size:10px; font-weight:600;"
        )
        name_row.addWidget(type_badge)
        if record.get("locked_until"):
            lock = QLabel("🔒 已锁定")
            lock.setStyleSheet("color:#b91c1c; font-size:10px; font-weight:600;")
            name_row.addWidget(lock)
        name_row.addStretch(1)
        mid.addLayout(name_row)

        sub = QLabel(subtitle)
        sub.setStyleSheet("font-size:11px; color:#94a3b8;")
        mid.addWidget(sub)
        lay.addLayout(mid, 1)

    def mousePressEvent(self, event):
        self.clicked.emit(self._username)
        super().mousePressEvent(event)


class UserManagementPage(QWidget):

    _ASSIGNABLE_KEYS = list(UserRepository.ALL_PAGE_KEYS)

    def __init__(self, user_repo, current_username: str, ink_repo=None,
                 current_user: dict = None, parent=None):
        super().__init__(parent)
        self.user_repo = user_repo
        self.current_username = current_username
        self.ink_repo = ink_repo
        self.current_user = current_user or user_repo.get_by_username(current_username) or {}
        self._viewer_type = UserRepository.account_type_of(self.current_user)
        self._editing_username = None
        self._permission_checks = {}
        self._ink_alloc_checks = {}
        self._build_ui()
        self.refresh()

    # ==================================================================
    #  界面骨架
    # ==================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("账户管理")
        title.setStyleSheet("font-size:22px; font-weight:800; color:#0f172a;")
        root.addWidget(title)

        if self._viewer_type == "super":
            sub_txt = ("你是主账户，可以管理所有账户、创建下级管理员，并给每位管理员"
                       "分配可创建的子账户数量。")
        else:
            sub_txt = ("你是管理员，可以创建和管理自己名下的员工账户。"
                       "（主账户和其他管理员的账户对你不可见）")
        subtitle = QLabel(sub_txt)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size:12px; color:#64748b;")
        root.addWidget(subtitle)

        self.quota_bar = QLabel("")
        self.quota_bar.setWordWrap(True)
        self.quota_bar.setVisible(False)
        self.quota_bar.setStyleSheet(
            "background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af; "
            "border-radius:8px; padding:8px 12px; font-size:12px;"
        )
        root.addWidget(self.quota_bar)

        body = QHBoxLayout()
        body.setSpacing(16)

        # 左：账户列表
        left_card = Card("账户列表")
        left_lay = left_card.body_layout
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索姓名 / 账号…")
        self.search_edit.textChanged.connect(self.refresh)
        left_lay.addWidget(self.search_edit)

        new_btn = PrimaryButton("＋ 新建账户")
        new_btn.clicked.connect(self._exit_edit_mode)
        left_lay.addWidget(new_btn)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_container = QWidget()
        self.list_vlay = QVBoxLayout(self.list_container)
        self.list_vlay.setContentsMargins(0, 0, 6, 0)
        self.list_vlay.setSpacing(8)
        self.list_vlay.addStretch(1)
        self.list_scroll.setWidget(self.list_container)
        left_lay.addWidget(self.list_scroll, 1)
        left_card.setMinimumWidth(330)
        left_card.setMaximumWidth(400)
        body.addWidget(left_card)

        # 右：资料面板
        right_card = Card("账户资料")
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_inner = QWidget()
        self.form_lay = QVBoxLayout(right_inner)
        self.form_lay.setContentsMargins(4, 4, 8, 4)
        self.form_lay.setSpacing(12)
        right_scroll.setWidget(right_inner)
        right_card.body_layout.addWidget(right_scroll)
        self._build_form(self.form_lay)
        body.addWidget(right_card, 1)

        root.addLayout(body, 1)

    def _build_form(self, lay):
        self.mode_banner = QLabel("")
        self.mode_banner.setWordWrap(True)
        self.mode_banner.setStyleSheet(
            "background:#fffbeb; border:1px solid #fde68a; color:#92400e; "
            "border-radius:8px; padding:8px 12px; font-size:12px;"
        )
        self.mode_banner.setVisible(False)
        lay.addWidget(self.mode_banner)

        lay.addWidget(self._section_label("基本信息"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("姓名"), 0, 0)
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setPlaceholderText("例如：李师傅")
        grid.addWidget(self.display_name_edit, 0, 1)
        grid.addWidget(QLabel("登录账号"), 1, 0)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("登录用，建好后不可改")
        grid.addWidget(self.username_edit, 1, 1)
        grid.addWidget(QLabel("登录密码"), 2, 0)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("至少4位")
        grid.addWidget(self.password_edit, 2, 1)
        lay.addLayout(grid)

        self.type_section = self._section_label("账户类型")
        lay.addWidget(self.type_section)
        self.type_group = QButtonGroup(self)
        type_row = QHBoxLayout()
        self.radio_staff = QRadioButton("员工账户")
        self.radio_admin = QRadioButton("管理员（可管理自己创建的账户）")
        self.radio_staff.setChecked(True)
        self.type_group.addButton(self.radio_staff)
        self.type_group.addButton(self.radio_admin)
        self.radio_staff.toggled.connect(self._on_type_changed)
        type_row.addWidget(self.radio_staff)
        type_row.addWidget(self.radio_admin)
        type_row.addStretch(1)
        self.type_row_widget = QWidget()
        self.type_row_widget.setLayout(type_row)
        lay.addWidget(self.type_row_widget)

        can_create_admin = (self._viewer_type == "super")
        self.radio_admin.setVisible(can_create_admin)
        if not can_create_admin:
            self.type_section.setVisible(False)
            self.type_row_widget.setVisible(False)

        self.quota_widget = QWidget()
        quota_lay = QHBoxLayout(self.quota_widget)
        quota_lay.setContentsMargins(0, 0, 0, 0)
        quota_lay.addWidget(QLabel("可创建子账户数量上限"))
        self.quota_spin = QSpinBox()
        self.quota_spin.setRange(1, 999)
        self.quota_spin.setValue(5)
        quota_lay.addWidget(self.quota_spin)
        quota_lay.addStretch(1)
        self.quota_widget.setVisible(False)
        lay.addWidget(self.quota_widget)

        lay.addWidget(self._section_label("快速套用角色模板（选完可再手动微调）"))
        self.role_combo = QComboBox()
        self.role_combo.addItem("— 不套用模板 —", None)
        for r in ROLE_LIST:
            self.role_combo.addItem(r, r)
        self.role_combo.currentIndexChanged.connect(self._on_role_template)
        lay.addWidget(self.role_combo)

        lay.addWidget(self._section_label("可访问的功能页面"))
        perm_grid = QGridLayout()
        perm_grid.setSpacing(6)
        added = 0
        for key in self._ASSIGNABLE_KEYS:
            if key == "users" and self._viewer_type != "super":
                continue
            cb = QCheckBox(PAGE_LABELS.get(key, key))
            self._permission_checks[key] = cb
            perm_grid.addWidget(cb, added // 2, added % 2)
            added += 1
        lay.addLayout(perm_grid)

        self.alloc_section = self._section_label(
            "分配油墨额度（员工只能用分到的油墨，且有用量上限）")
        lay.addWidget(self.alloc_section)
        self.alloc_container = QWidget()
        self.alloc_vlay = QVBoxLayout(self.alloc_container)
        self.alloc_vlay.setContentsMargins(0, 0, 0, 0)
        self.alloc_vlay.setSpacing(4)
        self._build_ink_allocations()
        lay.addWidget(self.alloc_container)

        lay.addSpacing(6)
        btn_row = QHBoxLayout()
        self.save_btn = PrimaryButton("＋ 创建账户")
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        self.reset_pw_btn = GhostButton("🔑 重置密码")
        self.reset_pw_btn.clicked.connect(self._on_reset_password)
        self.reset_pw_btn.setVisible(False)
        btn_row.addWidget(self.reset_pw_btn)
        self.cancel_btn = GhostButton("取消编辑")
        self.cancel_btn.clicked.connect(self._exit_edit_mode)
        self.cancel_btn.setVisible(False)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        self.delete_btn = DangerButton("－ 删除")
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setVisible(False)
        btn_row.addWidget(self.delete_btn)
        lay.addLayout(btn_row)
        lay.addStretch(1)

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:12px; font-weight:700; color:#334155; "
                          "border-bottom:1px solid #e2e8f0; padding-bottom:4px;")
        return lbl

    def _build_ink_allocations(self):
        while self.alloc_vlay.count():
            item = self.alloc_vlay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._ink_alloc_checks = {}
        inks = self.ink_repo.load_all() if self.ink_repo else []
        if not inks:
            hint = QLabel("（油墨库还没有油墨，先去油墨库添加）")
            hint.setStyleSheet("color:#94a3b8; font-size:11px;")
            self.alloc_vlay.addWidget(hint)
            return
        for ink in inks:
            code = ink.get("code", "")
            row = QHBoxLayout()
            cb = QCheckBox(f"{ink.get('name','')} [{code}]")
            spin = QDoubleSpinBox()
            spin.setRange(0, 1000000)
            spin.setDecimals(0)
            spin.setValue(500)
            spin.setSuffix(" ml")
            spin.setEnabled(False)
            cb.toggled.connect(spin.setEnabled)
            row.addWidget(cb, 1)
            row.addWidget(spin)
            w = QWidget()
            w.setLayout(row)
            self.alloc_vlay.addWidget(w)
            self._ink_alloc_checks[code] = (cb, spin)

    # ==================================================================
    #  列表刷新（核心：可见范围隔离）
    # ==================================================================

    def refresh(self):
        visible = self.user_repo.visible_accounts_for(self.current_user)
        kw = self.search_edit.text().strip().lower()
        if kw:
            visible = [u for u in visible
                       if kw in (u.get("display_name", "") or "").lower()
                       or kw in (u.get("username", "") or "").lower()]

        order = {"super": 0, "admin": 1, "staff": 2}
        visible.sort(key=lambda u: (order.get(UserRepository.account_type_of(u), 9),
                                    u.get("created_at", "")))

        while self.list_vlay.count() > 1:
            item = self.list_vlay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for rec in visible:
            subtitle = self._row_subtitle(rec)
            row = _AccountRow(rec, subtitle,
                              selected=(rec.get("username") == self._editing_username))
            row.clicked.connect(self._on_row_clicked)
            self.list_vlay.insertWidget(self.list_vlay.count() - 1, row)

        self._update_quota_bar()

    def _row_subtitle(self, rec):
        parts = [f"@{rec.get('username','')}"]
        atype = UserRepository.account_type_of(rec)
        if atype == "admin":
            used = self.user_repo.count_sub_accounts(rec.get("username", ""))
            cap = rec.get("max_sub_accounts")
            parts.append(f"已建 {used}/{cap} 个子账户" if cap is not None
                         else f"已建 {used} 个子账户")
        elif atype == "staff":
            creator = rec.get("created_by")
            if creator and self._viewer_type == "super":
                parts.append(f"由 {creator} 创建")
        return "　·　".join(parts)

    def _update_quota_bar(self):
        if self._viewer_type != "admin":
            self.quota_bar.setVisible(False)
            return
        cap = self.current_user.get("max_sub_accounts")
        used = self.user_repo.count_sub_accounts(self.current_username)
        if cap is None:
            self.quota_bar.setText(f"你已创建 {used} 个员工账户（无数量限制）。")
        else:
            left = cap - used
            self.quota_bar.setText(
                f"你的子账户配额：已用 <b>{used}</b> / 共 <b>{cap}</b> 个，"
                f"还能创建 <b>{max(0, left)}</b> 个。"
                + ("　配额已满，如需更多请联系主账户。" if left <= 0 else "")
            )
        self.quota_bar.setVisible(True)

    # ==================================================================
    #  交互
    # ==================================================================

    def _on_type_changed(self):
        is_admin = self.radio_admin.isChecked()
        self.quota_widget.setVisible(is_admin and self._viewer_type == "super")
        if is_admin:
            idx = self.role_combo.findData("管理员")
            if idx >= 0:
                self.role_combo.setCurrentIndex(idx)

    def _on_role_template(self):
        role = self.role_combo.currentData()
        if role is None:
            return
        perms = ROLE_PERMISSIONS.get(role, set())
        for key, cb in self._permission_checks.items():
            cb.setChecked(key in perms)

    def _on_row_clicked(self, username):
        rec = self.user_repo.get_by_username(username)
        if rec is None:
            return
        if not self.user_repo.can_manage_target(self.current_user, username):
            QMessageBox.information(
                self, "无权操作",
                "你没有权限管理这个账户。管理员只能管理自己创建的员工账户。"
            )
            return
        self._enter_edit_mode(rec)

    def _enter_edit_mode(self, rec):
        self._editing_username = rec.get("username")
        atype = UserRepository.account_type_of(rec)

        self.display_name_edit.setText(rec.get("display_name", ""))
        self.username_edit.setText(rec.get("username", ""))
        self.username_edit.setEnabled(False)
        self.password_edit.clear()
        self.password_edit.setEnabled(False)
        self.password_edit.setPlaceholderText("如需改密码，用下方【重置密码】")

        if atype == "admin":
            self.radio_admin.setChecked(True)
        else:
            self.radio_staff.setChecked(True)
        self.radio_staff.setEnabled(False)
        self.radio_admin.setEnabled(False)
        if atype == "admin" and self._viewer_type == "super":
            self.quota_widget.setVisible(True)
            self.quota_spin.setValue(rec.get("max_sub_accounts") or 5)

        perms = UserRepository.effective_permissions(rec)
        for key, cb in self._permission_checks.items():
            cb.setChecked(key in perms)

        allocs = rec.get("ink_allocations") or {}
        for code, (cb, spin) in self._ink_alloc_checks.items():
            if code in allocs:
                cb.setChecked(True)
                v = allocs[code]
                spin.setValue(float(v.get("limit_ml", 0)) if isinstance(v, dict) else float(v))
            else:
                cb.setChecked(False)

        is_super_target = (atype == "super")
        self.save_btn.setText("💾 保存修改")
        self.save_btn.setVisible(not is_super_target)
        self.reset_pw_btn.setVisible(
            self.user_repo.can_manage_target(self.current_user, rec.get("username")))
        self.cancel_btn.setVisible(True)
        can_delete = (not is_super_target
                      and rec.get("username") != self.current_username
                      and self.user_repo.can_manage_target(self.current_user, rec.get("username")))
        self.delete_btn.setVisible(can_delete)

        banner = f"正在编辑：{rec.get('display_name','')}（@{rec.get('username','')}）"
        if is_super_target:
            banner += "　—— 这是主账户，权限受保护，不能在此修改。"
        self.mode_banner.setText(banner)
        self.mode_banner.setVisible(True)
        for cb in self._permission_checks.values():
            cb.setEnabled(not is_super_target)

    def _exit_edit_mode(self):
        self._editing_username = None
        self.display_name_edit.clear()
        self.username_edit.clear()
        self.username_edit.setEnabled(True)
        self.password_edit.clear()
        self.password_edit.setEnabled(True)
        self.password_edit.setPlaceholderText("至少4位")
        self.radio_staff.setEnabled(True)
        self.radio_admin.setEnabled(True)
        self.radio_staff.setChecked(True)
        self.quota_widget.setVisible(False)
        self.role_combo.setCurrentIndex(0)
        for cb in self._permission_checks.values():
            cb.setChecked(False)
            cb.setEnabled(True)
        for code, (cb, spin) in self._ink_alloc_checks.items():
            cb.setChecked(False)
        self.save_btn.setText("＋ 创建账户")
        self.save_btn.setVisible(True)
        self.reset_pw_btn.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.delete_btn.setVisible(False)
        self.mode_banner.setVisible(False)
        self.refresh()

    # ==================================================================
    #  保存 / 删除 / 重置密码
    # ==================================================================

    def _collect_permissions(self):
        return [k for k, cb in self._permission_checks.items() if cb.isChecked()]

    def _collect_allocations(self):
        return {code: spin.value()
                for code, (cb, spin) in self._ink_alloc_checks.items() if cb.isChecked()}

    def _on_save(self):
        editing = self._editing_username
        display_name = self.display_name_edit.text().strip()
        if not display_name:
            QMessageBox.warning(self, "提示", "请填写姓名。")
            return
        permissions = self._collect_permissions()
        allocations = self._collect_allocations()

        # ===== 编辑已有账户 =====
        if editing:
            if not self.user_repo.can_manage_target(self.current_user, editing):
                QMessageBox.warning(self, "无权操作", "你没有权限修改这个账户。")
                return
            if self.user_repo.would_orphan_admin(editing, new_permissions=permissions):
                QMessageBox.critical(
                    self, "不能这样改",
                    "这是系统里最后一个拥有账户管理权限的账户，不能取消它的账户管理权限，"
                    "否则将没有任何人能管理账户。"
                )
                return
            self.user_repo.update_user(
                editing, display_name=display_name,
                permissions=permissions, ink_allocations=allocations,
            )
            if self.radio_admin.isChecked() and self._viewer_type == "super":
                rec = self.user_repo.get_by_username(editing)
                if rec is not None:
                    rec["max_sub_accounts"] = self.quota_spin.value()
                    self.user_repo.upsert(rec)
            QMessageBox.information(self, "已保存", f"账户【{display_name}】已更新。")
            self._exit_edit_mode()
            return

        # ===== 新建账户 =====
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "提示", "请填写登录账号和密码。")
            return
        if len(password) < 4:
            QMessageBox.warning(self, "提示", "密码至少4位。")
            return
        if self.user_repo.get_by_username(username):
            QMessageBox.warning(self, "提示", "这个登录账号已存在，换一个。")
            return

        want_admin = self.radio_admin.isChecked()

        if want_admin and not UserRepository.can_create_admin(self.current_user):
            QMessageBox.critical(
                self, "无权操作",
                "只有主账户能创建管理员。你作为管理员，只能创建员工账户。"
            )
            return

        if self._viewer_type == "admin":
            cap = self.current_user.get("max_sub_accounts")
            if cap is not None:
                used = self.user_repo.count_sub_accounts(self.current_username)
                if used >= cap:
                    QMessageBox.warning(
                        self, "配额已满",
                        f"你的子账户配额是 {cap} 个，已经用完。如需创建更多，请联系主账户。"
                    )
                    return

        if want_admin:
            account_type = "admin"
            max_sub = self.quota_spin.value()
            if "users" not in permissions:
                permissions = sorted(set(permissions) | {"users"})
        else:
            account_type = "staff"
            max_sub = None
            permissions = [p for p in permissions if p != "users"]

        if not permissions:
            confirm = QMessageBox.question(
                self, "确认",
                "没有勾选任何可访问页面，这个账户登录后看不到任何功能，确定创建吗？"
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        ok = self.user_repo.create_user(
            username, display_name, password,
            role="管理员" if want_admin else "员工",
            permissions=permissions, ink_allocations=allocations,
            account_type=account_type, created_by=self.current_username,
            max_sub_accounts=max_sub,
        )
        if not ok:
            QMessageBox.warning(self, "提示", "创建失败，账号可能已存在。")
            return
        QMessageBox.information(
            self, "已创建",
            f"账户【{display_name}】创建成功。" +
            ("　这是一个管理员账户，可以管理自己创建的员工。" if want_admin else "")
        )
        self._exit_edit_mode()

    def _on_reset_password(self):
        if not self._editing_username:
            return
        if not self.user_repo.can_manage_target(self.current_user, self._editing_username):
            QMessageBox.warning(self, "无权操作", "你没有权限重置这个账户的密码。")
            return
        from PyQt6.QtWidgets import QInputDialog
        new_pw, ok = QInputDialog.getText(
            self, "重置密码", f"给账户【{self._editing_username}】设置新密码：",
            QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        if len(new_pw) < 4:
            QMessageBox.warning(self, "提示", "密码至少4位，未修改。")
            return
        self.user_repo.set_password(self._editing_username, new_pw)
        QMessageBox.information(self, "已重置", "密码已重置。")

    def _on_delete(self):
        username = self._editing_username
        if not username:
            return
        if username == self.current_username:
            QMessageBox.warning(self, "提示", "不能删除当前登录的账户。")
            return
        if not self.user_repo.can_manage_target(self.current_user, username):
            QMessageBox.warning(self, "无权操作", "你没有权限删除这个账户。")
            return
        if self.user_repo.would_orphan_admin(username, new_permissions=None):
            QMessageBox.critical(
                self, "不能删除",
                "这是系统里最后一个拥有账户管理权限的账户，删除后将没有人能管理账户。"
            )
            return
        rec = self.user_repo.get_by_username(username)
        extra = ""
        if rec and UserRepository.account_type_of(rec) == "admin":
            n = self.user_repo.count_sub_accounts(username)
            if n > 0:
                extra = (f"\n\n注意：这个管理员名下还有 {n} 个员工账户。删除后这些员工"
                         f"会失去归属（仍可登录，但没有管理员管理他们）。")
        confirm = QMessageBox.question(
            self, "确认删除",
            f"确定删除账户【{rec.get('display_name','') if rec else username}】吗？{extra}"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.user_repo.delete(username)
        QMessageBox.information(self, "已删除", "账户已删除。")
        self._exit_edit_mode()
