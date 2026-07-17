# -*- coding: utf-8 -*-
"""
widgets.py  (UI层 - 通用样式化控件)
=====================================
把常用的"卡片容器 / 主按钮 / 危险按钮 / 侧边导航按钮"等封装成独立的
Widget子类，theme.py 中的 QSS 直接按类名选择器（如 `PrimaryButton {...}`）
统一控制外观，页面代码只管拼业务逻辑，不用每处手写 setStyleSheet，
符合高内聚低耦合、样式与逻辑分离的原则。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QPushButton, QLabel, QVBoxLayout, QGraphicsDropShadowEffect, QWidget, QBoxLayout
)


class ResponsiveRow(QWidget):
    """
    自适应"行"容器：窗口/父容器够宽时，内部几块面板并排显示（跟原来
    QHBoxLayout一样）；宽度不够时自动改成上下堆叠，全部内容都能看到，
    不再依赖"藏在底部、不容易被发现"的横向滚动条。

    用QBoxLayout.setDirection()在"横排"和"竖排"之间切换，不用销毁重建
    整个布局（那样容易引发控件重叠的问题，之前踩过坑）。

    用法：
        row = ResponsiveRow(breakpoint=900)
        row.add_panel(card1, stretch=1)
        row.add_panel(card2, stretch=1)
        parent_layout.addWidget(row)
    """

    def __init__(self, breakpoint: int = 900, spacing: int = 16, parent=None):
        super().__init__(parent)
        self._breakpoint = breakpoint
        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(spacing)
        self._is_horizontal = True

    def add_panel(self, widget: QWidget, stretch: int = 1):
        self._layout.addWidget(widget, stretch)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        should_be_horizontal = self.width() >= self._breakpoint
        if should_be_horizontal != self._is_horizontal:
            self._is_horizontal = should_be_horizontal
            self._layout.setDirection(
                QBoxLayout.Direction.LeftToRight if should_be_horizontal else QBoxLayout.Direction.TopToBottom
            )


class Card(QFrame):
    """
    带轻微投影、圆角、白底的卡片容器，替代原来直接用 QGroupBox 的简陋外观。

    用法：
        card = Card("① 目标色输入")
        card.body_layout.addWidget(...)   # 往卡片内容区加控件
    """

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("class", "Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            outer.addWidget(self.title_label)
        else:
            self.title_label = None

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(8)
        outer.addLayout(self.body_layout)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(15, 23, 42, 40))
        self.setGraphicsEffect(shadow)


class PrimaryButton(QPushButton):
    """主操作按钮（强调色，如"智能寻优配方"、"保存"）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("PrimaryButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)


class SuccessButton(QPushButton):
    """执行类按钮（如"开始执行配墨"）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("SuccessButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(42)


class DangerButton(QPushButton):
    """危险/急停类按钮。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("DangerButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(52)


class GhostButton(QPushButton):
    """次要操作按钮（边框描边风格，如"取消"、"清除"）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("GhostButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)


class SidebarButton(QPushButton):
    """左侧导航按钮：可选中态（当前页高亮）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


class Badge(QLabel):
    """彩色圆角标签（如类别标记：彩色油墨/高遮盖白/冲淡剂），颜色按调用方指定。"""

    def __init__(self, text: str = "", bg_hex: str = "#0d9488", fg_hex: str = "#ffffff", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_colors(bg_hex, fg_hex)

    def set_colors(self, bg_hex: str, fg_hex: str = "#ffffff"):
        self.setStyleSheet(
            f"background-color:{bg_hex}; color:{fg_hex}; border-radius:10px; "
            f"padding:3px 12px; font-size:12px; font-weight:600;"
        )


class StatCard(QFrame):
    """概览统计小卡片：大号数字 + 说明文字，用于页面顶部的数据总览行。"""

    def __init__(self, value: str = "0", caption: str = "", accent_hex: str = "#0d9488", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(
            f"#StatCard {{ background-color:#ffffff; border:1px solid #e2e8f0; border-radius:12px; "
            f"border-left: 4px solid {accent_hex}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"font-size:22px; font-weight:800; color:{accent_hex};")
        self.caption_label = QLabel(caption)
        self.caption_label.setStyleSheet("font-size:11px; color:#64748b;")
        lay.addWidget(self.value_label)
        lay.addWidget(self.caption_label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class ColorSwatch(QFrame):
    """一个纯色色块预览控件，统一管理边框/圆角样式。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None, height: int = 56):
        super().__init__(parent)
        self.setObjectName("ColorSwatch")
        self.setMinimumHeight(height)
        self.set_rgb(255, 255, 255)

    def set_rgb(self, r: int, g: int, b: int):
        self.setStyleSheet(
            f"#ColorSwatch {{ background-color: rgb({r},{g},{b}); "
            f"border: 1px solid #cbd5e1; border-radius: 8px; }}"
        )

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class StatusBadge(QLabel):
    """状态徽标：正常(绿) / 警告(红)，用于替代原来朴素的红字文本。"""

    def __init__(self, text: str = "系统就绪", parent=None):
        super().__init__(text, parent)
        self.setObjectName("StatusBadgeNormal")
        self.setMinimumHeight(30)

    def set_normal(self, text: str):
        self.setObjectName("StatusBadgeNormal")
        self.setText("●  " + text)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_danger(self, text: str):
        self.setObjectName("StatusBadgeDanger")
        self.setText("⚠  " + text)
        self.style().unpolish(self)
        self.style().polish(self)
