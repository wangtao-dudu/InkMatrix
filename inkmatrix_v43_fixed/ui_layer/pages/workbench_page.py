# -*- coding: utf-8 -*-
"""
workbench_page.py  (UI层 - 配色工作台页面)
==============================================
软件的主操作页面，融合：
    - 目标色三种输入来源：手动输入Lab / 从效果图取色 / CMYK输入(客户CDR色值)
    - 承印物底色选择、在库油墨勾选、智能寻优配方
    - 人工模式 / 全自动滴定模式执行，10Hz闭环轮询（QThread，不阻塞UI）

本页面只依赖 core_layer / dal_layer / hal_layer 的抽象接口，
硬件相关的具体实例（scale/dispenser）由 MainWindow 注入，
本页对"仿真硬件"还是"真实硬件"完全无感知，符合解耦原则。
"""

from typing import Callable, Dict, List

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QStackedWidget, QScrollArea
)

from core_layer.color_convert import lab_to_srgb_approx, cmyk_to_lab
from dal_layer.data_manager import get_material_props
from hal_layer.interfaces import AbstractScale, AbstractDispenser, DispenseStage
from ui_layer.widgets import Card, PrimaryButton, SuccessButton, GhostButton, ColorSwatch, ResponsiveRow
from ui_layer.color_pickers import ImageColorPickerDialog
from ui_layer.color_swatch_library import ColorSwatchPickerDialog
from ui_layer.ink_checklist import InkChecklistWidget
from ui_layer.worker import AutoDispenseWorker


class WorkbenchPage(QWidget):

    DELTA_E_WARNING_THRESHOLD = 3.0

    # 全局状态徽标由 MainWindow 统一展示，本页通过信号上报，不直接持有状态栏控件
    status_normal = pyqtSignal(str)
    status_danger = pyqtSignal(str)
    # ★ 配墨执行会扣减油墨库存，扣完必须通知全系统重新读盘。
    # 之前漏了这个信号，导致：在工作台配完一杯墨，库存明明扣了，但切到
    # 【油墨库管理】/【油墨库存管理】看到的还是打开页面时的旧数字——和
    # "问题3"是同一类 bug，只是发生在另一个入口。
    ink_db_changed = pyqtSignal()

    def __init__(
        self,
        ink_repo,
        bottle_repo,
        get_engine: Callable[[], object],
        scale: AbstractScale,
        dispenser: AbstractDispenser,
        get_allowed_ink_codes=None,
        user_repo=None,
        current_username=None,
        parent=None,
    ):
        super().__init__(parent)
        self.ink_repo = ink_repo
        self.bottle_repo = bottle_repo
        self.get_engine = get_engine
        self.scale = scale
        self.dispenser = dispenser
        self.get_allowed_ink_codes = get_allowed_ink_codes
        self.user_repo = user_repo
        self.current_username = current_username

        self._auto_worker = None
        self._last_formula_grams: Dict[str, float] = {}

        self._build_ui()
        self.refresh_ink_checklist()
        self.refresh_bottle_combo()

    # ================================================================
    # UI 搭建
    # ================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("配色工作台")
        title.setObjectName("PageTitle")
        subtitle = QLabel("设置目标颜色来源、勾选在库油墨，一键寻优并执行配墨")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        body = ResponsiveRow(breakpoint=900)
        body.add_panel(self._wrap_scrollable(self._build_input_card()), 1)
        body.add_panel(self._wrap_scrollable(self._build_output_card()), 1)
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

    # ---------------- 左：目标色与配置输入卡片 ----------------

    def _build_input_card(self) -> Card:
        card = Card("① 目标色输入与配置")
        lay = card.body_layout

        # ---- 目标色来源切换 ----
        lay.addWidget(QLabel("目标色来源："))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["手动输入 Lab 数值", "从效果图取色", "CMYK 输入（客户CDR色值）"])
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        lay.addWidget(self.source_combo)

        self.source_stack = QStackedWidget()
        self.source_stack.addWidget(self._build_manual_hint_widget())
        self.source_stack.addWidget(self._build_image_pick_widget())
        self.source_stack.addWidget(self._build_cmyk_widget())
        lay.addWidget(self.source_stack)

        # ---- 目标 Lab 数值（始终显示，可手动微调）----
        lab_grid = QGridLayout()
        self.spin_L = QDoubleSpinBox(); self.spin_L.setRange(0, 100); self.spin_L.setValue(50.0)
        self.spin_a = QDoubleSpinBox(); self.spin_a.setRange(-128, 128); self.spin_a.setValue(0.0)
        self.spin_b = QDoubleSpinBox(); self.spin_b.setRange(-128, 128); self.spin_b.setValue(0.0)
        for spin in (self.spin_L, self.spin_a, self.spin_b):
            spin.valueChanged.connect(self._update_color_preview)
        lab_grid.addWidget(QLabel("L*"), 0, 0); lab_grid.addWidget(self.spin_L, 0, 1)
        lab_grid.addWidget(QLabel("a*"), 0, 2); lab_grid.addWidget(self.spin_a, 0, 3)
        lab_grid.addWidget(QLabel("b*"), 0, 4); lab_grid.addWidget(self.spin_b, 0, 5)
        lay.addLayout(lab_grid)

        lay.addWidget(QLabel("目标色实时预览："))
        self.color_preview = ColorSwatch(height=50)
        lay.addWidget(self.color_preview)
        self._update_color_preview()

        # ---- 承印物底色 ----
        lay.addWidget(QLabel("承印物 / 瓶身底色："))
        self.bottle_combo = QComboBox()
        lay.addWidget(self.bottle_combo)

        # ---- 在库油墨勾选 ----
        row = QHBoxLayout()
        row.addWidget(QLabel("在库油墨勾选（今日仓库实际可用油墨）："))
        row.addStretch(1)
        refresh_btn = GhostButton("↻ 刷新")
        refresh_btn.clicked.connect(self.refresh_ink_checklist)
        row.addWidget(refresh_btn)
        lay.addLayout(row)

        self.ink_list_widget = InkChecklistWidget(
            self.ink_repo, get_engine=self.get_engine, get_allowed_codes=self.get_allowed_ink_codes
        )
        self.ink_list_widget.setMinimumHeight(300)
        lay.addWidget(self.ink_list_widget, 1)

        # ---- 配墨总重 ----
        total_row = QHBoxLayout()
        total_row.addWidget(QLabel("配墨总重(g)："))
        self.total_weight_spin = QDoubleSpinBox()
        self.total_weight_spin.setRange(1.0, 100000.0)
        self.total_weight_spin.setValue(500.0)
        total_row.addWidget(self.total_weight_spin)
        lay.addLayout(total_row)

        solve_btn = PrimaryButton("🎯 智能寻优配方")
        solve_btn.clicked.connect(self._on_solve_formula)
        lay.addWidget(solve_btn)

        return card

    def _build_manual_hint_widget(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        hint = QLabel("请在下方直接填写目标 L* / a* / b* 数值，或点击下方按钮从色卡快速选择。")
        hint.setStyleSheet("color:#64748b; font-size:12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        swatch_btn = GhostButton("🎨 从色卡选择相近颜色")
        swatch_btn.clicked.connect(self._on_pick_from_swatch)
        lay.addWidget(swatch_btn)
        return w

    def _build_image_pick_widget(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        hint = QLabel("适用场景：客户只提供了成品效果图（渲染图）。在图上点选目标颜色区域（可多点取平均，注意避开高光/阴影)。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:12px;")
        lay.addWidget(hint)
        btn = PrimaryButton("🖼️ 打开效果图取色")
        btn.clicked.connect(self._on_pick_from_image)
        lay.addWidget(btn)
        return w

    def _build_cmyk_widget(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        hint = QLabel(
            "适用场景：客户CDR原始文件里的颜色是CMYK数值。请打开CDR文件读出C/M/Y/K百分比后填入。\n"
            "⚠️ 该换算未绑定实际印刷ICC描述文件，仅为近似估算，请在寻优后结合效果图/实物比对确认。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#b45309; font-size:11px;")
        lay.addWidget(hint)

        grid = QGridLayout()
        self.spin_c = QDoubleSpinBox(); self.spin_c.setRange(0, 100); self.spin_c.setSuffix(" %")
        self.spin_m = QDoubleSpinBox(); self.spin_m.setRange(0, 100); self.spin_m.setSuffix(" %")
        self.spin_y = QDoubleSpinBox(); self.spin_y.setRange(0, 100); self.spin_y.setSuffix(" %")
        self.spin_k = QDoubleSpinBox(); self.spin_k.setRange(0, 100); self.spin_k.setSuffix(" %")
        grid.addWidget(QLabel("C"), 0, 0); grid.addWidget(self.spin_c, 0, 1)
        grid.addWidget(QLabel("M"), 0, 2); grid.addWidget(self.spin_m, 0, 3)
        grid.addWidget(QLabel("Y"), 1, 0); grid.addWidget(self.spin_y, 1, 1)
        grid.addWidget(QLabel("K"), 1, 2); grid.addWidget(self.spin_k, 1, 3)
        lay.addLayout(grid)

        convert_btn = PrimaryButton("⇄ 换算为 Lab 目标色")
        convert_btn.clicked.connect(self._on_convert_cmyk)
        lay.addWidget(convert_btn)
        return w

    # ---------------- 右：配方输出卡片 ----------------

    def _build_output_card(self) -> Card:
        card = Card("② 智能配方输出与执行")
        lay = card.body_layout

        self.formula_table = QTableWidget(0, 3)
        self.formula_table.setHorizontalHeaderLabels(["油墨名称", "配方比例(%)", "精准称重克数(g)"])
        self.formula_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        big_font = QFont()
        big_font.setPointSize(13)
        self.formula_table.setFont(big_font)
        self.formula_table.verticalHeader().setDefaultSectionSize(36)
        self.formula_table.setMinimumHeight(220)
        lay.addWidget(self.formula_table, 1)

        result_row = QHBoxLayout()
        self.predicted_lab_label = QLabel("预测Lab: --")
        self.delta_e_label = QLabel("ΔE: --")
        for lbl in (self.predicted_lab_label, self.delta_e_label):
            lbl.setStyleSheet("font-weight:600;")
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

        self.start_btn = SuccessButton("▶ 开始执行配墨")
        self.start_btn.clicked.connect(self._on_start_execution)
        lay.addWidget(self.start_btn)

        self.execution_log_label = QLabel("执行日志：等待开始……")
        self.execution_log_label.setWordWrap(True)
        self.execution_log_label.setStyleSheet("color:#475569; font-size:12px;")
        lay.addWidget(self.execution_log_label)

        return card

    # ================================================================
    # 目标色来源切换逻辑
    # ================================================================

    def _on_source_changed(self, index: int):
        self.source_stack.setCurrentIndex(index)

    def _on_pick_from_swatch(self):
        dlg = ColorSwatchPickerDialog(self, title="从色卡选择相近目标色")
        if dlg.exec():
            L, a, b = dlg.get_result_lab()
            self.spin_L.setValue(round(L, 2))
            self.spin_a.setValue(round(a, 2))
            self.spin_b.setValue(round(b, 2))
            self.status_normal.emit(f"已从色卡选定目标色，Lab=({L:.2f},{a:.2f},{b:.2f})。")

    def _on_pick_from_image(self):
        dlg = ImageColorPickerDialog(self, title="效果图取色 —— 还原客户成品渲染图颜色")
        if dlg.exec():
            L, a, b = dlg.get_result_lab()
            self.spin_L.setValue(round(L, 2))
            self.spin_a.setValue(round(a, 2))
            self.spin_b.setValue(round(b, 2))
            self.status_normal.emit(f"已从效果图取色，目标Lab=({L:.2f},{a:.2f},{b:.2f})，可在上方数值框继续微调。")

    def _on_convert_cmyk(self):
        c, m, y, k = self.spin_c.value(), self.spin_m.value(), self.spin_y.value(), self.spin_k.value()
        L, a, b = cmyk_to_lab(c, m, y, k)
        self.spin_L.setValue(round(L, 2))
        self.spin_a.setValue(round(a, 2))
        self.spin_b.setValue(round(b, 2))
        self.status_normal.emit(
            f"CMYK({c:.0f},{m:.0f},{y:.0f},{k:.0f}) 已近似换算为 Lab=({L:.2f},{a:.2f},{b:.2f})（近似值，非ICC精确换算）"
        )

    def _update_color_preview(self):
        r, g, b = lab_to_srgb_approx(self.spin_L.value(), self.spin_a.value(), self.spin_b.value())
        self.color_preview.set_rgb(r, g, b)

    # ================================================================
    # 数据刷新
    # ================================================================

    def refresh_ink_checklist(self):
        self.ink_list_widget.refresh()

    def refresh_bottle_combo(self):
        current_code = self.bottle_combo.currentData()
        self.bottle_combo.clear()
        for record in self.bottle_repo.load_all():
            self.bottle_combo.addItem(f"[{record['code']}] {record['name']}", record["code"])
        if current_code:
            idx = self.bottle_combo.findData(current_code)
            if idx >= 0:
                self.bottle_combo.setCurrentIndex(idx)

    def _get_checked_ink_codes(self) -> List[str]:
        return self.ink_list_widget.get_checked_codes()

    # ================================================================
    # 配方寻优
    # ================================================================

    def _on_solve_formula(self):
        checked = self._get_checked_ink_codes()
        if not checked:
            QMessageBox.warning(self, "提示", "请至少勾选一种在库油墨后再进行寻优。")
            return

        target_lab = (self.spin_L.value(), self.spin_a.value(), self.spin_b.value())
        white_codes = [r["code"] for r in self.ink_repo.load_all() if r.get("category") == "white"]
        substrate_lab = self._get_selected_bottle_lab()
        material_props = self._get_selected_material_props()

        engine = self.get_engine()
        try:
            result = engine.solve_formula(
                target_lab, checked, white_codes,
                substrate_lab=substrate_lab,
                material_props=material_props,   # 材质进算法：吸墨补偿 + 遮盖需求 + 附着力预警
            )
        except ValueError as exc:
            QMessageBox.warning(self, "寻优失败", str(exc))
            return

        total_grams = self.total_weight_spin.value()
        grams = engine.weights_to_grams(result.weights, total_grams)
        self._last_formula_grams = grams

        self._populate_formula_table(result.weights, grams)
        self.predicted_lab_label.setText("预测Lab: (%.2f, %.2f, %.2f)" % result.predicted_lab)
        ink_count = sum(1 for v in result.weights.values() if v > 0)
        de_text = "ΔE: %.3f  |  用墨%d种" % (result.delta_e, ink_count)
        if result.ink_count_simplified:
            de_text += "（已精简）"
        self.delta_e_label.setText(de_text)

        if result.delta_e > self.DELTA_E_WARNING_THRESHOLD:
            msg = f"色差超标预警！ΔE={result.delta_e:.2f} 超过工业容差 {self.DELTA_E_WARNING_THRESHOLD}"
            if result.warning:
                msg += f"；{result.warning}"
            self.status_danger.emit(msg)
        elif substrate_lab is not None and result.opacity_estimate < 0.7:
            self.status_danger.emit(
                f"配方寻优完成（ΔE={result.delta_e:.2f}），但遮盖力估算约{result.opacity_estimate*100:.0f}%，"
                f"瓶身底色可能透出影响实际效果，建议增加白墨占比。"
            )
        else:
            msg = "配方寻优完成，色差在工业容差范围内。"
            if result.white_auto_triggered:
                msg += f"（{result.warning}）"
            self.status_normal.emit(msg)

    def _get_selected_material_props(self):
        """
        取当前选中承印物的材质物理参数，交给配色引擎。

        材质不是一个"标签"而已——它实打实地改变印出来的颜色：
          · 纸/粗糙塑料会吸墨，墨膜变薄，同一配方颜色会偏浅偏灰
          · 棕玻璃/铜/铝底色深或有金属光泽，遮盖需求高，浅色压不住
        引擎拿到这两个系数后会自动补偿，不用人再去凭经验加白墨。
        """
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
    # 执行（人工模式 / 全自动滴定模式）
    # ================================================================

    def _on_start_execution(self):
        if not self._last_formula_grams:
            QMessageBox.warning(self, "提示", "请先完成【智能寻优配方】后再执行配墨。")
            return

        quota_problem = self._check_ink_quota(self._last_formula_grams)
        if quota_problem:
            QMessageBox.warning(self, "油墨额度不足", quota_problem)
            return

        if self.mode_combo.currentText() == "人工模式":
            lines = "\n".join(f"  - {code}: {g:.2f} g" for code, g in self._last_formula_grams.items())
            QMessageBox.information(self, "人工配墨指引", f"请人工按以下清单逐项称量倒入调墨桶：\n{lines}")
            self._consume_ink_stock(self._last_formula_grams)
            return

        if self._auto_worker is not None and self._auto_worker.isRunning():
            QMessageBox.warning(self, "提示", "当前已有自动滴定任务在执行中。")
            return

        self.dispenser.reset_safety()
        self.start_btn.setEnabled(False)
        self.execution_log_label.setText("执行日志：全自动滴定模式启动中……")

        self._auto_worker = AutoDispenseWorker(self.scale, self.dispenser, dict(self._last_formula_grams))
        self._auto_worker.stage_changed.connect(self._on_stage_changed)
        self._auto_worker.ink_finished.connect(self._on_ink_finished)
        self._auto_worker.all_finished.connect(self._on_all_finished)
        self._auto_worker.error_occurred.connect(self._on_worker_error)
        self._auto_worker.start()

    def _check_ink_quota(self, grams: dict) -> str:
        """
        子账户执行前检查：这次要用的每支墨，够不够自己被分配到的额度。
        管理员账户（user_repo.get_remaining_allocation返回None）不受限制。
        返回空字符串表示没问题；返回非空字符串就是要展示的错误信息。
        """
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
        """
        配墨执行后，按配方克重换算成毫升，从对应油墨的库存里扣掉。
        扣到缺货（<=0）的墨，会自动在选墨列表里被禁用，并弹窗提醒联系供应商。
        子账户还会同步累计个人用量，供额度检查使用。
        """
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

        # 库存已经变了 → 通知全系统重新读盘（油墨库管理表格、库存总览、
        # 工单页的选墨列表、账户管理的分配额度，全部跟着刷新）
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
        if all_ok:
            self.status_normal.emit("全自动滴定配墨完成，所有分量均命中目标重量。")
            self._consume_ink_stock(self._last_formula_grams)
        else:
            self.status_danger.emit("全自动滴定流程未完全成功，请检查现场并复位后重试。")

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
