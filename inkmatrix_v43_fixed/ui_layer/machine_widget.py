# -*- coding: utf-8 -*-
"""
machine_widget.py  (UI层 - 机台动态状态组件)
=================================================
参考用户上传的圆筒式丝印机造型（黄色圆柱机身+格栅窗口+顶部电机），
做一个会真正"动"的机台状态图标：
    - 状态="生产中" 时，机身持续旋转（用QTimer驱动角度+repaint实现，
      是原生动画，不是GIF图片）
    - 其他状态（调机中/已完成/异常暂停）机身静止，用颜色区分状态
    - 顶部小电机在"生产中"状态会有轻微脉动效果，呼应实际设备运转的观感
"""

import math

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient
from PyQt6.QtWidgets import QWidget

_STATUS_COLORS = {
    "调机中": ("#f59e0b", "#fde68a"),      # 橙色系
    "生产中": ("#0d9488", "#5eead4"),      # 青绿色系(呼应参考图的运转状态)
    "已完成": ("#16a34a", "#bbf7d0"),      # 绿色系
    "异常暂停": ("#dc2626", "#fecaca"),    # 红色系
}


class MachineAnimationWidget(QWidget):
    """圆柱形机台图标，"生产中"状态下持续旋转动画，其余状态静止。"""

    def __init__(self, status: str = "已完成", parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._status = status
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._apply_status(status)

    def set_status(self, status: str):
        self._apply_status(status)
        self.update()

    def _apply_status(self, status: str):
        self._status = status
        if status == "生产中":
            if not self._timer.isActive():
                self._timer.start(40)  # 约25fps，够流畅又不太占资源
        else:
            self._timer.stop()

    def _on_tick(self):
        self._angle = (self._angle + 4.0) % 360.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        primary, light = _STATUS_COLORS.get(self._status, ("#94a3b8", "#e2e8f0"))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h * 0.58
        radius = min(w, h) * 0.36

        # ---- 机身主体（圆柱形，径向渐变模拟金属质感） ----
        gradient = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
        gradient.setColorAt(0.0, QColor(light))
        gradient.setColorAt(1.0, QColor(primary))
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(QColor(primary), 2))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # ---- 旋转的格栅窗口（呼应参考图机身上的方格窗），角度随_angle转动 ----
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(QBrush(QColor(255, 255, 255, 160)))
        for i in range(3):
            a = i * 120
            rad = math.radians(a)
            x = radius * 0.5 * math.cos(rad)
            y = radius * 0.5 * math.sin(rad)
            painter.drawRoundedRect(QRectF(x - 8, y - 6, 16, 12), 2, 2)
        painter.restore()

        # ---- 顶部小电机（生产中时轻微放大做脉动效果） ----
        motor_r = 6 + (2 if self._status == "生产中" and int(self._angle) % 60 < 30 else 0)
        painter.setBrush(QBrush(QColor(primary)))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawEllipse(QRectF(cx - motor_r / 2, cy - radius - motor_r, motor_r, motor_r))

        # ---- 底部支脚 ----
        painter.setPen(QPen(QColor("#94a3b8"), 2))
        for dx in (-radius * 0.7, radius * 0.7):
            painter.drawLine(int(cx + dx), int(cy + radius - 2), int(cx + dx), int(cy + radius + 8))

        painter.end()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
