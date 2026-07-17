# -*- coding: utf-8 -*-
"""
ink_import_dialog.py  (UI层 - Excel油墨数据导入对话框)
============================================================
上传Excel，自动识别表头、自动分类、自动从颜色值反推光谱，
弹出预览列表让用户勾选确认后再真正写入油墨库（不是传了就无脑导入，
给用户留一个"看一眼对不对"的机会，尤其类别是猜的、没提供颜色值的
两种情况会明确标出来提醒）。
"""

from typing import List, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QWidget, QLineEdit
)

from core_layer.ink_import import parse_ink_excel
from core_layer.color_convert import lab_to_srgb_approx
from core_layer.color_engine import KubelkaMunkEngine, InkSpectralData
from ui_layer.ink_meta import category_label
from ui_layer.widgets import PrimaryButton, GhostButton


class InkImportDialog(QDialog):

    def __init__(self, parent=None, ink_repo=None):
        super().__init__(parent)
        self.ink_repo = ink_repo
        self.setWindowTitle("导入Excel油墨数据")
        self.setMinimumSize(760, 540)
        self._parsed: List[Dict] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        open_row = QHBoxLayout()
        open_btn = PrimaryButton("📂 选择Excel文件")
        open_btn.clicked.connect(self._on_open)
        open_row.addWidget(open_btn)
        self.file_label = QLabel("尚未选择文件")
        self.file_label.setStyleSheet("color:#64748b;")
        open_row.addWidget(self.file_label, 1)
        root.addLayout(open_row)

        hint = QLabel(
            "💡 表头随意——常见的\"编号/名称/类别/颜色/库存/单价\"中英文写法都能自动识别。"
            "没写类别的会按名称关键字自动猜（含\"白\"→高遮盖白，含\"光油/冲淡\"→冲淡剂，"
            "其余→彩色油墨）；提供了颜色值（HEX或RGB）的会自动反推出带色相的光谱，"
            "没提供颜色值的先用灰阶占位，导入后建议去油墨库用色相环补上真实颜色。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["导入", "颜色预览", "编号", "名称", "类别", "说明"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        cancel_btn = GhostButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = PrimaryButton("✅ 确认导入勾选项")
        ok_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择油墨数据Excel", "", "Excel文件 (*.xlsx *.xls)")
        if not path:
            return
        try:
            self._parsed = parse_ink_excel(path)
        except Exception as exc:
            QMessageBox.warning(self, "解析失败", f"无法解析该Excel文件：{exc}")
            return
        if not self._parsed:
            QMessageBox.information(self, "提示", "没有从这个文件里识别出任何油墨记录，请检查表格内容。")
        self.file_label.setText(path)
        self._populate_table()

    def _populate_table(self):
        engine_cache = {}
        self.table.setRowCount(len(self._parsed))
        for row, item in enumerate(self._parsed):
            cb_container = QWidget()
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            cb_layout.addWidget(checkbox)
            self.table.setCellWidget(row, 0, cb_container)

            import numpy as np
            eng = KubelkaMunkEngine([InkSpectralData(code="_p", name="_p", K=np.array(item["K"]), S=np.array(item["S"]))])
            lab = eng.compute_lab({"_p": 1.0}, apply_dry_back=False)
            rgb = lab_to_srgb_approx(*lab)
            preview_item = QTableWidgetItem("")
            preview_item.setBackground(QColor(*rgb))
            self.table.setItem(row, 1, preview_item)

            code_edit = QLineEdit(item["code"])
            self.table.setCellWidget(row, 2, code_edit)
            name_edit = QLineEdit(item["name"])
            self.table.setCellWidget(row, 3, name_edit)

            cat_text = category_label(item["category"]) + ("（猜测）" if item["category_guessed"] else "")
            self.table.setItem(row, 4, QTableWidgetItem(cat_text))

            note = "" if item["has_color_source"] else "⚠ 未提供颜色值，先用灰阶占位"
            if self.ink_repo and self.ink_repo.get_by_code(item["code"]):
                note += ("；" if note else "") + "⚠ 编号已存在，导入会覆盖原有数据"
            note_item = QTableWidgetItem(note)
            note_item.setForeground(QColor("#b45309") if note else QColor("#16a34a"))
            self.table.setItem(row, 5, note_item)

    def _on_confirm(self):
        if not self._parsed:
            QMessageBox.information(self, "提示", "请先选择并解析一个Excel文件。")
            return
        if not self.get_selected_records():
            QMessageBox.information(self, "提示", "请至少勾选一条要导入的记录。")
            return
        self.accept()

    def get_selected_records(self) -> List[Dict]:
        result = []
        for row, item in enumerate(self._parsed):
            cb_container = self.table.cellWidget(row, 0)
            checkbox = cb_container.findChild(QCheckBox)
            if checkbox and checkbox.isChecked():
                code_edit = self.table.cellWidget(row, 2)
                name_edit = self.table.cellWidget(row, 3)
                record = dict(item)
                record["code"] = code_edit.text().strip() or item["code"]
                record["name"] = name_edit.text().strip() or item["name"]
                result.append(record)
        return result
