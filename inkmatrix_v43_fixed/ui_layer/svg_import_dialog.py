# -*- coding: utf-8 -*-
"""
svg_import_dialog.py  (UI层 - SVG批量取色确认对话框)
=========================================================
配合 core_layer.svg_import.parse_svg_fill_colors 使用：
    上传一个SVG矢量文件 -> 自动识别出图里所有互不相同的填充颜色
    （精确读数值，不是像素采样）-> 在本对话框里勾选要导入哪些颜色、
    给每个颜色起个色位名字（文字/LOGO/图案...）-> 确认后批量导入为
    【多色印刷工单】的色位，自动进入寻优。
"""

from typing import List, Dict, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QCheckBox, QWidget
)

from core_layer.svg_import import parse_svg_fill_colors
from ui_layer.widgets import PrimaryButton, GhostButton


class SvgColorImportDialog(QDialog):
    """
    用法：
        dlg = SvgColorImportDialog(self)
        if dlg.exec():
            stations = dlg.get_selected_stations()   # [(name, (L,a,b)), ...]
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入SVG矢量图 —— 自动识别颜色")
        self.setMinimumSize(640, 500)
        self._detected: List[Dict] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        open_row = QHBoxLayout()
        open_btn = PrimaryButton("📂 选择SVG文件")
        open_btn.clicked.connect(self._on_open_svg)
        open_row.addWidget(open_btn)
        self.file_label = QLabel("尚未选择文件")
        self.file_label.setStyleSheet("color:#64748b;")
        open_row.addWidget(self.file_label, 1)
        root.addLayout(open_row)

        hint = QLabel(
            "💡 说明：直接读取SVG文件里每个图形写的精确颜色数值（不是渲染成图片再猜色），"
            "如果客户给的是CDR文件，请先在CorelDRAW里\"导出\"为SVG格式再上传（文件→导出→SVG）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["导入", "颜色预览", "色位名称", "出现次数(参考重要性)"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        cancel_btn = GhostButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = PrimaryButton("✅ 导入勾选的颜色为色位")
        ok_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _on_open_svg(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择SVG矢量文件", "", "SVG矢量图 (*.svg)")
        if not path:
            return
        try:
            self._detected = parse_svg_fill_colors(path)
        except Exception as exc:
            QMessageBox.warning(self, "解析失败", f"无法解析该SVG文件：{exc}")
            return

        if not self._detected:
            QMessageBox.information(self, "提示", "未能在该文件中识别到任何实色填充（可能全部是渐变/无填充图形）。")

        self.file_label.setText(path)
        self._populate_table()

    def _populate_table(self):
        self.table.setRowCount(len(self._detected))
        for row, item in enumerate(self._detected):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            cb_container = QWidget()
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.addWidget(checkbox)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row, 0, cb_container)

            preview_item = QTableWidgetItem("")
            preview_item.setBackground(QColor(*item["rgb"]))
            self.table.setItem(row, 1, preview_item)

            name_edit = QLineEdit(f"颜色{row + 1}")
            self.table.setCellWidget(row, 2, name_edit)

            count_item = QTableWidgetItem(str(item["count"]))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, count_item)

    def _on_confirm(self):
        if not self._detected:
            QMessageBox.information(self, "提示", "请先选择并解析一个SVG文件。")
            return
        selected = self.get_selected_stations()
        if not selected:
            QMessageBox.information(self, "提示", "请至少勾选一个颜色。")
            return
        self.accept()

    def get_selected_stations(self) -> List[Tuple[str, tuple]]:
        result = []
        for row, item in enumerate(self._detected):
            cb_container = self.table.cellWidget(row, 0)
            checkbox = cb_container.findChild(QCheckBox)
            name_edit = self.table.cellWidget(row, 2)
            if checkbox and checkbox.isChecked():
                name = name_edit.text().strip() or f"颜色{row + 1}"
                result.append((name, item["lab"]))
        return result
