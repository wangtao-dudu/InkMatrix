# -*- coding: utf-8 -*-
"""
ink_library_page.py  (UI层 - 油墨基因库管理页面，视觉升级版)
==================================================================
把原来挤在工作台里的"新增/删除油墨"简易入口，独立成一个正式的
档案管理页面：表格形式展示全部在库油墨（编号/名称/类别/密度/
干燥系数/颜色预览色块），支持新增、编辑、删除、搜索筛选。

视觉设计要点（对齐中高端管理后台的常见语言）：
    - 顶部数据总览卡片（总数/各类别数量），一眼看清库存构成
    - 颜色预览做成圆角色卡而不是整格纯色底色
    - 类别用彩色圆角标签展示，替代裸英文字符串
    - 更大的行高、字号，留白更充分，减少"表格拥挤感"
    - 搜索框 + 类别筛选，油墨种类多起来也能快速定位

对应 DAL 层需求：工厂随时新购进的任意油墨号都可以在此录入。
"""

from typing import Callable, List, Dict

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QMessageBox, QFrame, QTabWidget, QDateEdit, QTextEdit, QFileDialog,
    QScrollArea, QApplication, QDialogButtonBox
)

from core_layer.color_convert import lab_to_srgb_approx, srgb_to_lab
from core_layer.color_engine import KubelkaMunkEngine, InkSpectralData
from core_layer.ink_synthesis import synthesize_ink_spectrum
from ui_layer.widgets import Card, PrimaryButton, GhostButton, DangerButton, Badge, StatCard, ColorSwatch
from ui_layer.ink_meta import CATEGORY_META, category_label as _category_label, category_color as _category_color
from ui_layer.color_wheel import ColorWheelPanel


class AddInkDialog(QDialog):
    """新增/编辑油墨基因档案对话框（视觉升级版：分区块 + 实时颜色预览）。"""

    def __init__(self, parent=None, existing: dict = None, ink_repo=None):
        super().__init__(parent)
        self.setWindowTitle("编辑油墨基因档案" if existing else "新增油墨基因档案")
        self.setMinimumWidth(520)
        self._existing = existing
        self._ink_repo = ink_repo
        self._synthesized_K = None  # 从色相环反推出的完整光谱(非None时优先于平均K/S)
        self._synthesized_S = None
        self._wheel_lab = (50.0, 0.0, 0.0)
        self._build_ui()
        if existing:
            self._load_existing(existing)
        self._on_wheel_color_picked(*self.wheel_panel.current_rgb())
        self._update_preview()

    def _build_ui(self):
        # ────────────────────────────────────────────────────────────
        # 【对话框底部被切掉，保存按钮点不到】修复
        # ────────────────────────────────────────────────────────────
        # 以前这个对话框是直接往 self 上堆 QVBoxLayout，没有滚动区，也没有高度
        # 上限。内容越加越多（尤其是后来加的 Lab 输入区和几段说明文字），对话框
        # 就一直往下长，最后长得比屏幕还高——底部的【保存/取消】按钮被挤到屏幕
        # 外面，用户根本点不到，等于"新增油墨"这个功能直接不能用。
        #
        # 而且笔记本屏幕（1366×768 这类）比台式机矮得多。在开发机上看着正常的
        # 布局，到用户那儿就是残的——这种问题只有真机跑一遍才会暴露。
        #
        # 修法三件事：
        #   1. 所有内容塞进 QScrollArea：长了就滚动，不再顶破屏幕
        #   2. 【保存/取消】按钮放在滚动区【外面】，永远钉在对话框底部，
        #      不管里面内容有多长都点得到
        #   3. 对话框高度按【当前屏幕可用高度的 85%】封顶，且允许拖动改大小
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ---- 基础信息 ----
        section1 = QLabel("基础信息")
        section1.setStyleSheet("font-size:13px; font-weight:700; color:#0f172a;")
        root.addWidget(section1)

        form1 = QFormLayout()
        form1.setSpacing(10)
        self.code_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.category_combo = QComboBox()
        for code, meta in CATEGORY_META.items():
            self.category_combo.addItem(meta["label"], code)
        form1.addRow("油墨编号（唯一）：", self.code_edit)
        form1.addRow("油墨名称：", self.name_edit)
        form1.addRow("类别：", self.category_combo)
        root.addLayout(form1)

        divider1 = QFrame(); divider1.setFrameShape(QFrame.Shape.HLine)
        divider1.setStyleSheet("color:#e2e8f0;")
        root.addWidget(divider1)

        # ---- 物理参数 ----
        section2 = QLabel("物理参数")
        section2.setStyleSheet("font-size:13px; font-weight:700; color:#0f172a;")
        root.addWidget(section2)

        form2 = QFormLayout()
        form2.setSpacing(10)
        self.density_spin = QDoubleSpinBox(); self.density_spin.setRange(0.5, 3.0); self.density_spin.setValue(1.05)
        self.density_spin.setSuffix(" g/ml")
        self.dryback_spin = QDoubleSpinBox(); self.dryback_spin.setRange(0.0, 1.0)
        self.dryback_spin.setSingleStep(0.05); self.dryback_spin.setValue(0.25)
        form2.addRow("密度：", self.density_spin)
        form2.addRow("干燥修正系数(0~1)：", self.dryback_spin)

        # ---- 库存：只读展示，不能在这里改（问题3修复） ----
        #
        # 为什么要改成只读：库存的唯一真值源是【油墨库存管理】页的进出库
        # 流水。以前这里放了一个可编辑的输入框，就出现了这样的事故：
        #   仓管在【油墨库存管理】入库 500ml → 库存 5000 变 5500
        #   老板在【油墨库管理】随手改了一下这支墨的名字并保存
        #   → 保存时把对话框打开那一刻读到的旧库存 5000 又写了回去
        #   → 那 500ml 凭空消失，两个页面的数字对不上
        # 现在库存在这里只能看不能改，要改必须去【油墨库存管理】走正规
        # 的采购入库/销售出库流程，账实才能永远对得上。
        self.stock_readonly_label = QLabel("－")
        self.stock_readonly_label.setStyleSheet(
            "color:#0f172a; font-weight:700; background:#f1f5f9; "
            "border:1px solid #e2e8f0; border-radius:6px; padding:6px 10px;"
        )
        form2.addRow("当前库存：", self.stock_readonly_label)

        self.low_stock_readonly_label = QLabel("－")
        self.low_stock_readonly_label.setStyleSheet("color:#64748b; padding:2px 0;")
        form2.addRow("低库存预警线：", self.low_stock_readonly_label)
        root.addLayout(form2)

        stock_hint = QLabel(
            "🔒 库存数量在此处只读。所有入库/出库都必须走【油墨库存管理】页，"
            "那里是库存的唯一入口——这样账面数量和实际进出流水才能永远对得上，"
            "两个页面看到的永远是同一个数字。"
        )
        stock_hint.setWordWrap(True)
        stock_hint.setStyleSheet("color:#0d9488; font-size:11px; background:#f0fdfa; "
                                 "border-radius:6px; padding:8px 10px;")
        root.addWidget(stock_hint)

        divider2 = QFrame(); divider2.setFrameShape(QFrame.Shape.HLine)
        divider2.setStyleSheet("color:#e2e8f0;")
        root.addWidget(divider2)

        # ---- 指定油墨颜色：Lab精确输入 或 色相环点选 ----
        section_wheel = QLabel("指定这支油墨的颜色（自动推导出带色相的K/S光谱）")
        section_wheel.setStyleSheet("font-size:13px; font-weight:700; color:#0f172a;")
        root.addWidget(section_wheel)
        wheel_hint = QLabel(
            "两种方式，任选其一：<br>"
            "<b>① 直接填 Lab 值（推荐）</b> —— 如果你有色差仪/分光测色仪，测出来的就是这三个数，"
            "直接填进去，这是最准的。<br>"
            "<b>② 在色相环上点选</b> —— 没有仪器时用鼠标大概点一个，属于目测，精度有限。<br>"
            "两边是联动的：改 Lab 色相环会跟着动，点色相环 Lab 也会跟着变。"
        )
        wheel_hint.setWordWrap(True)
        wheel_hint.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(wheel_hint)

        # ① Lab 精确输入
        lab_row = QHBoxLayout()
        lab_row.addWidget(QLabel("L*"))
        self.lab_l_spin = QDoubleSpinBox()
        self.lab_l_spin.setRange(0, 100); self.lab_l_spin.setDecimals(2)
        self.lab_l_spin.setValue(50.0); self.lab_l_spin.setSingleStep(1.0)
        self.lab_l_spin.setToolTip("明度：0=纯黑，100=纯白")
        lab_row.addWidget(self.lab_l_spin)

        lab_row.addWidget(QLabel("a*"))
        self.lab_a_spin = QDoubleSpinBox()
        self.lab_a_spin.setRange(-128, 127); self.lab_a_spin.setDecimals(2)
        self.lab_a_spin.setValue(0.0); self.lab_a_spin.setSingleStep(1.0)
        self.lab_a_spin.setToolTip("绿←→红：负数偏绿，正数偏红")
        lab_row.addWidget(self.lab_a_spin)

        lab_row.addWidget(QLabel("b*"))
        self.lab_b_spin = QDoubleSpinBox()
        self.lab_b_spin.setRange(-128, 127); self.lab_b_spin.setDecimals(2)
        self.lab_b_spin.setValue(0.0); self.lab_b_spin.setSingleStep(1.0)
        self.lab_b_spin.setToolTip("蓝←→黄：负数偏蓝，正数偏黄")
        lab_row.addWidget(self.lab_b_spin)

        apply_lab_btn = PrimaryButton("✓ 用这个Lab")
        apply_lab_btn.clicked.connect(self._on_apply_lab_input)
        lab_row.addWidget(apply_lab_btn)
        root.addLayout(lab_row)

        # 允许色差：来料检验的判据。
        # 供应商送来一桶墨，实测 Lab 跟上面这个标准 Lab 一比，ΔE 超过这个数
        # 就是不合格，可以直接退货。行业惯例：黑色人眼最敏感，公差最严(1.0~1.2)；
        # 常规彩色 1.5；饱和度极高的色（射光蓝、紫罗兰、绿）本来就难做准，放宽到 2.0。
        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("允许色差 ΔE*ab："))
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.1, 20.0)
        self.tolerance_spin.setDecimals(1)
        self.tolerance_spin.setSingleStep(0.1)
        self.tolerance_spin.setValue(2.0)
        self.tolerance_spin.setToolTip(
            "来料检验的判据：供应商送来的墨，实测Lab跟上面的标准Lab比，\n"
            "ΔE超过这个数就是不合格。\n\n"
            "行业惯例：黑色 1.0~1.2（人眼对中性色最敏感）、常规彩色 1.5、\n"
            "高饱和色（射光蓝/紫罗兰/绿）2.0"
        )
        tol_row.addWidget(self.tolerance_spin)
        tol_row.addStretch(1)
        root.addLayout(tol_row)

        lab_tip = QLabel(
            "📏 用色差仪测这支墨的时候：印一块<b>厚实、完全遮盖</b>的墨块（不能透底），"
            "<b>彻底干燥后</b>再测——湿墨的读数是没用的。"
        )
        lab_tip.setWordWrap(True)
        lab_tip.setStyleSheet("color:#0d9488; font-size:11px; background:#f0fdfa; "
                              "border-radius:6px; padding:7px 9px;")
        root.addWidget(lab_tip)

        # ② 色相环点选
        wheel_row = QHBoxLayout()
        self.wheel_panel = ColorWheelPanel(diameter=150)
        self.wheel_panel.color_picked.connect(self._on_wheel_color_picked)
        wheel_row.addWidget(self.wheel_panel)

        wheel_preview_col = QVBoxLayout()
        wheel_preview_col.addWidget(QLabel("当前选中："))
        self.wheel_preview_swatch = ColorSwatch(height=48)
        self.wheel_preview_swatch.setFixedWidth(90)
        wheel_preview_col.addWidget(self.wheel_preview_swatch)
        self.wheel_lab_label = QLabel("Lab: --")
        self.wheel_lab_label.setStyleSheet("color:#64748b; font-size:11px;")
        self.wheel_lab_label.setWordWrap(True)
        wheel_preview_col.addWidget(self.wheel_lab_label)
        wheel_preview_col.addStretch(1)
        wheel_row.addLayout(wheel_preview_col)

        wheel_actions = QVBoxLayout()
        derive_btn = PrimaryButton("✨ 自动推导光谱并应用")
        derive_btn.clicked.connect(self._on_derive_spectrum)
        wheel_actions.addWidget(derive_btn)

        search_btn = GhostButton("🔍 查找库内相近颜色")
        search_btn.clicked.connect(self._on_search_similar)
        wheel_actions.addWidget(search_btn)

        self.similar_list = QLabel("（尚未查找）")
        self.similar_list.setWordWrap(True)
        self.similar_list.setStyleSheet("color:#64748b; font-size:11px;")
        wheel_actions.addWidget(self.similar_list)
        wheel_actions.addStretch(1)
        wheel_row.addLayout(wheel_actions, 1)
        root.addLayout(wheel_row)

        divider3 = QFrame(); divider3.setFrameShape(QFrame.Shape.HLine)
        divider3.setStyleSheet("color:#e2e8f0;")
        root.addWidget(divider3)

        # ---- 光谱参数 + 实时预览 ----
        section3 = QLabel("光谱参数（简化录入 / 平均K-S，仅能做灰阶）")
        section3.setStyleSheet("font-size:13px; font-weight:700; color:#0f172a;")
        root.addWidget(section3)
        hint = QLabel("没有分光测色仪时，可只填一个近似的平均K/S数值；有条件建议后续用实测光谱数据替换，寻优会更准。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94a3b8; font-size:11px;")
        root.addWidget(hint)

        spectral_row = QHBoxLayout()
        form3 = QFormLayout()
        form3.setSpacing(10)
        self.avg_k_spin = QDoubleSpinBox(); self.avg_k_spin.setRange(0.0, 500.0); self.avg_k_spin.setValue(20.0)
        self.avg_s_spin = QDoubleSpinBox(); self.avg_s_spin.setRange(0.1, 500.0); self.avg_s_spin.setValue(10.0)
        self.avg_k_spin.valueChanged.connect(self._on_manual_ks_edit)
        self.avg_s_spin.valueChanged.connect(self._on_manual_ks_edit)
        form3.addRow("平均吸收系数 K：", self.avg_k_spin)
        form3.addRow("平均散射系数 S：", self.avg_s_spin)
        spectral_row.addLayout(form3, 1)

        preview_col = QVBoxLayout()
        preview_col.addWidget(QLabel("纯色预览："))
        self.preview_swatch = ColorSwatch(height=56)
        self.preview_swatch.setFixedWidth(100)
        preview_col.addWidget(self.preview_swatch)
        preview_col.addStretch(1)
        spectral_row.addLayout(preview_col)
        root.addLayout(spectral_row)

        root.addStretch(1)

        # ---- 滚动区装完内容 ----
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ---- 按钮：钉在滚动区外面，永远在对话框底部可见 ----
        btn_bar = QWidget()
        btn_bar.setStyleSheet("background:#f8fafc; border-top:1px solid #e2e8f0;")
        btn_row = QHBoxLayout(btn_bar)
        btn_row.setContentsMargins(28, 12, 28, 12)
        btn_row.addStretch(1)
        cancel_btn = GhostButton("取消")
        ok_btn = PrimaryButton("💾 保存")
        ok_btn.clicked.connect(self._on_save_clicked)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        outer.addWidget(btn_bar)

        self._fit_to_screen()

    def _fit_to_screen(self):
        """
        按当前屏幕的【可用高度】给对话框封顶，避免在小屏笔记本上顶出屏幕。

        用 availableGeometry 而不是 geometry：前者已经扣掉了任务栏/Dock，
        才是真正能用的空间。留 85% 是给标题栏和一点边距留余量。
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(560, 700)
            return
        avail = screen.availableGeometry()
        max_h = int(avail.height() * 0.85)

        # 先问问内容自然想要多高，再和上限取小
        wanted_h = self.sizeHint().height()
        self.resize(min(600, avail.width() - 40), min(wanted_h, max_h))
        self.setMaximumHeight(max_h)

    def _load_existing(self, existing: dict):
        self.code_edit.setText(existing["code"])
        self.code_edit.setEnabled(False)  # 编号作为主键，编辑时不可改
        self.name_edit.setText(existing["name"])
        idx = self.category_combo.findData(existing.get("category", "color"))
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        self.density_spin.setValue(existing.get("density", 1.05))
        self.dryback_spin.setValue(existing.get("dry_back_factor", 0.25))

        # 库存只读展示，同时把 ml 换算成 g 一并显示（问题2）：
        # 库存按体积(ml)记，配墨按重量(g)称，两者靠密度换算，这里直接
        # 两个数字都摆出来，师傅一眼就知道"这桶墨还能称出多少克"。
        stock_ml = existing.get("stock_ml", 0.0) or 0.0
        density = existing.get("density", 1.05) or 1.05
        self.stock_readonly_label.setText(
            f"{stock_ml:g} ml  ≈  {stock_ml * density:.0f} g   （按密度 {density:.2f} g/ml 换算）"
        )
        self.low_stock_readonly_label.setText(
            f"{existing.get('low_stock_threshold_ml', 100.0) or 0.0:g} ml"
            f"（可在【油墨库存管理】页调整）"
        )
        self.tolerance_spin.setValue(existing.get("delta_e_tolerance", 2.0) or 2.0)

        # 有标准 Lab 的，把它回填到 Lab 输入框里，并保留原有的 K/S 光谱
        # （不要重新推导——原来的光谱可能是分光光度计实测的，重推会把好数据毁掉）
        ref = existing.get("ref_lab")
        if ref and len(ref) == 3:
            self._wheel_lab = tuple(ref)
            for spin, val in ((self.lab_l_spin, ref[0]), (self.lab_a_spin, ref[1]),
                              (self.lab_b_spin, ref[2])):
                spin.blockSignals(True)
                spin.setValue(float(val))
                spin.blockSignals(False)
            self.wheel_preview_swatch.set_rgb(*lab_to_srgb_approx(*ref))
            self._synthesized_K = np.array(existing.get("K", []))
            self._synthesized_S = np.array(existing.get("S", []))
            src = "（K/S为Lab推算）" if existing.get("ks_from_lab") else "（K/S为实测）"
            self.wheel_lab_label.setText(
                f"Lab({ref[0]:.2f}, {ref[1]:.2f}, {ref[2]:.2f})\n← 档案里的标准值\n{src}"
            )

        k_arr = existing.get("K", [20.0])
        s_arr = existing.get("S", [10.0])
        self.avg_k_spin.setValue(float(np.mean(k_arr)))
        self.avg_s_spin.setValue(float(np.mean(s_arr)))

    def _update_preview(self):
        """预览色块：如果刚从色相环反推过光谱，优先显示那条曲线的呈色；否则用平均K/S(灰阶)。"""
        try:
            if self._synthesized_K is not None:
                k_arr, s_arr = self._synthesized_K, self._synthesized_S
            else:
                k_arr = np.array([self.avg_k_spin.value()] * 31)
                s_arr = np.array([self.avg_s_spin.value()] * 31)
            tmp_ink = InkSpectralData(code="_preview", name="_preview", K=k_arr, S=s_arr)
            engine = KubelkaMunkEngine([tmp_ink])
            lab = engine.compute_lab({"_preview": 1.0}, apply_dry_back=False)
            r, g, b = lab_to_srgb_approx(*lab)
        except Exception:
            r, g, b = 200, 200, 200
        self.preview_swatch.set_rgb(r, g, b)

    def _on_apply_lab_input(self):
        """
        用手填的 Lab 值定这支油墨的颜色。

        这是给有色差仪/分光测色仪的人用的——他们手上就是精确的三个数字，
        以前却只能拿鼠标在色相环上"大概点一下"，等于把仪器测出来的精确数据
        硬生生降级成了目测。现在可以直接填。

        填完会同步更新色相环的预览色块，两边保持一致。
        """
        L = self.lab_l_spin.value()
        a = self.lab_a_spin.value()
        b = self.lab_b_spin.value()
        self._wheel_lab = (L, a, b)

        r, g, bb = lab_to_srgb_approx(L, a, b)
        self.wheel_preview_swatch.set_rgb(r, g, bb)
        self.wheel_lab_label.setText(f"Lab({L:.2f}, {a:.2f}, {b:.2f})\n← 手工输入")

        # 直接把光谱也推出来，省得用户还要再点一次"自动推导"
        self._on_derive_spectrum()

    def _on_wheel_color_picked(self, r: int, g: int, b: int):
        self._wheel_lab = srgb_to_lab(r, g, b)
        self.wheel_preview_swatch.set_rgb(r, g, b)
        L, a, bb = self._wheel_lab

        # 反向同步到 Lab 输入框，让用户看到自己点的这个位置对应什么数值
        # （blockSignals 是为了防止改值时又触发别的联动，绕成死循环）
        for spin, val in ((self.lab_l_spin, L), (self.lab_a_spin, a), (self.lab_b_spin, bb)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

        self.wheel_lab_label.setText(f"RGB({r},{g},{b})\nLab({L:.1f},{a:.1f},{bb:.1f})\n← 色相环点选")

    def _on_derive_spectrum(self):
        result = synthesize_ink_spectrum(self._wheel_lab)
        self._synthesized_K = result["K"]
        self._synthesized_S = result["S"]
        # 平均K/S数值框也同步显示一下（仅供参考，实际保存时优先用反推出的完整曲线）
        self.avg_k_spin.blockSignals(True)
        self.avg_s_spin.blockSignals(True)
        self.avg_k_spin.setValue(float(np.mean(result["K"])))
        self.avg_s_spin.setValue(float(np.mean(result["S"])))
        self.avg_k_spin.blockSignals(False)
        self.avg_s_spin.blockSignals(False)
        self._update_preview()
        QMessageBox.information(
            self, "已生成",
            f"已根据色相环选色反推出带色相的光谱曲线（跟目标色的差距 ΔE={result['achieved_delta_e']:.2f}），"
            f"点【保存】即可写入这支油墨的完整光谱。"
        )

    def _on_search_similar(self):
        if self._ink_repo is None:
            self.similar_list.setText("（未连接油墨库，无法搜索）")
            return
        records = self._ink_repo.load_all()
        if not records:
            self.similar_list.setText("（油墨库为空）")
            return

        scored = []
        for r in records:
            try:
                ink = InkSpectralData(code=r["code"], name=r["name"], K=np.array(r["K"]), S=np.array(r["S"]))
                engine = KubelkaMunkEngine([ink])
                lab = engine.compute_lab({r["code"]: 1.0}, apply_dry_back=False)
                de = engine.delta_e_76(lab, self._wheel_lab)
                scored.append((de, r["name"], r["code"]))
            except Exception:
                continue
        scored.sort(key=lambda x: x[0])
        top5 = scored[:5]
        if not top5:
            self.similar_list.setText("（没有可比较的油墨）")
            return
        lines = [f"{name}[{code}] ΔE={de:.1f}" for de, name, code in top5]
        self.similar_list.setText("库内相近颜色：\n" + "\n".join(lines))

    def _on_manual_ks_edit(self):
        # 用户手动改了平均K/S数值，说明不再采用色相环反推的那条曲线，回到"灰阶模式"
        self._synthesized_K = None
        self._synthesized_S = None
        self._update_preview()

    def _on_save_clicked(self):
        # 保险检查：色相环选了明显有色相的颜色，但用户忘了点"自动推导光谱并应用"，
        # 直接保存的话这支墨会变成没有色相的灰阶——这是个真实发生过的误操作，
        # 这里主动提醒一下，而不是让它悄无声息地存错。
        if self._synthesized_K is None:
            L, a, b = self._wheel_lab
            chroma = (a ** 2 + b ** 2) ** 0.5
            k_val, s_val = self.avg_k_spin.value(), self.avg_s_spin.value()
            looks_untouched = abs(k_val - 20.0) < 0.01 and abs(s_val - 10.0) < 0.01
            if chroma > 15 and looks_untouched:
                choice = QMessageBox.question(
                    self, "还没应用色相环选色",
                    f"检测到你在色相环上选了一个明显带颜色的目标（Lab≈{L:.0f},{a:.0f},{b:.0f}），"
                    f"但还没点击【✨ 自动推导光谱并应用】——现在保存的话，这支墨会是没有色相的灰阶。\n\n"
                    f"要不要现在自动应用这个颜色再保存？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                )
                if choice == QMessageBox.StandardButton.Cancel:
                    return
                if choice == QMessageBox.StandardButton.Yes:
                    self._on_derive_spectrum()
        self.accept()

    def get_record(self) -> dict:
        n_points = len(self._existing["K"]) if self._existing else 31
        if self._synthesized_K is not None:
            k_list = [float(v) for v in self._synthesized_K]
            s_list = [float(v) for v in self._synthesized_S]
        else:
            k_val = self.avg_k_spin.value()
            s_val = self.avg_s_spin.value()
            k_list = [k_val] * n_points
            s_list = [s_val] * n_points
        # 注意：这里【故意不返回 stock_ml / low_stock_threshold_ml】。
        # 库存不归本对话框管，保存时由 InkRepository.upsert_meta() 从磁盘上
        # 的最新记录里原样继承过去，避免覆盖掉【油墨库存管理】那边的进出库
        # 结果（这正是问题3那个"入库数量凭空消失"的bug的根因）。
        rec = {
            "code": self.code_edit.text().strip(),
            "name": self.name_edit.text().strip(),
            "category": self.category_combo.currentData(),
            "K": k_list,
            "S": s_list,
            "density": self.density_spin.value(),
            "dry_back_factor": self.dryback_spin.value(),
            # 允许色差：来料检验的判据
            "delta_e_tolerance": self.tolerance_spin.value(),
        }
        # 标准 Lab：只有真的用 Lab/色相环指定过颜色，才存这个基准值。
        # 没指定过就别硬塞一个默认值进去——那样来料检验会拿一个假基准去判合格，
        # 比"没有基准"更糟糕。
        if self._synthesized_K is not None:
            L, a, b = self._wheel_lab
            rec["ref_lab"] = [round(L, 2), round(a, 2), round(b, 2)]
            rec["ks_from_lab"] = True
        return rec


class BatchCheckDialog(QDialog):
    """
    来料检验：拿色差仪测出来的实测 Lab，跟档案里的标准 Lab 比，判合格/超差。

    这是"色差仪唯一真正够用"的场景——它只回答"这桶墨的颜色像不像标准色"，
    不涉及混色预测（那个需要 K/S 光谱，必须上分光光度计）。两回事，别混淆。
    """

    def __init__(self, parent, ink_record: dict):
        super().__init__(parent)
        self.setWindowTitle("来料检验 —— 色差判定")
        self.setMinimumWidth(480)
        self._record = ink_record
        ref = ink_record["ref_lab"]
        tol = ink_record.get("delta_e_tolerance") or 2.0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # 标准值
        std_box = QWidget()
        std_lay = QHBoxLayout(std_box)
        std_lay.setContentsMargins(12, 10, 12, 10)
        std_swatch = ColorSwatch(height=52)
        std_swatch.setFixedWidth(70)
        std_swatch.set_rgb(*lab_to_srgb_approx(*ref))
        std_lay.addWidget(std_swatch)
        std_text = QLabel(
            f"<b>{ink_record.get('name','')}</b>　[{ink_record.get('code','')}]<br>"
            f"标准 Lab：<b>L*{ref[0]:.2f}　a*{ref[1]:.2f}　b*{ref[2]:.2f}</b><br>"
            f"允许色差：<b>ΔE ≤ {tol}</b>"
        )
        std_lay.addWidget(std_text, 1)
        std_box.setStyleSheet("background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;")
        root.addWidget(std_box)

        # 实测值输入
        root.addWidget(QLabel("<b>用色差仪测这批来料，把读数填进来：</b>"))
        m_row = QHBoxLayout()
        m_row.addWidget(QLabel("L*"))
        self.m_l = QDoubleSpinBox(); self.m_l.setRange(0, 100); self.m_l.setDecimals(2)
        self.m_l.setValue(ref[0]); m_row.addWidget(self.m_l)
        m_row.addWidget(QLabel("a*"))
        self.m_a = QDoubleSpinBox(); self.m_a.setRange(-128, 127); self.m_a.setDecimals(2)
        self.m_a.setValue(ref[1]); m_row.addWidget(self.m_a)
        m_row.addWidget(QLabel("b*"))
        self.m_b = QDoubleSpinBox(); self.m_b.setRange(-128, 127); self.m_b.setDecimals(2)
        self.m_b.setValue(ref[2]); m_row.addWidget(self.m_b)
        root.addLayout(m_row)

        for sp in (self.m_l, self.m_a, self.m_b):
            sp.valueChanged.connect(self._recheck)

        tip = QLabel(
            "📏 测的时候：把这批墨<b>厚实、完全遮盖</b>地印一块（不能透底），"
            "<b>彻底干燥后</b>再测——湿墨的读数没有意义。"
            "多测几个点取平均，避免局部不均导致误判。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#0d9488; font-size:11px; background:#f0fdfa; "
                          "border-radius:6px; padding:7px 9px;")
        root.addWidget(tip)

        # 实测色块 + 判定结果
        cmp_row = QHBoxLayout()
        cmp_row.addWidget(QLabel("实测颜色："))
        self.m_swatch = ColorSwatch(height=52)
        self.m_swatch.setFixedWidth(70)
        cmp_row.addWidget(self.m_swatch)
        cmp_row.addStretch(1)
        root.addLayout(cmp_row)

        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setMinimumHeight(90)
        root.addWidget(self.verdict)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        root.addWidget(btns)

        self._recheck()

    def _recheck(self):
        from dal_layer.data_manager import check_ink_batch

        measured = (self.m_l.value(), self.m_a.value(), self.m_b.value())
        self.m_swatch.set_rgb(*lab_to_srgb_approx(*measured))
        result = check_ink_batch(self._record, measured)

        if result["ok"]:
            style = ("background:#f0fdf4; border:1px solid #86efac; color:#166534;")
        else:
            style = ("background:#fef2f2; border:1px solid #fecaca; color:#991b1b;")
        self.verdict.setStyleSheet(
            style + "border-radius:8px; padding:11px 13px; font-size:13px;"
        )
        self.verdict.setText(result["verdict"].replace("\n", "<br>"))


class InkLibraryPage(QWidget):

    ink_db_changed = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, ink_repo, get_engine: Callable[[], object],
                 get_allowed_ink_codes: Callable[[], object] = None,
                 is_main_account: Callable[[], bool] = None,
                 user_repo=None, ink_stock_repo=None,
                 parent=None):
        """
        Args:
            get_allowed_ink_codes: 返回当前账户能看到哪些油墨编号的集合；
                返回 None 表示"不受限"（主账户）。这是【问题1】的修复——
                以前这个页面根本没接权限回调，所以不管是谁登录，表格里
                都把油墨库整个倒出来了，跟【多色印刷工单】那边已经做了
                过滤的行为对不上，等于分配油墨的设置在这一页形同虚设。
            is_main_account: 是否主账户。子账户只有"查看自己被分配到的
                油墨"的权限，不能新增/编辑/删除/导入油墨档案——档案是
                全局共享的基础数据，让子账户改会影响到所有人。
        """
        super().__init__(parent)
        self.ink_repo = ink_repo
        self.get_engine = get_engine
        self.get_allowed_ink_codes = get_allowed_ink_codes
        self.is_main_account = is_main_account
        # 删除油墨时要做连带清理（清子账户的分配额度）和风险提示（还有多少
        # 库存、有多少条历史流水），所以这一页也需要能看到这两个仓储。
        self.user_repo = user_repo
        self.ink_stock_repo = ink_stock_repo
        self._build_ui()
        self._apply_account_restrictions()
        self.refresh_table()

    def _apply_account_restrictions(self):
        """子账户：整个页面降级为"只读查看我能用的油墨"，隐藏所有写操作入口。"""
        main = self.is_main_account() if self.is_main_account else True
        if main:
            return
        for btn in (self.add_btn, self.import_btn, self.std_btn, self.edit_btn, self.del_btn):
            btn.setVisible(False)
        self.readonly_banner.setVisible(True)

    # ================================================================
    # UI 搭建
    # ================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("油墨基因库管理")
        title.setObjectName("PageTitle")
        subtitle = QLabel("录入/维护每支油墨的光谱物理常数（K吸收系数、S散射系数）、密度与干燥修正系数")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        # ---- 数据总览统计卡片 ----
        self.stat_row = QHBoxLayout()
        self.stat_row.setSpacing(12)
        self.stat_total = StatCard("0", "在库油墨总数", accent_hex="#0d9488")
        self.stat_color = StatCard("0", _category_label("color"), accent_hex=_category_color("color"))
        self.stat_white = StatCard("0", _category_label("white"), accent_hex=_category_color("white"))
        self.stat_varnish = StatCard("0", _category_label("varnish"), accent_hex=_category_color("varnish"))
        for card in (self.stat_total, self.stat_color, self.stat_white, self.stat_varnish):
            self.stat_row.addWidget(card)
        self.stat_row.addStretch(1)
        root.addLayout(self.stat_row)

        card = Card()
        lay = card.body_layout
        lay.setSpacing(14)

        # ---- 搜索/筛选/操作 工具条 ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 按编号或名称搜索…")
        self.search_edit.setMinimumWidth(220)
        self.search_edit.textChanged.connect(self.refresh_table)
        toolbar.addWidget(self.search_edit)

        self.category_filter = QComboBox()
        self.category_filter.addItem("全部类别", "")
        for code, meta in CATEGORY_META.items():
            self.category_filter.addItem(meta["label"], code)
        self.category_filter.currentIndexChanged.connect(self.refresh_table)
        toolbar.addWidget(self.category_filter)

        toolbar.addStretch(1)
        self.add_btn = PrimaryButton("＋ 新增油墨档案")
        self.add_btn.clicked.connect(self._on_add)
        self.import_btn = GhostButton("📥 导入Excel数据")
        self.import_btn.setToolTip(
            "支持 L*/a*/b* 列 + 允许色差列。\n"
            "有 Lab 就用 Lab（仪器测的绝对色彩坐标），没有才回落到 RGB。\n"
            "编号可以不填，系统按颜色自动给（大红→R-01，青→C-01）。"
        )
        self.import_btn.clicked.connect(self._on_import_excel)

        self.std_btn = GhostButton("🎨 载入标准专色库")
        self.std_btn.setToolTip(
            "一键载入丝印常用的13支标准专色（CMYK四色 + 射光蓝/大红/橙/绿/紫罗兰/\n"
            "过程蓝/金红/耐晒黑 + 高遮盖白），带标准Lab值和允许色差。\n"
            "适合新装机建库起步，比对着空表格一支支敲快得多。"
        )
        self.std_btn.clicked.connect(self._on_load_standard)

        self.qc_btn = GhostButton("🔬 来料检验")
        self.qc_btn.setToolTip(
            "供应商送来一桶墨，用色差仪测出实测Lab填进来，\n"
            "系统跟标准Lab比，ΔE超过允许色差就是不合格，可以直接退货。"
        )
        self.qc_btn.clicked.connect(self._on_batch_check)
        self.edit_btn = GhostButton("✎ 编辑选中")
        self.edit_btn.clicked.connect(self._on_edit)
        self.del_btn = DangerButton("－ 删除选中")
        self.del_btn.setMinimumHeight(36)
        self.del_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.import_btn)
        toolbar.addWidget(self.std_btn)
        toolbar.addWidget(self.qc_btn)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.del_btn)
        lay.addLayout(toolbar)

        # ---- 演示数据警告横幅 ----
        #
        # 出厂自带的 24 支墨，K/S 值是【数学推算出来的】，不是任何一支真实
        # 油墨的实测数据。它们的存在只是为了让软件装上就能点开看看，绝对
        # 不能拿去指导实际生产——实测下来，这套假数据对饱和的橙色 ΔE 能到
        # 18，对柠檬黄能到 12（不是算法找不到，是这套数据物理上就调不出那个
        # 颜色）。如果新客户装上直接用，配出来的东西一定对不上，然后会得出
        # "这软件不行"的结论。
        #
        # 所以：横幅必须醒目、必须一直挂在那儿、必须给一个一键清空的按钮。
        self.demo_banner = QWidget()
        demo_lay = QHBoxLayout(self.demo_banner)
        demo_lay.setContentsMargins(12, 10, 12, 10)
        demo_text = QLabel(
            "⚠️ <b>当前油墨库里有演示数据</b>　这些墨的光谱(K/S)是数学推算的，<b>不是真实油墨的实测值</b>，"
            "拿它配出来的方案在现场对不上。<br>"
            "请<b>删掉它们，换成你自己真实在用的油墨</b>（可用【导入Excel】批量建档）。"
            "十几支真墨远胜二十几支假墨。"
        )
        demo_text.setWordWrap(True)
        demo_text.setStyleSheet("color:#7f1d1d; font-size:12px; background:transparent;")
        demo_lay.addWidget(demo_text, 1)
        self.purge_demo_btn = DangerButton("🗑 一键清空演示数据")
        self.purge_demo_btn.setMinimumHeight(34)
        self.purge_demo_btn.clicked.connect(self._on_purge_demo)
        demo_lay.addWidget(self.purge_demo_btn)
        self.demo_banner.setStyleSheet(
            "background:#fef2f2; border:1px solid #fecaca; border-radius:8px;"
        )
        self.demo_banner.setVisible(False)
        lay.addWidget(self.demo_banner)

        # 子账户看到的只读提示横幅（主账户下隐藏）
        self.readonly_banner = QLabel(
            "🔒 你的账户只能查看【已分配给你】的油墨。油墨档案（名称/光谱/密度）"
            "属于全局基础数据，由主账户统一维护；库存数量请到【油墨库存管理】查看。"
        )
        self.readonly_banner.setWordWrap(True)
        self.readonly_banner.setStyleSheet(
            "color:#0369a1; background:#f0f9ff; border:1px solid #bae6fd; "
            "border-radius:8px; padding:10px 12px; font-size:12px;"
        )
        self.readonly_banner.setVisible(False)
        lay.addWidget(self.readonly_banner)

        # ---- 表格 ----
        self.table = QTableWidget(0, 7)
        # 库存列同时给出 ml 和 g（问题2）：采购/库存按体积走，配墨称重按重量走，
        # 两个单位都摆在同一格里，师傅不用自己拿计算器乘密度。
        self.table.setHorizontalHeaderLabels(
            ["颜色", "编号", "名称", "类别", "密度(g/ml)", "干燥系数", "库存 (ml / 折合g)"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 90)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 130)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(6, 210)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { font-size: 13px; } "
            "QTableWidget::item:alternate { background-color: #fafbfc; }"
        )
        lay.addWidget(self.table, 1)

        root.addWidget(card, 1)

    def _filtered_records(self) -> List[Dict]:
        records = self.ink_repo.load_all()

        # ★【问题1修复】权限过滤：子账户只能看到分配给它的那些油墨。
        # get_allowed_ink_codes() 返回 None 代表主账户，不设限；返回一个
        # 集合就只放行集合里的编号。这跟【多色印刷工单】页用的是同一个
        # 回调、同一套判断，所以两个页面的行为从此保持一致。
        allowed = self.get_allowed_ink_codes() if self.get_allowed_ink_codes else None
        if allowed is not None:
            records = [r for r in records if r["code"] in allowed]

        keyword = self.search_edit.text().strip().lower()
        category = self.category_filter.currentData()
        result = []
        for r in records:
            if keyword and keyword not in r["code"].lower() and keyword not in r["name"].lower():
                continue
            if category and r.get("category") != category:
                continue
            result.append(r)
        return result

    def refresh_table(self):
        records = self._filtered_records()

        # 库里只要还有一支演示墨，红色警告横幅就一直挂着（且只有主账户能清）
        has_demo = any(r.get("is_demo_data") for r in self.ink_repo.load_all())
        is_main = self.is_main_account() if self.is_main_account else True
        self.demo_banner.setVisible(has_demo and is_main)
        engine = self.get_engine()
        self.table.setRowCount(len(records))
        for row, r in enumerate(records):
            try:
                lab = engine.compute_lab({r["code"]: 1.0}, apply_dry_back=False)
                rgb = lab_to_srgb_approx(*lab)
            except Exception:
                rgb = (200, 200, 200)

            self.table.setCellWidget(row, 0, self._make_swatch_cell(rgb))

            code_item = QTableWidgetItem(r["code"])
            code_item.setData(Qt.ItemDataRole.UserRole, r["code"])
            code_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r.get("is_demo_data"):
                name_item = QTableWidgetItem("⚠️ " + r["name"] + "（演示数据）")
                name_item.setForeground(QColor("#b91c1c"))
                name_item.setToolTip(
                    "这是出厂演示油墨，光谱(K/S)是数学推算的，不是实测值。\n"
                    "拿它配出来的配方在现场对不上，请换成你自己真实在用的油墨。"
                )
            else:
                name_item = QTableWidgetItem(r["name"])
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            density_item = QTableWidgetItem(f"{r.get('density', 1.0):.2f}")
            density_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dryback_item = QTableWidgetItem(f"{r.get('dry_back_factor', 0.0):.2f}")
            dryback_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table.setItem(row, 1, code_item)
            self.table.setItem(row, 2, name_item)
            self.table.setCellWidget(row, 3, self._make_category_cell(r.get("category", "color")))
            self.table.setItem(row, 4, density_item)
            self.table.setItem(row, 5, dryback_item)

            stock = r.get("stock_ml", 0.0) or 0.0
            status = self.ink_repo.stock_status(r)
            grams = self.ink_repo.ml_to_grams(r, stock)   # 克重 = 毫升 × 密度
            stock_item = QTableWidgetItem(f"{stock:g} ml  ≈ {grams:.0f} g   {status}")
            stock_item.setToolTip(
                f"库存 {stock:g} ml，按密度 {r.get('density', 1.0):.2f} g/ml 折合约 {grams:.0f} g。\n"
                f"库存按体积记账（采购是按桶/升买的），配墨按重量称量（天平称的是克），\n"
                f"两者靠这支墨的密度换算。要调整库存请到【油墨库存管理】页。"
            )
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "缺货":
                stock_item.setBackground(QColor("#fee2e2"))
                stock_item.setForeground(QColor("#b91c1c"))
            elif status == "库存不足":
                stock_item.setBackground(QColor("#fef9c3"))
                stock_item.setForeground(QColor("#b45309"))
            self.table.setItem(row, 6, stock_item)

    def _make_swatch_cell(self, rgb) -> QWidget:
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(10, 8, 10, 8)
        chip = QFrame()
        chip.setFixedSize(48, 32)
        chip.setStyleSheet(
            f"background-color: rgb({rgb[0]},{rgb[1]},{rgb[2]}); "
            f"border-radius: 8px; border: 1px solid #d1d5db;"
        )
        lay.addWidget(chip)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return container

    def _on_purge_demo(self):
        """
        一键清空所有标记为演示数据的油墨。

        为什么要有这个按钮：出厂那 24 支墨的 K/S 是数学推算的假数据。一支一支
        删太折磨人，而且用户很可能根本意识不到"这些不是真的"就直接拿去配色了。
        给一个显眼的一键清空，是为了把"换成自己的真墨"这件事的门槛降到最低。

        只删还带 is_demo_data 标记的；用户自己建的、或者 Excel 导进来的墨
        不会被碰（那些墨在 upsert_meta / upsert 时不会带这个标记）。
        """
        demo = [r for r in self.ink_repo.load_all() if r.get("is_demo_data")]
        if not demo:
            QMessageBox.information(self, "提示", "当前油墨库里已经没有演示数据了。")
            return

        with_stock = [r for r in demo if (r.get("stock_ml") or 0) > 0]
        msg = (
            f"将删除 {len(demo)} 支出厂演示油墨。\n\n"
            f"这些墨的光谱数据是数学推算的，不是真实油墨的实测值，"
            f"拿它们配出来的配方在现场对不上——删掉是对的。\n\n"
            f"删除后请用【＋新增油墨档案】或【📥导入Excel】把你自己真正在用的墨录进来。"
        )
        if with_stock:
            msg += (
                f"\n\n⚠️ 注意：其中 {len(with_stock)} 支已经被你记过库存了"
                f"（说明你可能已经把它当真墨在用）。请先确认这些是不是你要保留的。"
            )
        box = QMessageBox(self)
        box.setWindowTitle("清空演示数据")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        for r in demo:
            self.ink_repo.delete(r["code"])
            if self.user_repo:
                self.user_repo.purge_ink_allocations(r["code"])

        self.refresh_table()
        self.ink_db_changed.emit()
        self.status_message.emit(
            f"已清空 {len(demo)} 支演示油墨。现在请录入你自己真实在用的油墨。"
        )

    def _on_load_standard(self):
        """一键载入 13 支标准专色（12 支常用专色 + 高遮盖白）。"""
        from dal_layer.data_manager import build_standard_ink_records

        records = build_standard_ink_records()
        existing = {r["code"] for r in self.ink_repo.load_all()}
        dupes = [r["code"] for r in records if r["code"] in existing]

        msg = (
            f"将载入 {len(records)} 支标准专色：\n\n"
            f"　CMYK 四色（青/洋红/黄/黑）\n"
            f"　射光蓝、大红、橙色、绿色、紫罗兰、过程蓝、金红、耐晒黑\n"
            f"　高遮盖白\n\n"
            f"每支都带【标准 Lab 值】和【允许色差 ΔE】，可以直接用来做来料检验。\n\n"
            f"⚠️ 必须说清楚一件事：\n"
            f"这些墨的 K/S 光谱是从 Lab 反推的，不是分光光度计实测的。\n"
            f"　✅ 每支墨的【单色显示】是准的\n"
            f"　⚠️ 但【混色配方】的 ΔE 预测仍然是近似的，不能当验收依据\n\n"
            f"这是个好的【起点】，不是【终点】。要让混色也准，只有一条路：\n"
            f"用分光光度计实测每支墨的反射光谱。"
        )
        if dupes:
            msg += f"\n\n⚠️ 其中 {len(dupes)} 支编号已存在，会被覆盖：{', '.join(dupes[:5])}"
            msg += "…" if len(dupes) > 5 else ""

        box = QMessageBox(self)
        box.setWindowTitle("载入标准专色库")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        for r in records:
            self.ink_repo.upsert(r)
        self.refresh_table()
        self.ink_db_changed.emit()
        self.status_message.emit(
            f"已载入 {len(records)} 支标准专色。库存都是 0，请到【油墨库存管理】做入库。"
        )

    def _on_batch_check(self):
        """
        来料检验：供应商送来的这桶墨，颜色对不对？

        这是你作为油墨供应商能立刻用上的功能——测一下实测 Lab，跟标准 Lab 比，
        超差就退货。

        注意这个功能【只需要色差仪，不需要分光光度计】：它只比"颜色像不像"，
        不涉及混色预测。这是色差仪唯一真正够用的场景——别跟"配色精度"混淆，
        那个还是绕不开分光光度计。
        """
        from dal_layer.data_manager import check_ink_batch

        code = self._selected_code()
        if not code:
            QMessageBox.information(self, "提示", "请先在表格里选中要检验的那支油墨。")
            return
        record = self.ink_repo.get_by_code(code)
        if record is None:
            return

        if not record.get("ref_lab"):
            QMessageBox.information(
                self, "这支墨没有标准Lab值",
                f"【{record.get('name','')}】还没有录【标准 Lab 值】，没法判断来料合不合格。\n\n"
                f"标准 Lab 是这支墨【应该】是什么颜色——它是检验的基准。\n\n"
                f"补录方法：\n"
                f"  · 点【✏️ 编辑】，在 Lab 输入框里填上这支墨的标准值，或者\n"
                f"  · 用【📥 导入Excel】，表格里带 L*/a*/b* 列，或者\n"
                f"  · 点【🎨 载入标准专色库】，用行业标准值"
            )
            return

        dlg = BatchCheckDialog(self, record)
        dlg.exec()

    def _make_category_cell(self, category: str) -> QWidget:
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        badge = Badge(_category_label(category), bg_hex=_category_color(category))
        lay.addWidget(badge)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return container

    def _selected_code(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)

    # ================================================================
    # 增删改
    # ================================================================

    def _on_import_excel(self):
        from ui_layer.ink_import_dialog import InkImportDialog
        dlg = InkImportDialog(self, ink_repo=self.ink_repo)
        if dlg.exec():
            records = dlg.get_selected_records()
            imported = 0
            for r in records:
                # 已存在的油墨：只覆盖档案信息，库存保持磁盘上的现值不动；
                # 新油墨：库存从 Excel 里带过来的初始值起算（首次建库方便）。
                if self.ink_repo.get_by_code(r["code"]):
                    self.ink_repo.upsert_meta({
                        "code": r["code"], "name": r["name"], "category": r["category"],
                        "K": r["K"], "S": r["S"], "density": r["density"],
                        "dry_back_factor": r["dry_back_factor"],
                    })
                else:
                    self.ink_repo.upsert({
                        "code": r["code"], "name": r["name"], "category": r["category"],
                        "K": r["K"], "S": r["S"], "density": r["density"],
                        "dry_back_factor": r["dry_back_factor"], "stock_ml": r["stock_ml"],
                        "low_stock_threshold_ml": r["low_stock_threshold_ml"],
                    })
                imported += 1
            self.refresh_table()
            self.ink_db_changed.emit()
            QMessageBox.information(self, "导入完成", f"已成功导入 {imported} 支油墨。")

    def _on_add(self):
        dialog = AddInkDialog(self, ink_repo=self.ink_repo)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            record = dialog.get_record()
            if not record["code"] or not record["name"]:
                QMessageBox.warning(self, "提示", "油墨编号与名称不能为空。")
                return
            if self.ink_repo.get_by_code(record["code"]):
                QMessageBox.warning(self, "提示", f"编号 [{record['code']}] 已存在，请更换编号或使用编辑功能。")
                return
            # 新建的油墨库存从 0 起步，必须去【油墨库存管理】走一笔采购入库
            self.ink_repo.upsert_meta(record)
            self.refresh_table()
            self.ink_db_changed.emit()
            QMessageBox.information(
                self, "已建档",
                f"油墨档案 [{record['code']}] {record['name']} 已创建，当前库存为 0。\n\n"
                f"请到【油墨库存管理】页做一笔【采购入库】，把实际到货数量记进去，"
                f"库存数字才会出现。"
            )

    def _on_edit(self):
        code = self._selected_code()
        if not code:
            QMessageBox.information(self, "提示", "请先在表格中点击选中要编辑的油墨。")
            return
        existing = self.ink_repo.get_by_code(code)
        dialog = AddInkDialog(self, existing=existing, ink_repo=self.ink_repo)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            record = dialog.get_record()
            # ★【问题3修复】用 upsert_meta 而不是 upsert：只写档案信息，
            # 库存字段从磁盘上的最新记录继承，绝不会把【油墨库存管理】
            # 那边刚记的入库/出库结果覆盖掉。
            self.ink_repo.upsert_meta(record)
            self.refresh_table()
            self.ink_db_changed.emit()

    def _on_delete(self):
        code = self._selected_code()
        if not code:
            QMessageBox.information(self, "提示", "请先在表格中点击选中要删除的油墨。")
            return

        record = self.ink_repo.get_by_code(code)
        if record is None:
            return
        name = record.get("name", "")
        stock_ml = record.get("stock_ml", 0.0) or 0.0

        # 删一支墨不只是从列表里划掉一行，它会牵连到三个地方。把后果一次讲清楚，
        # 而不是等用户点完"是"之后才发现账对不上、子账户的额度莫名其妙消失了。
        ledger_count = self.ink_stock_repo.count_for_ink(code) if self.ink_stock_repo else 0
        holders = []
        if self.user_repo:
            for u in self.user_repo.load_all():
                allocs = u.get("ink_allocations") or {}
                if code in allocs:
                    holders.append(u.get("display_name") or u.get("username"))

        msg = f"确定要删除油墨档案 [{code}] {name} 吗？\n"
        consequences = []
        if stock_ml > 0:
            grams = self.ink_repo.ml_to_grams(record, stock_ml)
            consequences.append(
                f"⚠️ 这支墨账面上还有 {stock_ml:g} ml（约 {grams:.0f} g）库存。\n"
                f"   如果仓库里实际还有货，删掉档案等于这批墨从此不在账上，"
                f"以后盘点会对不上。建议先在【油墨库存管理】做出库/报废处理。"
            )
        if ledger_count > 0:
            consequences.append(
                f"📋 这支墨有 {ledger_count} 条进出库流水。\n"
                f"   流水属于历史账目，删除油墨档案后【会保留】，不会被抹掉——"
                f"账目不能凭空消失。但那些记录里的油墨编号会指向一支已经不存在的墨。"
            )
        if holders:
            consequences.append(
                f"👤 这支墨已分配给 {len(holders)} 个子账户（{', '.join(holders[:3])}"
                f"{'…' if len(holders) > 3 else ''}）。\n"
                f"   删除后，这些账户的对应分配额度和用量记录会一并清除。"
            )
        if consequences:
            msg += "\n" + "\n\n".join(consequences)
        msg += "\n\n此操作不可撤销。"

        box = QMessageBox(self)
        box.setWindowTitle("确认删除油墨")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        self.ink_repo.delete(code)

        # 连带清理：把所有账户里对这支墨的分配额度/用量记录一起清掉，
        # 否则 users.json 里会留下指向已删除油墨的悬空引用。
        purged = 0
        if self.user_repo:
            purged = self.user_repo.purge_ink_allocations(code)

        self.refresh_table()
        self.ink_db_changed.emit()

        tail = f"，并清理了 {purged} 个子账户的分配记录" if purged else ""
        note = f"\n（{ledger_count} 条历史进出库流水已保留在账上）" if ledger_count else ""
        self.status_message.emit(f"已删除油墨 [{code}] {name}{tail}{note}")
