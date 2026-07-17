# -*- coding: utf-8 -*-
"""
production_page.py  (UI层 - 生产追踪页面)
==============================================
车间日常管理：打样/调机时上传照片，手动录入预计完成时间、预计产量，
维护每台丝印机的当前运行状态，供老板/管理层查看车间整体情况。

⚠️ 重要说明（避免误解功能边界）：
    这里的"机台运行状态"是【人工手动录入】的记录看板，不是接了传感器
    /PLC实时读数的工业物联网监控——机台本身不会自动上报数据，需要
    操作员每次调机/开工/完工时手动进来点一下更新状态、传张照片。
    这跟真正的"机台联网实时监控"是两回事，但对于"车间里发生了什么、
    进度到哪了"这种日常管理记录需求，已经够用。
"""

import os
import shutil
import datetime
from typing import List, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QDoubleSpinBox, QDateTimeEdit, QTextEdit, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QFrame, QGridLayout,
    QDialog
)
from PyQt6.QtCore import QDateTime

from ui_layer.widgets import Card, PrimaryButton, GhostButton, DangerButton, Badge, ResponsiveRow
from ui_layer.machine_widget import MachineAnimationWidget

_PHOTO_STORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "assets", "production_photos"
)

STATUS_META = {
    "调机中": {"color": "#d97706"},
    "生产中": {"color": "#0d9488"},
    "已完成": {"color": "#16a34a"},
    "异常暂停": {"color": "#dc2626"},
}


class ProductionPage(QWidget):

    def __init__(self, production_repo, machine_repo, parent=None):
        super().__init__(parent)
        self.production_repo = production_repo
        self.machine_repo = machine_repo
        self._photo_path: Optional[str] = None
        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("生产追踪")
        title.setObjectName("PageTitle")
        subtitle = QLabel("打样/调机记录 + 各台丝印机当前状态一览，供管理层实时掌握车间进度")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        # ---- 机台状态总览 ----
        root.addWidget(self._build_machine_overview_card())

        body = ResponsiveRow(breakpoint=900)
        body.add_panel(self._wrap_scrollable(self._build_new_record_card()), 1)
        body.add_panel(self._wrap_scrollable(self._build_history_card()), 2)
        root.addWidget(body, 1)

    @staticmethod
    def _wrap_scrollable(inner: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(inner)
        return scroll

    # ---------------- 机台状态总览 ----------------

    def _build_machine_overview_card(self) -> Card:
        self._overview_card = Card("机台当前状态一览")
        self._overview_grid = QGridLayout()
        self._overview_card.body_layout.addLayout(self._overview_grid)
        return self._overview_card

    def _refresh_machine_overview(self):
        while self._overview_grid.count():
            item = self._overview_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        machines = self.machine_repo.load_all()
        latest_by_machine = self.production_repo.latest_status_by_machine()

        if not machines:
            empty_label = QLabel("还没有录入任何机台，请在右侧\"新增记录\"里填机台名称并保存一条记录即可自动建档。")
            empty_label.setStyleSheet("color:#94a3b8;")
            self._overview_grid.addWidget(empty_label, 0, 0)
            return

        col_count = 3
        for i, m in enumerate(machines):
            latest = latest_by_machine.get(m["code"])
            card = self._build_machine_status_chip(m, latest)
            self._overview_grid.addWidget(card, i // col_count, i % col_count)

    def _build_machine_status_chip(self, machine: Dict, latest: Optional[Dict]) -> QFrame:
        chip = QFrame()
        chip.setObjectName("MachineChip")
        chip.setMinimumWidth(220)
        status = latest.get("status", "未知") if latest else "暂无记录"
        color = STATUS_META.get(status, {}).get("color", "#94a3b8")
        chip.setStyleSheet(
            f"#MachineChip {{ background-color:#ffffff; border:1px solid #e2e8f0; "
            f"border-left:4px solid {color}; border-radius:10px; padding:4px; }}"
        )
        outer = QHBoxLayout(chip)

        anim_widget = MachineAnimationWidget(status if latest else "已完成")
        outer.addWidget(anim_widget)

        lay = QVBoxLayout()
        name_label = QLabel(machine.get("name", machine.get("code", "")))
        name_label.setStyleSheet("font-weight:700; font-size:13px;")
        lay.addWidget(name_label)

        badge = Badge(status, bg_hex=color)
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)

        if latest:
            customer = latest.get("customer") or "-"
            product = latest.get("product_name") or "-"
            info = QLabel(
                f"客户：{customer}\n"
                f"产品：{product}\n"
                f"预计完成：{latest.get('expected_completion', '-')}\n"
                f"预计产量：{latest.get('expected_quantity', '-')}\n"
                f"更新于：{latest.get('updated_at', '-')}"
            )
        else:
            info = QLabel("暂无生产记录")
        info.setStyleSheet("color:#64748b; font-size:11px;")
        info.setWordWrap(True)
        lay.addWidget(info)
        outer.addLayout(lay, 1)
        return chip

    def _on_manage_machines(self):
        dlg = MachineManageDialog(self, self.machine_repo, self.production_repo)
        dlg.exec()
        self.refresh_all()

    # ---------------- 新增记录卡片 ----------------

    def _build_new_record_card(self) -> Card:
        card = Card("① 新增打样/生产记录")
        lay = card.body_layout

        lay.addWidget(QLabel("机台（没有的话直接输入新名称会自动建档）："))
        machine_row = QHBoxLayout()
        self.machine_combo = QComboBox()
        self.machine_combo.setEditable(True)
        machine_row.addWidget(self.machine_combo, 1)
        manage_machine_btn = GhostButton("⚙ 管理机台")
        manage_machine_btn.clicked.connect(self._on_manage_machines)
        machine_row.addWidget(manage_machine_btn)
        lay.addLayout(machine_row)

        lay.addWidget(QLabel("客户名称（选填）："))
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("例如：客户A")
        lay.addWidget(self.customer_edit)

        lay.addWidget(QLabel("关联产品/工单名称（选填）："))
        self.product_name_edit = QLineEdit()
        self.product_name_edit.setPlaceholderText("例如：客户A - 100ml白瓶套色")
        lay.addWidget(self.product_name_edit)

        lay.addWidget(QLabel("状态："))
        self.status_combo = QComboBox()
        self.status_combo.addItems(list(STATUS_META.keys()))
        lay.addWidget(self.status_combo)

        lay.addWidget(QLabel("预计完成时间："))
        self.expected_time_edit = QDateTimeEdit()
        self.expected_time_edit.setCalendarPopup(True)
        self.expected_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.expected_time_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600 * 4))
        lay.addWidget(self.expected_time_edit)

        lay.addWidget(QLabel("预计产量："))
        self.expected_qty_spin = QDoubleSpinBox()
        self.expected_qty_spin.setRange(0, 10000000)
        self.expected_qty_spin.setDecimals(0)
        lay.addWidget(self.expected_qty_spin)

        photo_row = QHBoxLayout()
        upload_photo_btn = PrimaryButton("📷 上传调机照片")
        upload_photo_btn.clicked.connect(self._on_upload_photo)
        photo_row.addWidget(upload_photo_btn)
        self.photo_status_label = QLabel("尚未上传")
        self.photo_status_label.setStyleSheet("color:#64748b; font-size:11px;")
        photo_row.addWidget(self.photo_status_label, 1)
        lay.addLayout(photo_row)

        self.photo_preview = QLabel()
        self.photo_preview.setFixedHeight(100)
        self.photo_preview.setStyleSheet("border:1px dashed #cbd5e1; border-radius:6px; color:#94a3b8;")
        self.photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_preview.setText("（照片预览）")
        lay.addWidget(self.photo_preview)

        lay.addWidget(QLabel("备注："))
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(70)
        lay.addWidget(self.notes_edit)

        save_btn = PrimaryButton("💾 保存记录")
        save_btn.clicked.connect(self._on_save_record)
        lay.addWidget(save_btn)

        return card

    def _on_upload_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择调机照片", "", "图片文件 (*.png *.jpg *.jpeg)")
        if not path:
            return
        os.makedirs(_PHOTO_STORE_DIR, exist_ok=True)
        ext = os.path.splitext(path)[1] or ".jpg"
        dest_name = f"photo_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
        dest = os.path.join(_PHOTO_STORE_DIR, dest_name)
        try:
            shutil.copy(path, dest)
        except Exception as exc:
            QMessageBox.warning(self, "上传失败", f"无法复制照片文件：{exc}")
            return
        self._photo_path = dest
        self.photo_status_label.setText(os.path.basename(dest))
        pix = QPixmap(dest)
        if not pix.isNull():
            self.photo_preview.setPixmap(
                pix.scaledToHeight(96, Qt.TransformationMode.SmoothTransformation)
            )

    def _on_save_record(self):
        machine_name = self.machine_combo.currentText().strip()
        if not machine_name:
            QMessageBox.warning(self, "提示", "请填写或选择机台名称。")
            return

        # 机台名称对应到机台编号：已存在则复用，不存在则自动建档
        machine_code = self.machine_combo.currentData()
        if not machine_code:
            existing = next((m for m in self.machine_repo.load_all() if m["name"] == machine_name), None)
            if existing:
                machine_code = existing["code"]
            else:
                machine_code = f"M-{len(self.machine_repo.load_all()) + 1:03d}"
                self.machine_repo.upsert({"code": machine_code, "name": machine_name})

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        record = {
            "id": f"PR-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
            "machine_code": machine_code,
            "machine_name": machine_name,
            "customer": self.customer_edit.text().strip(),
            "product_name": self.product_name_edit.text().strip(),
            "photo_path": self._photo_path or "",
            "status": self.status_combo.currentText(),
            "expected_completion": self.expected_time_edit.dateTime().toString("yyyy-MM-dd HH:mm"),
            "expected_quantity": self.expected_qty_spin.value(),
            "notes": self.notes_edit.toPlainText().strip(),
            "created_at": now_str,
            "updated_at": now_str,
        }
        self.production_repo.upsert(record)

        QMessageBox.information(self, "已保存", f"机台【{machine_name}】的生产记录已保存。")
        self._photo_path = None
        self.photo_status_label.setText("尚未上传")
        self.photo_preview.setPixmap(QPixmap())
        self.photo_preview.setText("（照片预览）")
        self.notes_edit.clear()
        self.customer_edit.clear()
        self.refresh_all()

    # ---------------- 历史记录卡片 ----------------

    def _build_history_card(self) -> Card:
        card = Card("② 生产记录历史（按更新时间倒序）")
        lay = card.body_layout

        self.history_table = QTableWidget(0, 8)
        self.history_table.setHorizontalHeaderLabels(
            ["机台", "客户", "关联产品", "状态", "预计完成时间", "预计产量", "照片", "更新时间"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.verticalHeader().setDefaultSectionSize(34)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.cellDoubleClicked.connect(self._on_history_double_clicked)
        lay.addWidget(self.history_table, 1)

        hint = QLabel("💡 双击【照片】列的行可以查看当次上传的调机照片大图。")
        hint.setStyleSheet("color:#94a3b8; font-size:11px;")
        lay.addWidget(hint)

        del_btn = DangerButton("－ 删除选中记录")
        del_btn.setMinimumHeight(34)
        del_btn.clicked.connect(self._on_delete_record)
        lay.addWidget(del_btn)

        return card

    def _refresh_history_table(self):
        records = self.production_repo.load_all()
        self.history_table.setRowCount(len(records))
        for row, r in enumerate(records):
            machine_item = QTableWidgetItem(r.get("machine_name", ""))
            machine_item.setData(Qt.ItemDataRole.UserRole, r["id"])
            customer_item = QTableWidgetItem(r.get("customer", "") or "-")
            product_item = QTableWidgetItem(r.get("product_name", "") or "-")
            status_item = QTableWidgetItem(r.get("status", ""))
            color = STATUS_META.get(r.get("status", ""), {}).get("color")
            if color:
                status_item.setForeground(QColor(color))
            time_item = QTableWidgetItem(r.get("expected_completion", ""))
            qty_item = QTableWidgetItem(f"{r.get('expected_quantity', 0):g}")
            photo_item = QTableWidgetItem("📷有照片" if r.get("photo_path") else "无")
            updated_item = QTableWidgetItem(r.get("updated_at", ""))
            for item in (machine_item, customer_item, product_item, status_item, time_item, qty_item, photo_item, updated_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(row, 0, machine_item)
            self.history_table.setItem(row, 1, customer_item)
            self.history_table.setItem(row, 2, product_item)
            self.history_table.setItem(row, 3, status_item)
            self.history_table.setItem(row, 4, time_item)
            self.history_table.setItem(row, 5, qty_item)
            self.history_table.setItem(row, 6, photo_item)
            self.history_table.setItem(row, 7, updated_item)

    def _on_history_double_clicked(self, row: int, col: int):
        if col != 6:
            return
        record_id = self.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        record = self.production_repo.get_by_id(record_id)
        if not record or not record.get("photo_path") or not os.path.exists(record["photo_path"]):
            QMessageBox.information(self, "提示", "这条记录没有上传照片。")
            return
        dlg_pix = QPixmap(record["photo_path"])
        preview_label = QLabel()
        preview_label.setPixmap(dlg_pix.scaledToWidth(500, Qt.TransformationMode.SmoothTransformation))
        from PyQt6.QtWidgets import QDialog, QVBoxLayout as _QV
        dlg = QDialog(self)
        dlg.setWindowTitle(f"调机照片 - {record.get('machine_name','')}")
        _QV(dlg).addWidget(preview_label)
        dlg.exec()

    def _on_delete_record(self):
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中要删除的记录。")
            return
        record_id = self.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(self, "确认删除", "确定要删除这条生产记录吗？")
        if confirm == QMessageBox.StandardButton.Yes:
            self.production_repo.delete(record_id)
            self.refresh_all()

    # ---------------- 统一刷新 ----------------

    def refresh_all(self):
        self._refresh_machine_combo()
        self._refresh_machine_overview()
        self._refresh_history_table()

    def _refresh_machine_combo(self):
        current_text = self.machine_combo.currentText()
        self.machine_combo.blockSignals(True)
        self.machine_combo.clear()
        for m in self.machine_repo.load_all():
            self.machine_combo.addItem(m["name"], m["code"])
        self.machine_combo.setCurrentText(current_text)
        self.machine_combo.blockSignals(False)


class MachineManageDialog(QDialog):
    """机台管理对话框：新增 / 删除 丝印机台档案。"""

    def __init__(self, parent, machine_repo, production_repo):
        super().__init__(parent)
        self.machine_repo = machine_repo
        self.production_repo = production_repo
        self.setWindowTitle("机台管理")
        self.setMinimumSize(420, 380)
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        root = QVBoxLayout(self)

        add_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("新机台名称，例如：3号丝印机")
        add_row.addWidget(self.name_edit, 1)
        add_btn = PrimaryButton("＋ 新增机台")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["编号", "名称"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 1)

        del_btn = DangerButton("－ 删除选中机台")
        del_btn.setMinimumHeight(34)
        del_btn.clicked.connect(self._on_delete)
        root.addWidget(del_btn)

        close_btn = GhostButton("关闭")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)

    def _refresh_table(self):
        machines = self.machine_repo.load_all()
        self.table.setRowCount(len(machines))
        for row, m in enumerate(machines):
            code_item = QTableWidgetItem(m["code"])
            code_item.setData(Qt.ItemDataRole.UserRole, m["code"])
            name_item = QTableWidgetItem(m["name"])
            self.table.setItem(row, 0, code_item)
            self.table.setItem(row, 1, name_item)

    def _on_add(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请填写机台名称。")
            return
        if any(m["name"] == name for m in self.machine_repo.load_all()):
            QMessageBox.warning(self, "提示", "该机台名称已存在。")
            return
        code = f"M-{len(self.machine_repo.load_all()) + 1:03d}"
        self.machine_repo.upsert({"code": code, "name": name})
        self.name_edit.clear()
        self._refresh_table()

    def _on_delete(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中要删除的机台。")
            return
        code = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        has_records = any(r.get("machine_code") == code for r in self.production_repo.load_all())
        msg = "确定要删除这台机台吗？"
        if has_records:
            msg += "\n注意：该机台已有生产记录，删除机台档案不会删除历史记录，但总览里将不再显示这台机器。"
        confirm = QMessageBox.question(self, "确认删除", msg)
        if confirm == QMessageBox.StandardButton.Yes:
            self.machine_repo.delete(code)
            self._refresh_table()
