# -*- coding: utf-8 -*-
"""
color_wheel.py  (UI层 - 色相环控件)
======================================
真正意义上的"色相环"：一个圆盘，角度代表色相(Hue)，到圆心的距离
代表饱和度(Saturation)，鼠标点选/拖动即可选色；圆盘下方一条明度
(Lightness)滑杆控制颜色的深浅。比"网格铺色块"更直观，符合大家
对"色环选色"的直觉认知。
"""

import math

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider

from core_layer.color_convert import hsl_to_rgb


class ColorWheelWidget(QWidget):
    """圆形色相/饱和度选择盘，点击或拖动鼠标选色。"""

    color_picked = pyqtSignal(int, int, int)  # r, g, b

    def __init__(self, parent=None, diameter: int = 240):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._lightness = 50.0   # 0-100，由外部滑杆控制
        self._hue = 0.0          # 当前选中角度 0-360
        self._sat = 0.0          # 当前选中饱和度 0-100
        self._wheel_pixmap: QPixmap = None
        self._rebuild_wheel()

    # ---------------------------------------------------------- 外部接口 ----

    def set_lightness(self, lightness: int):
        self._lightness = float(lightness)
        self._rebuild_wheel()
        self.update()
        self._emit_current_color()

    def current_rgb(self):
        return hsl_to_rgb(self._hue, self._sat, self._lightness)

    def set_selection(self, h: float, s: float):
        self._hue, self._sat = h, s
        self.update()

    # ---------------------------------------------------------- 圆盘绘制 ----

    def _rebuild_wheel(self):
        d = self._diameter
        img = QImage(d, d, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        cx, cy = d / 2.0, d / 2.0
        radius = d / 2.0 - 2.0

        for y in range(d):
            dy = y - cy
            for x in range(d):
                dx = x - cx
                dist = math.hypot(dx, dy)
                if dist <= radius:
                    angle = math.degrees(math.atan2(dy, dx))
                    hue = (angle + 360.0) % 360.0
                    sat = min(100.0, dist / radius * 100.0)
                    r, g, b = hsl_to_rgb(hue, sat, self._lightness)
                    img.setPixelColor(x, y, QColor(r, g, b))
        self._wheel_pixmap = QPixmap.fromImage(img)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._wheel_pixmap)

        # 绘制当前选中点的标记（双色圆环，保证在深浅背景上都看得清）
        cx, cy = self._diameter / 2.0, self._diameter / 2.0
        radius = self._diameter / 2.0 - 2.0
        rad = math.radians(self._hue)
        r_px = self._sat / 100.0 * radius
        mx = cx + r_px * math.cos(rad)
        my = cy + r_px * math.sin(rad)

        pen_outer = QPen(QColor("#ffffff")); pen_outer.setWidth(3)
        painter.setPen(pen_outer)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(int(mx), int(my)), 7, 7)
        pen_inner = QPen(QColor("#111827")); pen_inner.setWidth(1)
        painter.setPen(pen_inner)
        painter.drawEllipse(QPoint(int(mx), int(my)), 7, 7)

    # ---------------------------------------------------------- 鼠标交互 ----

    def mousePressEvent(self, event):
        self._pick_at(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick_at(event.position())

    def _pick_at(self, pos):
        cx, cy = self._diameter / 2.0, self._diameter / 2.0
        radius = self._diameter / 2.0 - 2.0
        dx, dy = pos.x() - cx, pos.y() - cy
        dist = min(math.hypot(dx, dy), radius)
        angle = math.degrees(math.atan2(dy, dx))

        self._hue = (angle + 360.0) % 360.0
        self._sat = dist / radius * 100.0 if radius > 0 else 0.0
        self.update()
        self._emit_current_color()

    def _emit_current_color(self):
        r, g, b = self.current_rgb()
        self.color_picked.emit(r, g, b)


class ColorWheelPanel(QWidget):
    """色相环 + 明度滑杆 的组合面板，直接嵌入对话框使用。"""

    color_picked = pyqtSignal(int, int, int)

    def __init__(self, parent=None, diameter: int = 240):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.wheel = ColorWheelWidget(diameter=diameter)
        self.wheel.color_picked.connect(self.color_picked.emit)

        wheel_row = QHBoxLayout()
        wheel_row.addStretch(1)
        wheel_row.addWidget(self.wheel)
        wheel_row.addStretch(1)
        root.addLayout(wheel_row)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("明度："))
        self.lightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.lightness_slider.setRange(5, 95)
        self.lightness_slider.setValue(50)
        self.lightness_slider.valueChanged.connect(self._on_lightness_changed)
        slider_row.addWidget(self.lightness_slider, 1)
        self.lightness_label = QLabel("50%")
        self.lightness_label.setFixedWidth(36)
        slider_row.addWidget(self.lightness_label)
        root.addLayout(slider_row)

    def _on_lightness_changed(self, value: int):
        self.lightness_label.setText(f"{value}%")
        self.wheel.set_lightness(value)

    def current_rgb(self):
        return self.wheel.current_rgb()
