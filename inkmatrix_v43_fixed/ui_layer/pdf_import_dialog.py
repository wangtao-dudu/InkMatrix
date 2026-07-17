# -*- coding: utf-8 -*-
"""
pdf_import_dialog.py  (UI层 - PDF设计稿导入对话框)
=======================================================
"上传PDF设计稿，自动识别背景色和印刷色"的用户界面。

流程：
    1. 选择PDF文件（可能多页，先选页）
    2. 自动转换+解析出该页所有精确颜色，按估算覆盖面积从大到小排序
    3. 面积最大的一项默认标记为【背景色】（通常就是瓶身/包装底色，
       不需要印刷），其余默认勾选为【印刷色位】，可以逐个改名/调整
    4. 确认后返回 (印刷色位列表, 背景色Lab或None)
"""

from typing import List, Dict, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QCheckBox,
    QWidget, QComboBox, QRadioButton, QButtonGroup
)

from core_layer.pdf_import import get_pdf_page_count, extract_colors_from_pdf
from ui_layer.widgets import PrimaryButton, GhostButton


class PdfColorImportDialog(QDialog):
    """
    用法：
        dlg = PdfColorImportDialog(self)
        if dlg.exec():
            stations = dlg.get_selected_stations()      # [(name, (L,a,b)), ...]
            background_lab = dlg.get_background_lab()   # (L,a,b) 或 None
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入PDF设计稿 —— 自动识别背景色与印刷色")
        self.setMinimumSize(700, 560)
        self._detected: List[Dict] = []
        self._background_row: Optional[int] = None
        self._pdf_path: Optional[str] = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        open_row = QHBoxLayout()
        open_btn = PrimaryButton("📂 选择PDF文件")
        open_btn.clicked.connect(self._on_open_pdf)
        open_row.addWidget(open_btn)

        open_row.addWidget(QLabel("页码："))
        self.page_combo = QComboBox()
        self.page_combo.setMinimumWidth(80)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        open_row.addWidget(self.page_combo)

        self.file_label = QLabel("尚未选择文件")
        self.file_label.setStyleSheet("color:#64748b;")
        open_row.addWidget(self.file_label, 1)
        root.addLayout(open_row)

        hint = QLabel(
            "💡 说明：直接读取PDF矢量图形里的精确颜色数值（不是渲染成图片再猜色）。"
            "系统按每种颜色的估算覆盖面积自动排序——面积最大的通常就是背景色/瓶身底色，"
            "已默认帮你标记，其余作为待印刷色位，勾选与命名都可以调整。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["背景色", "导入为色位", "颜色预览", "色位名称", "覆盖面积(参考)"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        cancel_btn = GhostButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = PrimaryButton("✅ 确认导入")
        ok_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    # ---------------------------------------------------------- 文件加载 ----

    def _on_open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择PDF设计稿", "", "PDF文件 (*.pdf)")
        if not path:
            return
        self._pdf_path = path
        self.file_label.setText(path)

        page_count = get_pdf_page_count(path)
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for i in range(1, page_count + 1):
            self.page_combo.addItem(f"第{i}页", i)
        self.page_combo.blockSignals(False)

        self._load_page(1)

    def _on_page_changed(self, _index: int):
        page = self.page_combo.currentData()
        if page and self._pdf_path:
            self._load_page(page)

    def _load_page(self, page_number: int):
        try:
            self._detected = extract_colors_from_pdf(self._pdf_path, page_number)
        except RuntimeError as exc:
            QMessageBox.warning(self, "转换失败", str(exc))
            self._detected = []
        except Exception as exc:
            QMessageBox.warning(self, "解析失败", f"无法解析该PDF文件：{exc}")
            self._detected = []

        if not self._detected:
            QMessageBox.information(self, "提示", "未能在该页识别到任何实色填充（可能全部是渐变/图片/无填充图形）。")

        self._populate_table()

    # ---------------------------------------------------------- 表格构建 ----

    def _populate_table(self):
        self.table.setRowCount(len(self._detected))
        self._bg_radio_group = QButtonGroup(self)
        self._bg_radio_group.setExclusive(True)

        for row, item in enumerate(self._detected):
            # 背景色单选
            bg_container = QWidget()
            bg_layout = QHBoxLayout(bg_container)
            bg_layout.setContentsMargins(0, 0, 0, 0)
            bg_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bg_radio = QRadioButton()
            bg_radio.setChecked(row == 0)  # 面积最大(第一项)默认标记为背景色
            self._bg_radio_group.addButton(bg_radio, row)
            bg_layout.addWidget(bg_radio)
            self.table.setCellWidget(row, 0, bg_container)

            # 是否导入为印刷色位（背景色默认不勾选，其余默认勾选）
            cb_container = QWidget()
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox = QCheckBox()
            checkbox.setChecked(row != 0)
            cb_layout.addWidget(checkbox)
            self.table.setCellWidget(row, 1, cb_container)
            bg_radio.toggled.connect(lambda checked, cb=checkbox: cb.setChecked(not checked) if checked else None)

            preview_item = QTableWidgetItem("")
            preview_item.setBackground(QColor(*item["rgb"]))
            self.table.setItem(row, 2, preview_item)

            default_name = "背景色/底色" if row == 0 else f"颜色{row}"
            name_edit = QLineEdit(default_name)
            self.table.setCellWidget(row, 3, name_edit)

            area_item = QTableWidgetItem(f"{item['area']:.0f}")
            area_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, area_item)

    # ---------------------------------------------------------- 结果输出 ----

    def _on_confirm(self):
        if not self._detected:
            QMessageBox.information(self, "提示", "请先选择并解析一个PDF文件。")
            return
        if not self.get_selected_stations():
            QMessageBox.information(self, "提示", "请至少勾选一个颜色作为印刷色位。")
            return
        self.accept()

    def get_selected_stations(self) -> List[Tuple[str, tuple]]:
        result = []
        for row, item in enumerate(self._detected):
            cb_container = self.table.cellWidget(row, 1)
            checkbox = cb_container.findChild(QCheckBox)
            name_edit = self.table.cellWidget(row, 3)
            if checkbox and checkbox.isChecked():
                name = name_edit.text().strip() or f"颜色{row + 1}"
                result.append((name, item["lab"]))
        return result

    def get_background_lab(self) -> Optional[tuple]:
        bg_id = self._bg_radio_group.checkedId()
        if bg_id is None or bg_id < 0 or bg_id >= len(self._detected):
            return None
        return self._detected[bg_id]["lab"]
