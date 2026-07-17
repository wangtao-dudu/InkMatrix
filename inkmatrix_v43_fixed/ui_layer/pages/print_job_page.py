# -*- coding: utf-8 -*-
"""
print_job_page.py  (UI层 - 多色印刷工单页面)
=================================================
解决"一个瓶子上有多个印刷颜色（文字/LOGO/图案各一个颜色），丝印机器
需要分网版套色印刷"的现场需求。

核心概念：
    工单 (Job)：对应一个瓶身的完整印刷任务，包含：
        - 承印物瓶身底色（共享，来自承印物底色库）
        - 在库油墨勾选（共享，今日仓库可用油墨）
        - 若干【色位】(ColorStation)：每个色位对应丝印的一个独立网版，
          有各自的目标色、目标重量、配方结果，可分别单独寻优与执行。

典型流程：
    1. 打开客户效果图，用"多色位批量取色"一次性点出 文字/LOGO/图案 等
       各色位的目标颜色（也可以手动逐个添加色位）
    2. 勾选今日在库油墨、选择瓶身底色
    3. 一键为全部色位寻优，得到每个网版各自的配方克重表
    4. 逐色位执行配墨（人工模式打印清单 / 全自动滴定模式）
"""

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QDate
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox,
    QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QInputDialog, QSplitter, QFileDialog, QScrollArea, QDateEdit
)

from core_layer.color_convert import lab_to_srgb_approx
from hal_layer.interfaces import AbstractScale, AbstractDispenser
from ui_layer.widgets import Card, PrimaryButton, SuccessButton, GhostButton, ColorSwatch, ResponsiveRow
from ui_layer.ink_checklist import InkChecklistWidget
from ui_layer.color_pickers import JobImageColorMapDialog
from ui_layer.pdf_import_dialog import PdfColorImportDialog
from ui_layer.worker import AutoDispenseWorker
from dal_layer.report_generator import generate_print_job_docx
from dal_layer.data_manager import get_material_props
from ui_layer.ink_meta import ink_fingerprint


class ColorStation:
    """一个丝印色位（一个网版）的完整状态。"""

    def __init__(self, name: str, target_lab: tuple, total_grams: float = 500.0):
        self.name = name
        self.target_lab = target_lab
        self.total_grams = total_grams
        self.weights: Dict[str, float] = {}
        self.grams: Dict[str, float] = {}
        self.predicted_lab: Optional[tuple] = None
        self.delta_e: Optional[float] = None
        self.white_auto_triggered = False
        self.warning: Optional[str] = None
        self.opacity_estimate: float = 1.0
        self.ink_count_simplified: bool = False
        self.ink_fingerprints: Dict[str, tuple] = {}  # 寻优时各油墨的指纹快照,供后续检测油墨是否被改过

    @property
    def is_solved(self) -> bool:
        return self.delta_e is not None


class PrintJobPage(QWidget):

    DELTA_E_WARNING_THRESHOLD = 3.0

    status_normal = pyqtSignal(str)
    status_danger = pyqtSignal(str)
    # ★ 同 workbench：工单页执行配墨同样会扣库存，扣完必须广播出去
    ink_db_changed = pyqtSignal()
    product_saved = pyqtSignal()

    def __init__(self, ink_repo, bottle_repo, get_engine, scale: AbstractScale,
                 dispenser: AbstractDispenser, product_repo=None, company_repo=None,
                 get_allowed_ink_codes=None, user_repo=None, current_username=None, parent=None):
        super().__init__(parent)
        self.ink_repo = ink_repo
        self.bottle_repo = bottle_repo
        self.get_engine = get_engine
        self.scale = scale
        self.dispenser = dispenser
        self.product_repo = product_repo
        self.company_repo = company_repo
        self.get_allowed_ink_codes = get_allowed_ink_codes
        self.user_repo = user_repo
        self.current_username = current_username

        self.stations: List[ColorStation] = []
        self._current_station: Optional[ColorStation] = None
        self._auto_worker = None

        self._build_ui()
        self.refresh_bottle_combo()

    # ================================================================
    # UI 搭建
    # ================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("多色印刷工单")
        title.setObjectName("PageTitle")
        subtitle = QLabel("一个瓶身有多个丝印色位（文字/LOGO/图案各一版）时，在此统一管理各色位的配方与执行")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        body = ResponsiveRow(breakpoint=1100)
        body.add_panel(self._wrap_scrollable(self._build_job_config_card()), 1)
        body.add_panel(self._wrap_scrollable(self._build_station_list_card()), 1)
        body.add_panel(self._wrap_scrollable(self._build_station_detail_card()), 2)
        root.addWidget(body, 1)

    @staticmethod
    def _wrap_scrollable(inner: QWidget) -> QWidget:
        """
        把卡片包进 QScrollArea：窗口/列宽度不够时内容整体可以滚动，
        而不是被挤压到跟旁边控件重叠（曾经真实出现过的重叠bug教训）。
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(inner)
        return scroll

    # ---------------- 工单基础配置卡片 ----------------

    def _build_job_config_card(self) -> Card:
        card = Card("① 工单配置")
        lay = card.body_layout

        # 工单页只管【怎么配色】这一件事。数量、单价、优惠、已付这些钱的事，
        # 全部归【财务管理】——它挂在进销存的进货记录上，那才是钱的源头。
        # 在这里再录一遍，只会变成两份对不上的数据。
        lay.addWidget(QLabel("产品名称："))
        self.product_name_edit = QLineEdit()
        self.product_name_edit.setPlaceholderText("例如：客户A - 100ml白瓶三色套印")
        self.product_name_edit.setToolTip("这个名字会作为配色模板的名称，存到【产品管理】里，下次同样的活直接调出来")
        lay.addWidget(self.product_name_edit)

        lay.addWidget(QLabel("客户名称（选填，导出工单会用到）："))
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("例如：客户A")
        lay.addWidget(self.customer_edit)

        lay.addWidget(QLabel("客户联系电话："))
        self.customer_phone_edit = QLineEdit()
        self.customer_phone_edit.setPlaceholderText("例如：138xxxxxxxx")
        lay.addWidget(self.customer_phone_edit)

        lay.addWidget(QLabel("交货日期："))
        self.delivery_date_edit = QDateEdit()
        self.delivery_date_edit.setCalendarPopup(True)
        self.delivery_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.delivery_date_edit.setDate(QDate.currentDate().addDays(7))
        lay.addWidget(self.delivery_date_edit)

        finance_hint = QLabel(
            "💰 数量 / 单价 / 优惠 / 收款，都在【财务管理】页——那边直接读进销存的进货数据，"
            "不用在这里再录一遍。"
        )
        finance_hint.setWordWrap(True)
        finance_hint.setStyleSheet("color:#64748b; font-size:11px; background:#f8fafc; "
                                   "border-radius:6px; padding:7px 9px;")
        lay.addWidget(finance_hint)

        lay.addWidget(QLabel("承印物 / 瓶身底色："))
        self.bottle_combo = QComboBox()
        lay.addWidget(self.bottle_combo)

        row = QHBoxLayout()
        row.addWidget(QLabel("在库油墨勾选："))
        row.addStretch(1)
        refresh_btn = GhostButton("↻ 刷新")
        refresh_btn.clicked.connect(lambda: self.ink_list_widget.refresh())
        row.addWidget(refresh_btn)
        lay.addLayout(row)
        self.ink_list_widget = InkChecklistWidget(
            self.ink_repo, get_engine=self.get_engine,
            get_allowed_codes=self.get_allowed_ink_codes, auto_select_all=True,
        )
        self.ink_list_widget.setMinimumHeight(320)
        lay.addWidget(self.ink_list_widget, 1)

        lay.addWidget(QLabel("新色位默认配墨总重(g)："))
        self.default_grams_spin = QDoubleSpinBox()
        self.default_grams_spin.setRange(1.0, 100000.0)
        self.default_grams_spin.setValue(300.0)
        lay.addWidget(self.default_grams_spin)

        pick_btn = PrimaryButton("🖼️ 从效果图批量取色（多色位）")
        pick_btn.clicked.connect(self._on_batch_pick_from_image)
        lay.addWidget(pick_btn)

        svg_btn = PrimaryButton("📄 导入PDF设计稿（自动识别背景色+印刷色）")
        svg_btn.clicked.connect(self._on_import_pdf)
        lay.addWidget(svg_btn)

        manual_btn = GhostButton("＋ 手动添加色位")
        manual_btn.clicked.connect(self._on_add_station_manual)
        lay.addWidget(manual_btn)

        solve_all_btn = PrimaryButton("🎯 为全部色位智能寻优")
        solve_all_btn.clicked.connect(self._on_solve_all)
        lay.addWidget(solve_all_btn)

        save_product_btn = GhostButton("💾 保存为产品模板")
        save_product_btn.clicked.connect(self._on_save_as_product)
        lay.addWidget(save_product_btn)

        export_btn = PrimaryButton("📄 导出Word工单文档")
        export_btn.clicked.connect(self._on_export_docx)
        lay.addWidget(export_btn)

        return card

    # ---------------- 色位列表卡片 ----------------

    def _build_station_list_card(self) -> Card:
        card = Card("② 色位列表（丝印网版）")
        lay = card.body_layout

        self.station_table = QTableWidget(0, 5)
        self.station_table.setHorizontalHeaderLabels(["色位", "预览", "配墨量(g)", "ΔE", "状态"])
        self.station_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.station_table.verticalHeader().setDefaultSectionSize(34)
        self.station_table.itemSelectionChanged.connect(self._on_station_row_selected)
        # 配墨量列（第2列）允许双击直接改，改了立刻更新对应色位——
        # 这样 PDF 导入十几个色位后，不用一个个点进详情面板，直接在表格里改量。
        self.station_table.cellChanged.connect(self._on_station_cell_changed)
        lay.addWidget(self.station_table, 1)

        del_btn = GhostButton("－ 删除选中色位")
        del_btn.clicked.connect(self._on_delete_station)
        lay.addWidget(del_btn)

        return card

    # ---------------- 色位详情/执行卡片 ----------------

    def _build_station_detail_card(self) -> Card:
        card = Card("③ 色位详情与执行")
        lay = card.body_layout

        self.detail_name_label = QLabel("请在左侧色位列表中选择一个色位")
        self.detail_name_label.setStyleSheet("font-weight:700; font-size:14px;")
        lay.addWidget(self.detail_name_label)

        lab_grid = QGridLayout()
        self.spin_L = QDoubleSpinBox(); self.spin_L.setRange(0, 100)
        self.spin_a = QDoubleSpinBox(); self.spin_a.setRange(-128, 128)
        self.spin_b = QDoubleSpinBox(); self.spin_b.setRange(-128, 128)
        for spin in (self.spin_L, self.spin_a, self.spin_b):
            spin.valueChanged.connect(self._on_detail_lab_changed)
        lab_grid.addWidget(QLabel("L*"), 0, 0); lab_grid.addWidget(self.spin_L, 0, 1)
        lab_grid.addWidget(QLabel("a*"), 0, 2); lab_grid.addWidget(self.spin_a, 0, 3)
        lab_grid.addWidget(QLabel("b*"), 0, 4); lab_grid.addWidget(self.spin_b, 0, 5)
        lay.addLayout(lab_grid)

        preview_row = QHBoxLayout()
        self.detail_swatch = ColorSwatch(height=36)
        preview_row.addWidget(self.detail_swatch, 1)
        self.detail_weight_spin = QDoubleSpinBox()
        self.detail_weight_spin.setRange(1.0, 100000.0)
        self.detail_weight_spin.setPrefix("总重 ")
        self.detail_weight_spin.setSuffix(" g")
        self.detail_weight_spin.valueChanged.connect(self._on_detail_weight_changed)
        preview_row.addWidget(self.detail_weight_spin)
        lay.addLayout(preview_row)

        solve_btn = PrimaryButton("🎯 为当前色位重新寻优")
        solve_btn.clicked.connect(self._on_solve_current)
        lay.addWidget(solve_btn)

        self.formula_table = QTableWidget(0, 3)
        self.formula_table.setHorizontalHeaderLabels(["油墨名称", "配方比例(%)", "精准称重克数(g)"])
        self.formula_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        big_font = QFont(); big_font.setPointSize(12)
        self.formula_table.setFont(big_font)
        self.formula_table.setMinimumHeight(160)
        lay.addWidget(self.formula_table, 1)

        result_row = QHBoxLayout()
        self.predicted_lab_label = QLabel("预测Lab: --")
        self.delta_e_label = QLabel("ΔE: --")
        result_row.addWidget(self.predicted_lab_label)
        result_row.addWidget(self.delta_e_label)
        result_row.addStretch(1)
        lay.addLayout(result_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("执行模式："))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["人工模式", "全自动滴定模式"])
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        self.start_btn = SuccessButton("▶ 执行当前色位配墨")
        self.start_btn.clicked.connect(self._on_start_execution)
        lay.addWidget(self.start_btn)

        self.execution_log_label = QLabel("执行日志：请先选择色位。")
        self.execution_log_label.setWordWrap(True)
        self.execution_log_label.setStyleSheet("color:#475569; font-size:12px;")
        lay.addWidget(self.execution_log_label)

        self._set_detail_enabled(False)
        return card

    def _set_detail_enabled(self, enabled: bool):
        for w in (self.spin_L, self.spin_a, self.spin_b, self.detail_weight_spin,
                  self.mode_combo, self.start_btn):
            w.setEnabled(enabled)

    # ================================================================
    # 数据刷新
    # ================================================================

    def refresh_bottle_combo(self):
        current_code = self.bottle_combo.currentData()
        self.bottle_combo.clear()
        for record in self.bottle_repo.load_all():
            self.bottle_combo.addItem(f"[{record['code']}] {record['name']}", record["code"])
        if current_code:
            idx = self.bottle_combo.findData(current_code)
            if idx >= 0:
                self.bottle_combo.setCurrentIndex(idx)

    def refresh_ink_checklist(self):
        self.ink_list_widget.refresh()

    # ================================================================
    # 色位增删
    # ================================================================

    def _on_batch_pick_from_image(self):
        dlg = JobImageColorMapDialog(self)
        if dlg.exec():
            station_labs = dlg.get_station_labs()
            if not station_labs:
                return
            for name, lab in station_labs.items():
                existing = next((s for s in self.stations if s.name == name), None)
                if existing:
                    existing.target_lab = lab
                    existing.delta_e = None  # 目标色变了，需要重新寻优
                else:
                    self.stations.append(ColorStation(name, lab, self.default_grams_spin.value()))
            self._refresh_station_table()
            self.status_normal.emit(f"已从效果图批量取色，共 {len(station_labs)} 个色位已更新目标色。")

    def _on_import_pdf(self):
        """
        导入PDF设计稿 —— 色位和背景色一次到位（问题5修复）。

        以前的做法：PDF里明明已经把背景色识别出来了，却只是在状态栏提示
        一句"识别到背景色，请自己去【瓶身识别】页建个档案"，等于把活儿又
        踢回给用户。用户还得记住那个 Lab 值，切页面、手动建档、再切回来
        选中——一次导入要跑三个页面，纯属折腾。

        现在的做法：识别到背景色就直接落地成一条承印物档案并自动选中，
        导入完直接点【全部色位智能寻优】就行，中间不需要任何额外操作。
        """
        dlg = PdfColorImportDialog(self)
        if not dlg.exec():
            return

        stations_to_add = dlg.get_selected_stations()
        background_lab = dlg.get_background_lab()

        added, updated = 0, 0
        for name, lab in stations_to_add:
            existing = next((s for s in self.stations if s.name == name), None)
            if existing:
                existing.target_lab = lab
                existing.delta_e = None
                updated += 1
            else:
                self.stations.append(ColorStation(name, lab, self.default_grams_spin.value()))
                added += 1
        self._refresh_station_table()

        msg = f"PDF识别完成：新增 {added} 个印刷色位，更新 {updated} 个（精确读取矢量数值，非像素采样）。"

        if background_lab is not None:
            bottle_code = self._auto_register_background(background_lab)
            L, a, b = background_lab
            msg += (
                f" 背景色 Lab=({L:.1f},{a:.1f},{b:.1f}) 已自动登记为承印物 [{bottle_code}] 并选中，"
                f"直接点【全部色位寻优】即可。"
            )

        self.status_normal.emit(msg)

    def _auto_register_background(self, background_lab: tuple) -> str:
        """
        把PDF里识别出的背景色落地成一条承印物档案，并在下拉里选中它。

        去重逻辑：如果库里已经有一只底色几乎一样的瓶子（ΔE<2，肉眼基本
        看不出差别），就直接复用它，不重复建档——否则同一个客户的稿子导
        几次，承印物库里就堆一堆几乎一样的记录。

        材质留空（custom，中性参数）：PDF里只有颜色信息，读不出这是塑料
        还是玻璃。所以这里只解决"底色"，材质仍需去【承印物识别】页补上
        ——那里选完材质，配色才会真正把吸墨/遮盖/附着力算进去。
        """
        engine = self.get_engine()

        for r in self.bottle_repo.load_all():
            existing_lab = r.get("base_lab")
            if not existing_lab:
                continue
            if engine.delta_e_76(tuple(existing_lab), tuple(background_lab)) < 2.0:
                idx = self.bottle_combo.findData(r["code"])
                if idx >= 0:
                    self.bottle_combo.setCurrentIndex(idx)
                return r["code"]

        # 库里没有相近的，新建一条
        existing_codes = {r["code"] for r in self.bottle_repo.load_all()}
        seq = 1
        while f"BT-PDF{seq:02d}" in existing_codes:
            seq += 1
        code = f"BT-PDF{seq:02d}"

        self.bottle_repo.upsert({
            "code": code,
            "name": f"PDF识别底色 #{seq}",
            "base_lab": list(background_lab),
            "substrate_type": "custom",   # 材质未知，用中性参数；建议去承印物页补充
        })
        self.refresh_bottle_combo()
        idx = self.bottle_combo.findData(code)
        if idx >= 0:
            self.bottle_combo.setCurrentIndex(idx)
        return code

    def _on_add_station_manual(self):
        name, ok = QInputDialog.getText(self, "新增色位", "色位名称（例如：文字 / LOGO / 图案）：")
        name = name.strip()
        if not (ok and name):
            return
        if any(s.name == name for s in self.stations):
            QMessageBox.information(self, "提示", "该色位名称已存在，请更换名称。")
            return
        station = ColorStation(name, (50.0, 0.0, 0.0), self.default_grams_spin.value())
        self.stations.append(station)
        self._refresh_station_table()
        self._select_station(station)

    def _on_delete_station(self):
        row = self.station_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在列表中选中要删除的色位。")
            return
        station = self.stations[row]
        confirm = QMessageBox.question(self, "确认删除", f"确定要删除色位【{station.name}】吗？")
        if confirm == QMessageBox.StandardButton.Yes:
            self.stations.remove(station)
            if self._current_station is station:
                self._current_station = None
                self._set_detail_enabled(False)
                self.detail_name_label.setText("请在左侧色位列表中选择一个色位")
                self.formula_table.setRowCount(0)
            self._refresh_station_table()

    def _refresh_station_table(self):
        self._refreshing_table = True   # 防止程序性写入触发 cellChanged
        self.station_table.setRowCount(len(self.stations))
        for row, s in enumerate(self.stations):
            name_item = QTableWidgetItem(s.name)
            r, g, b = lab_to_srgb_approx(*s.target_lab)
            preview_item = QTableWidgetItem("")
            preview_item.setBackground(QColor(r, g, b))
            # 配墨量：每个色位单独显示。PDF 批量导入后每个色位需要的墨量不同
            # （大面积色位墨多、小 logo 墨少），在这里一眼看清、也能直接改。
            grams_item = QTableWidgetItem(f"{s.total_grams:.0f}")
            de_item = QTableWidgetItem(f"{s.delta_e:.2f}" if s.is_solved else "--")
            status_item = QTableWidgetItem("✅已寻优" if s.is_solved else "⏳未寻优")
            if s.is_solved and s.delta_e > self.DELTA_E_WARNING_THRESHOLD:
                status_item.setText("⚠ ΔE超标")
            if s.is_solved and self._station_is_stale(s):
                status_item.setText("🔴配方已过期")
                status_item.setToolTip("配方所用的某支油墨，数据在寻优之后被修改过，当前显示的配方比例/ΔE已经不准了，请重新点击寻优。")
            for item in (name_item, preview_item, grams_item, de_item, status_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # 除了配墨量列，其余列都设成只读——避免用户误改色位名/ΔE等
            for item in (name_item, preview_item, de_item, status_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            grams_item.setToolTip("双击可直接修改这个色位的配墨量")
            self.station_table.setItem(row, 0, name_item)
            self.station_table.setItem(row, 1, preview_item)
            self.station_table.setItem(row, 2, grams_item)
            self.station_table.setItem(row, 3, de_item)
            self.station_table.setItem(row, 4, status_item)
        self._refreshing_table = False

    # ================================================================
    # 色位选择与详情联动
    # ================================================================

    def _on_station_cell_changed(self, row: int, col: int):
        # 只处理"配墨量"列（第2列），其余列是展示用的
        if col != 2:
            return
        if getattr(self, "_refreshing_table", False):
            return   # 刷新表格时程序性写入的，不是用户改的，忽略
        if row < 0 or row >= len(self.stations):
            return
        item = self.station_table.item(row, col)
        if item is None:
            return
        try:
            grams = float(item.text())
            if grams <= 0:
                raise ValueError
        except ValueError:
            # 输入的不是有效数字，恢复成原值
            self._refreshing_table = True
            item.setText(f"{self.stations[row].total_grams:.0f}")
            self._refreshing_table = False
            return
        self.stations[row].total_grams = grams
        # 如果改的正好是当前选中的色位，同步详情面板里的配墨量输入框
        if self._current_station is self.stations[row]:
            self._updating_detail = True
            self.detail_weight_spin.setValue(grams)
            self._updating_detail = False
            # 配墨量变了，克重要重算（比例不变，总量变）
            if self.stations[row].is_solved:
                self.stations[row].grams = self.get_engine().weights_to_grams(
                    self.stations[row].weights, grams
                )
                self._populate_formula_table(self.stations[row].weights,
                                             self.stations[row].grams)

    def _on_station_row_selected(self):
        row = self.station_table.currentRow()
        if row < 0 or row >= len(self.stations):
            return
        self._select_station(self.stations[row])

    def _select_station(self, station: ColorStation):
        self._current_station = station
        self._set_detail_enabled(True)
        self.detail_name_label.setText(f"当前色位：{station.name}")

        self._updating_detail = True
        self.spin_L.setValue(station.target_lab[0])
        self.spin_a.setValue(station.target_lab[1])
        self.spin_b.setValue(station.target_lab[2])
        self.detail_weight_spin.setValue(station.total_grams)
        self._updating_detail = False
        self._update_detail_swatch()

        if station.is_solved:
            self._populate_formula_table(station.weights, station.grams)
            self.predicted_lab_label.setText("预测Lab: (%.2f, %.2f, %.2f)" % station.predicted_lab)
            ink_count = sum(1 for v in station.weights.values() if v > 0)
            de_text = "ΔE: %.3f  |  用墨%d种" % (station.delta_e, ink_count)
            if station.ink_count_simplified:
                de_text += "（已精简）"
            if station.opacity_estimate < 0.7:
                de_text += f"  ⚠遮盖力约{station.opacity_estimate*100:.0f}%"
            self.delta_e_label.setText(de_text)
            if self._station_is_stale(station):
                self.execution_log_label.setText(
                    f"🔴 执行日志：警告——色位【{station.name}】所用的某支油墨在寻优之后被修改过，"
                    f"当前显示的配方比例/ΔE已经不是最新的了，请先重新点击【为当前色位重新寻优】再执行配墨！"
                )
            else:
                self.execution_log_label.setText(f"执行日志：色位【{station.name}】等待执行……")
        else:
            self.formula_table.setRowCount(0)
            self.predicted_lab_label.setText("预测Lab: --")
            self.delta_e_label.setText("ΔE: --")
            self.execution_log_label.setText(f"执行日志：色位【{station.name}】等待寻优/执行……")

        # 让表格行选中态与当前色位保持一致
        for row, s in enumerate(self.stations):
            if s is station:
                self.station_table.blockSignals(True)
                self.station_table.selectRow(row)
                self.station_table.blockSignals(False)
                break

    def _on_detail_lab_changed(self, _value=None):
        if getattr(self, "_updating_detail", False) or self._current_station is None:
            return
        self._current_station.target_lab = (self.spin_L.value(), self.spin_a.value(), self.spin_b.value())
        self._current_station.delta_e = None  # 目标色改了，旧结果失效
        self._update_detail_swatch()
        self._refresh_station_table()

    def _on_detail_weight_changed(self, value: float):
        if self._current_station is not None:
            self._current_station.total_grams = value

    def _update_detail_swatch(self):
        r, g, b = lab_to_srgb_approx(self.spin_L.value(), self.spin_a.value(), self.spin_b.value())
        self.detail_swatch.set_rgb(r, g, b)

    # ================================================================
    # 寻优
    # ================================================================

    def _solve_station(self, station: ColorStation, checked_codes: List[str], white_codes: List[str]) -> bool:
        engine = self.get_engine()
        substrate_lab = self._get_selected_bottle_lab()
        material_props = self._get_selected_material_props()
        try:
            result = engine.solve_formula(
                station.target_lab, checked_codes, white_codes,
                substrate_lab=substrate_lab,
                material_props=material_props,   # 材质进算法（问题6）
            )
        except ValueError as exc:
            self.status_danger.emit(f"色位【{station.name}】寻优失败：{exc}")
            return False

        station.weights = result.weights
        station.grams = engine.weights_to_grams(result.weights, station.total_grams)
        station.predicted_lab = result.predicted_lab
        station.delta_e = result.delta_e
        station.white_auto_triggered = result.white_auto_triggered
        station.warning = result.warning
        station.opacity_estimate = result.opacity_estimate
        station.ink_count_simplified = result.ink_count_simplified

        # 记录本次寻优实际用到的每支油墨当时的"指纹"，后续油墨库改了
        # 这些墨的数据时，能检测出这份配方已经过期，需要提醒重新寻优。
        station.ink_fingerprints = {}
        for code, w in result.weights.items():
            if w > 0:
                record = self.ink_repo.get_by_code(code)
                if record:
                    station.ink_fingerprints[code] = ink_fingerprint(record)
        return True

    def _station_is_stale(self, station: ColorStation) -> bool:
        """检测配方所用的油墨，有没有在寻优之后又被编辑过（光谱数据变了）。"""
        if not station.ink_fingerprints:
            return False
        for code, snapshot in station.ink_fingerprints.items():
            record = self.ink_repo.get_by_code(code)
            if record is None:
                return True  # 用到的墨被删了，肯定也算过期
            if ink_fingerprint(record) != snapshot:
                return True
        return False

    def _get_selected_material_props(self):
        """当前选中承印物的材质物理参数（吸墨/遮盖/附着力），供配色引擎补偿用。"""
        bottle_code = self.bottle_combo.currentData()
        if not bottle_code:
            return None
        record = self.bottle_repo.get_by_code(bottle_code)
        if not record:
            return None
        return get_material_props(record.get("substrate_type", "custom"))

    def _get_selected_bottle_lab(self):
        bottle_code = self.bottle_combo.currentData()
        if not bottle_code:
            return None
        record = self.bottle_repo.get_by_code(bottle_code)
        if record and record.get("base_lab"):
            return tuple(record["base_lab"])
        return None

    def _on_solve_current(self):
        if self._current_station is None:
            QMessageBox.information(self, "提示", "请先选择一个色位。")
            return
        checked = self.ink_list_widget.get_checked_codes()
        if not checked:
            QMessageBox.warning(self, "提示", "请至少勾选一种在库油墨后再进行寻优。")
            return
        white_codes = [r["code"] for r in self.ink_repo.load_all() if r.get("category") == "white"]

        if self._solve_station(self._current_station, checked, white_codes):
            self._select_station(self._current_station)
            self._refresh_station_table()
            s = self._current_station
            if s.delta_e > self.DELTA_E_WARNING_THRESHOLD:
                self.status_danger.emit(f"色位【{s.name}】色差超标！ΔE={s.delta_e:.2f}")
            else:
                self.status_normal.emit(f"色位【{s.name}】寻优完成，ΔE={s.delta_e:.2f}")

    def _on_solve_all(self):
        if not self.stations:
            QMessageBox.information(self, "提示", "请先添加至少一个色位（可通过效果图批量取色或手动添加）。")
            return
        checked = self.ink_list_widget.get_checked_codes()
        if not checked:
            QMessageBox.warning(self, "提示", "请至少勾选一种在库油墨后再进行寻优。")
            return
        white_codes = [r["code"] for r in self.ink_repo.load_all() if r.get("category") == "white"]

        ok_count, warn_count = 0, 0
        for station in self.stations:
            if self._solve_station(station, checked, white_codes):
                ok_count += 1
                if station.delta_e > self.DELTA_E_WARNING_THRESHOLD:
                    warn_count += 1

        self._refresh_station_table()
        if self._current_station is not None:
            self._select_station(self._current_station)

        # 寻优完立刻自动存成产品模板。
        #
        # 为什么要自动存：算一遍配方要花几秒钟、要勾油墨、要选承印物，用户
        # 忙完这一轮很容易忘了点"保存为产品模板"——结果下次同样的活儿又得
        # 从头再来一遍。既然寻优成功就说明这套配方是有价值的，那就直接存下来，
        # 不要指望用户记得手动点。
        auto_saved = self._auto_save_product_template()

        tail = ""
        if auto_saved:
            tail = f" 已自动保存为产品模板【{auto_saved}】，下次同样的活直接在【产品管理】调出来。"
        elif not self.product_name_edit.text().strip():
            tail = " ⚠️ 没填【产品名称】，这次的配方没有存成模板——填个名字再点一次寻优就会自动存。"

        # 明确告诉用户：优选只是【算配方】，不会扣任何油墨库存。
        # 这直接回应"点了为全部色位优选是不是自动扣了所有色位的油墨"的疑问——
        # 不会。扣墨只发生在你对某个具体色位点【执行配墨】的时候，而且只扣那一个色位。
        note = "（注意：优选只计算配方，不扣油墨；扣库存发生在你对单个色位点【执行配墨】时）"

        if warn_count > 0:
            self.status_danger.emit(
                f"全部色位寻优完成（{ok_count}个），其中 {warn_count} 个色位ΔE超标，请检查。{tail}{note}"
            )
        else:
            self.status_normal.emit(
                f"全部 {ok_count} 个色位寻优完成，色差均在工业容差范围内。{tail}{note}"
            )

    def _auto_save_product_template(self) -> str:
        """寻优成功后自动存模板。没填产品名就跳过（返回空串）。"""
        if self.product_repo is None or not self.stations:
            return ""
        name = self.product_name_edit.text().strip()
        if not name:
            return ""
        self._save_product_template(name, silent=True)
        return name

    # ================================================================
    # 产品模板：保存 / 载入
    # ================================================================

    def _save_product_template(self, name: str, silent: bool = False):
        """
        存/更新一个产品配色模板。

        ⚠️ 这里【只存配色相关的东西】：产品名、客户、承印物、各个色位的目标色。
        数量/单价/优惠/已付这些钱的事一概不存——那些归【财务管理】，它挂在
        进销存的进货记录上。同一件事在两个地方各存一份，迟早对不上。
        """
        import datetime
        existing = next(
            (p for p in self.product_repo.load_all() if p.get("name") == name), None
        )
        code = existing["code"] if existing else f"PROD-{len(self.product_repo.load_all()) + 1:04d}"

        record = {
            "code": code,
            "name": name,
            "customer": self.customer_edit.text().strip(),
            "customer_phone": self.customer_phone_edit.text().strip(),
            "delivery_date": self.delivery_date_edit.date().toString("yyyy-MM-dd"),
            "bottle_code": self.bottle_combo.currentData() or "",
            "stations": [
                {
                    "name": s.name,
                    "target_lab": list(s.target_lab),
                    "total_grams": s.total_grams,
                }
                for s in self.stations
            ],
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.product_repo.upsert(record)
        self.product_saved.emit()
        if not silent:
            self.status_normal.emit(
                f"已保存为产品模板【{name}】，可在【产品管理】页面查看、下次直接载入。"
            )

    def _on_save_as_product(self):
        if self.product_repo is None:
            QMessageBox.warning(self, "提示", "产品模板功能未启用。")
            return
        if not self.stations:
            QMessageBox.information(self, "提示", "请先添加至少一个色位后再保存为产品模板。")
            return
        name = self.product_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请先填写【产品名称】，它会作为配色模板的名称保存。")
            return
        self._save_product_template(name)

    def load_product_template(self, record: Dict):
        """由 ProductPage 触发：把一个已保存的产品模板载入到本页面。"""
        self.product_name_edit.setText(record.get("name", ""))
        self.customer_edit.setText(record.get("customer", ""))
        self.customer_phone_edit.setText(record.get("customer_phone", ""))
        delivery_date_str = record.get("delivery_date", "")
        if delivery_date_str:
            qdate = QDate.fromString(delivery_date_str, "yyyy-MM-dd")
            if qdate.isValid():
                self.delivery_date_edit.setDate(qdate)
        bottle_code = record.get("bottle_code", "")
        if bottle_code:
            idx = self.bottle_combo.findData(bottle_code)
            if idx >= 0:
                self.bottle_combo.setCurrentIndex(idx)

        self.stations = [
            ColorStation(s["name"], tuple(s["target_lab"]), s.get("total_grams", 300.0))
            for s in record.get("stations", [])
        ]
        self._current_station = None
        self._set_detail_enabled(False)
        self.detail_name_label.setText("请在左侧色位列表中选择一个色位")
        self.formula_table.setRowCount(0)
        self._refresh_station_table()
        self.status_normal.emit(f"已载入产品模板【{record.get('name')}】，请重新点击【为全部色位智能寻优】。")

    # ================================================================
    # 导出Word工单
    # ================================================================

    def _on_export_docx(self):
        if not self.stations:
            QMessageBox.information(self, "提示", "请先添加并寻优至少一个色位后再导出。")
            return

        default_filename = (self.product_name_edit.text().strip() or "工单") + ".docx"
        path, _ = QFileDialog.getSaveFileName(self, "导出Word工单文档", default_filename, "Word文档 (*.docx)")
        if not path:
            return

        company_info = self.company_repo.load() if self.company_repo else {}
        bottle_name = ""
        bottle_code = self.bottle_combo.currentData()
        if bottle_code:
            b = self.bottle_repo.get_by_code(bottle_code)
            if b:
                bottle_name = b.get("name", "")

        job_meta = {
            "product_name": self.product_name_edit.text().strip(),
            "customer": self.customer_edit.text().strip(),
            "bottle_name": bottle_name,
        }

        ink_lookup = {r["code"]: r["name"] for r in self.ink_repo.load_all()}
        stations_payload = []
        for s in self.stations:
            rgb = lab_to_srgb_approx(*s.target_lab)
            rows = [
                {"ink_name": ink_lookup.get(code, code), "pct": w * 100.0, "grams": s.grams.get(code, 0.0)}
                for code, w in sorted(s.weights.items(), key=lambda x: -x[1]) if w > 0
            ] if s.is_solved else []
            stations_payload.append({
                "name": s.name,
                "target_lab": s.target_lab,
                "target_rgb": rgb,
                "predicted_lab": s.predicted_lab,
                "delta_e": s.delta_e,
                "total_grams": s.total_grams,
                "rows": rows,
            })

        try:
            generate_print_job_docx(company_info, job_meta, stations_payload, path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"生成Word文档时出错：{exc}")
            return

        self.status_normal.emit(f"工单文档已导出：{path}")
        QMessageBox.information(self, "导出成功", f"工单文档已保存到：\n{path}")

    def _populate_formula_table(self, weights: dict, grams: dict):
        ink_lookup = {r["code"]: r["name"] for r in self.ink_repo.load_all()}
        rows = [(code, w) for code, w in weights.items() if w > 0]
        rows.sort(key=lambda x: -x[1])
        self.formula_table.setRowCount(len(rows))
        for row_idx, (code, w) in enumerate(rows):
            name_item = QTableWidgetItem(ink_lookup.get(code, code))
            pct_item = QTableWidgetItem(f"{w * 100:.2f}%")
            gram_item = QTableWidgetItem(f"{grams.get(code, 0.0):.2f} g")
            for item in (name_item, pct_item, gram_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.formula_table.setItem(row_idx, 0, name_item)
            self.formula_table.setItem(row_idx, 1, pct_item)
            self.formula_table.setItem(row_idx, 2, gram_item)

    # ================================================================
    # 执行（人工模式 / 全自动滴定模式）—— 按当前选中色位单独执行
    # ================================================================

    def _on_start_execution(self):
        station = self._current_station
        if station is None or not station.is_solved:
            QMessageBox.warning(self, "提示", "请先为当前色位完成【智能寻优】后再执行配墨。")
            return

        if self._station_is_stale(station):
            confirm = QMessageBox.question(
                self, "配方已过期，确定要继续吗？",
                f"色位【{station.name}】所用的某支油墨，数据在这次寻优之后又被修改过——"
                f"当前显示的配方比例/克重不是基于最新油墨数据算出来的，直接拿去执行可能配出错误的颜色。\n\n"
                f"强烈建议先点【为当前色位重新寻优】刷新配方，再执行。\n\n"
                f"确定要用这份可能过期的配方继续执行吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        if self.mode_combo.currentText() == "人工模式":
            quota_problem = self._check_ink_quota(station.grams)
            if quota_problem:
                QMessageBox.warning(self, "油墨额度不足", quota_problem)
                return
            lines = "\n".join(f"  - {code}: {g:.2f} g" for code, g in station.grams.items())
            QMessageBox.information(
                self, "人工配墨指引",
                f"色位【{station.name}】请人工按以下清单逐项称量倒入调墨桶：\n{lines}"
            )
            self._consume_ink_stock(station.grams)
            return

        quota_problem = self._check_ink_quota(station.grams)
        if quota_problem:
            QMessageBox.warning(self, "油墨额度不足", quota_problem)
            return

        if self._auto_worker is not None and self._auto_worker.isRunning():
            QMessageBox.warning(self, "提示", "当前已有自动滴定任务在执行中。")
            return

        self.dispenser.reset_safety()
        self.start_btn.setEnabled(False)
        self.execution_log_label.setText(f"执行日志：色位【{station.name}】全自动滴定启动中……")

        self._auto_worker = AutoDispenseWorker(self.scale, self.dispenser, dict(station.grams))
        self._auto_worker.stage_changed.connect(self._on_stage_changed)
        self._auto_worker.ink_finished.connect(self._on_ink_finished)
        self._auto_worker.all_finished.connect(self._on_all_finished)
        self._auto_worker.error_occurred.connect(self._on_worker_error)
        self._auto_worker.start()

    def _check_ink_quota(self, grams: dict) -> str:
        """子账户执行前检查用量是否超出被分配的额度；管理员不受限制。"""
        if not self.user_repo or not self.current_username:
            return ""
        problems = []
        for code, g in grams.items():
            if g <= 0:
                continue
            record = self.ink_repo.get_by_code(code)
            density = (record.get("density", 1.0) or 1.0) if record else 1.0
            ml_needed = g / density
            remaining = self.user_repo.get_remaining_allocation(self.current_username, code)
            if remaining is not None and ml_needed > remaining:
                name = record["name"] if record else code
                problems.append(f"[{code}] {name}：需要{ml_needed:.0f}ml，你的剩余额度只有{remaining:.0f}ml")
        if problems:
            return "以下油墨超出了你被分配到的额度，请联系管理员增加分配：\n" + "\n".join(problems)
        return ""

    def _consume_ink_stock(self, grams: dict):
        """配墨执行后按配方克重换算成毫升,从对应油墨库存扣减,扣光则禁用并提醒补货。子账户同步累计个人用量。"""
        depleted_names = []
        for code, g in grams.items():
            if g <= 0:
                continue
            record = self.ink_repo.get_by_code(code)
            if record is None:
                continue
            density = record.get("density", 1.0) or 1.0
            ml_used = g / density
            updated = self.ink_repo.adjust_stock(code, -ml_used)
            if updated and self.ink_repo.stock_status(updated) == "缺货":
                depleted_names.append(f"[{code}] {updated['name']}")
            if self.user_repo and self.current_username:
                self.user_repo.record_ink_usage(self.current_username, code, ml_used)

        # ★ 库存已变，广播给全系统重新读盘（见信号定义处的说明）
        self.ink_db_changed.emit()

        self.refresh_ink_checklist()
        if depleted_names:
            names_text = "、".join(depleted_names)
            QMessageBox.warning(
                self, "油墨库存已用完",
                f"以下油墨库存已用完：\n{names_text}\n\n请联系油墨供应商补货。"
                f"在补充库存之前，这些油墨已从选墨列表中自动禁用，暂时无法参与配方寻优。"
            )

    def _on_stage_changed(self, ink_code: str, stage_text: str, weight: float):
        self.execution_log_label.setText(f"执行日志：[{ink_code}] 当前阶段：{stage_text}  |  实时重量：{weight:.2f} g")

    def _on_ink_finished(self, ink_code: str, success: bool, final_weight: float):
        status = "✅命中" if success else "⚠️偏差超限"
        self.execution_log_label.setText(f"执行日志：[{ink_code}] 滴定完成，最终重量 {final_weight:.2f} g（{status}）")

    def _on_all_finished(self, all_ok: bool):
        self.start_btn.setEnabled(True)
        name = self._current_station.name if self._current_station else ""
        if all_ok:
            self.status_normal.emit(f"色位【{name}】全自动滴定完成，所有分量均命中目标重量。")
            if self._current_station is not None:
                self._consume_ink_stock(self._current_station.grams)
        else:
            self.status_danger.emit(f"色位【{name}】全自动滴定未完全成功，请检查现场并复位后重试。")

    def _on_worker_error(self, message: str):
        self.start_btn.setEnabled(True)
        self.status_danger.emit(message)

    # ================================================================
    # 急停 / 安全（由 MainWindow 全局急停按钮调用）
    # ================================================================

    def trigger_emergency_stop(self):
        self.dispenser.emergency_stop()
        if self._auto_worker is not None and self._auto_worker.isRunning():
            self._auto_worker.request_abort()

    def reset_safety(self):
        self.dispenser.reset_safety()
        self.start_btn.setEnabled(True)

    def shutdown(self):
        if self._auto_worker is not None and self._auto_worker.isRunning():
            self._auto_worker.request_abort()
            self._auto_worker.wait(1000)
