# -*- coding: utf-8 -*-
"""
color_swatch_library.py  (UI层 - 色卡选择器)
=================================================
解决"工人不识数字，只想直接点最像的颜色"的需求。

说明（重要，避免误解）：
    这里生成的是一套【系统化色板】——按色相(Hue)/明度(Lightness)/
    饱和度(Saturation)均匀铺开几百个色块，覆盖常见色系，供"挑最接近
    的色块"这种直觉式操作使用。
    这**不是**、也不能宣称是 Pantone / RAL 等商用色卡系统的复刻
    ——那些是有版权的商业标准色号数据，本软件没有取得授权，不能
    也不会去仿制那些具体色号和数值。如果贵厂已经在使用某套商用色卡
    并且需要软件里的色号跟色卡完全对应，需要贵厂自行采购官方色卡的
    数字色值数据（通常官方会提供Lab/CMYK对照表），我们可以把那份
    数据导入到"油墨库管理"或本色板中，但不能凭空编造官方数值。
"""

from typing import List, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea,
    QWidget, QPushButton, QTabWidget, QSizePolicy
)

from core_layer.color_convert import srgb_to_lab, lab_to_srgb_approx, hsl_to_rgb
from ui_layer.widgets import PrimaryButton, GhostButton, ColorSwatch
from ui_layer.color_wheel import ColorWheelPanel


def _hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    """兼容旧调用，实际转发到 core_layer.color_convert.hsl_to_rgb。"""
    return hsl_to_rgb(h, s, l)


def build_chromatic_palette() -> List[Tuple[str, int, int, int]]:
    """彩色系：24色相 x 3饱和度 x 5明度 = 360个色块。"""
    swatches = []
    for h in range(0, 360, 15):
        for s in (85, 60, 35):
            for l in (75, 60, 45, 30, 18):
                r, g, b = _hsl_to_rgb(h, s, l)
                code = f"H{h:03d}-S{s}-L{l}"
                swatches.append((code, r, g, b))
    return swatches


def build_neutral_palette() -> List[Tuple[str, int, int, int]]:
    """中性灰阶：黑->白，供瓶身底色（玻璃/塑料/纸质本色）常用。"""
    swatches = []
    for l in range(4, 100, 4):
        r, g, b = _hsl_to_rgb(0, 0, l)
        code = f"灰阶-L{l}"
        swatches.append((code, r, g, b))
    return swatches


def build_earth_tone_palette() -> List[Tuple[str, int, int, int]]:
    """常见承印物底色系（牛皮纸棕、琥珀棕、米白等），瓶身/包装场景高频使用。"""
    hues = [20, 25, 30, 35, 40, 45]
    swatches = []
    for h in hues:
        for s in (45, 65):
            for l in (30, 45, 60, 75, 88):
                r, g, b = _hsl_to_rgb(h, s, l)
                code = f"棕调-H{h}-S{s}-L{l}"
                swatches.append((code, r, g, b))
    return swatches


class _SwatchButton(ColorSwatch):
    """网格里的单个可点选色块。"""

    def __init__(self, code: str, r: int, g: int, b: int, parent=None):
        super().__init__(parent, height=30)
        self.code = code
        self.rgb = (r, g, b)
        self.set_rgb(r, g, b)
        self.setFixedSize(30, 30)
        self.setToolTip(f"{code}\nRGB({r},{g},{b})")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class ColorSwatchPickerDialog(QDialog):
    """
    色卡网格选择对话框。

    用法：
        dlg = ColorSwatchPickerDialog(self)
        if dlg.exec():
            lab = dlg.get_result_lab()
    """

    def __init__(self, parent=None, title: str = "从色卡选择相近颜色"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 560)
        self._selected_rgb: Tuple[int, int, int] = (255, 255, 255)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        hint = QLabel(
            "💡 这是系统生成的通用色板（按色相/明度/饱和度均匀铺开），用于\"挑最接近的颜色\"这种直觉操作，"
            "不是某个商用色卡品牌的官方复刻。点击色块即可选用，右下角可预览、确认。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(hint)

        tabs = QTabWidget()
        tabs.addTab(self._build_grid_tab(build_neutral_palette()), "灰阶 / 玻璃塑料本色")
        tabs.addTab(self._build_grid_tab(build_earth_tone_palette()), "牛皮纸 / 琥珀棕调")
        tabs.addTab(self._build_wheel_tab(), "全色相（色相环点选）")
        root.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("已选颜色："))
        self.preview_swatch = ColorSwatch(height=40)
        self.preview_swatch.setFixedWidth(80)
        bottom.addWidget(self.preview_swatch)
        self.preview_label = QLabel("尚未选择")
        bottom.addWidget(self.preview_label, 1)

        cancel_btn = GhostButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = PrimaryButton("✅ 确定使用")
        ok_btn.clicked.connect(self.accept)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(ok_btn)
        root.addLayout(bottom)

    def _build_wheel_tab(self) -> QWidget:
        container = QWidget()
        lay = QVBoxLayout(container)
        hint = QLabel("💡 点击或按住拖动圆盘选择色相与饱和度，下方滑杆调整明度深浅。")
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.wheel_panel = ColorWheelPanel(diameter=260)
        self.wheel_panel.color_picked.connect(
            lambda r, g, b: self._on_swatch_clicked((r, g, b), "色相环选取")
        )
        lay.addWidget(self.wheel_panel)
        lay.addStretch(1)
        return container

    def _build_grid_tab(self, palette: List[Tuple[str, int, int, int]]) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(3)
        columns = 18
        for i, (code, r, g, b) in enumerate(palette):
            btn = _SwatchButton(code, r, g, b)
            btn.clicked.connect(lambda rgb=(r, g, b), c=code: self._on_swatch_clicked(rgb, c))
            grid.addWidget(btn, i // columns, i % columns)

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        return scroll

    def _on_swatch_clicked(self, rgb: Tuple[int, int, int], code: str):
        self._selected_rgb = rgb
        self.preview_swatch.set_rgb(*rgb)
        L, a, b = srgb_to_lab(*rgb)
        self.preview_label.setText(f"{code}  |  Lab=({L:.1f}, {a:.1f}, {b:.1f})")

    def get_result_lab(self) -> Tuple[float, float, float]:
        return srgb_to_lab(*self._selected_rgb)
