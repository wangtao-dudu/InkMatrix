# -*- coding: utf-8 -*-
"""
color_pickers.py  (UI层 - 图片取色组件)
==========================================
解决"客户只给效果图/照片，没有分光测色数据"的现场痛点：
    - 效果图取色：在客户提供的成品渲染图上点选目标区域，直接得到目标Lab，
      不用再靠人工估读Lab数值。
    - 瓶身识别：在瓶身实拍照片上点选瓶身本体颜色，得到承印物底色Lab，
      自动写入承印物底色库，替代人工估测/查表。

设计要点：
    - 支持连续点选多个采样点并显示各点颜色，取"多点平均"而不是单点，
      因为渲染图/实拍照片存在高光、阴影、渐变，单点容易采到不代表
      真实颜色的极值点；工人可以刻意避开高光/阴影，多点找平均更稳。
    - 每个采样点用 7x7 像素邻域中值，抑制传感器/压缩噪声。
    - 本组件只做"图像像素 -> sRGB -> Lab"，不做任何硬件通信，
      与 HAL 层完全独立，符合分层解耦原则。
"""

from typing import List, Tuple, Optional, Dict

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QScrollArea, QListWidget, QListWidgetItem, QMessageBox, QSlider, QWidget,
    QComboBox, QInputDialog
)

from core_layer.color_convert import srgb_to_lab, lab_to_srgb_approx
from ui_layer.widgets import PrimaryButton, GhostButton, ColorSwatch


def _median_neighborhood(image: QImage, cx: int, cy: int, radius: int = 3) -> Tuple[int, int, int]:
    """取 (2*radius+1)^2 邻域像素的中值，抑制噪点/压缩伪影对取色的干扰。"""
    w, h = image.width(), image.height()
    rs, gs, bs = [], [], []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                color = image.pixelColor(x, y)
                rs.append(color.red())
                gs.append(color.green())
                bs.append(color.blue())
    rs.sort(); gs.sort(); bs.sort()
    mid = len(rs) // 2
    return rs[mid], gs[mid], bs[mid]


class _ClickableImageLabel(QLabel):
    """支持鼠标点击取色的图片显示控件，点击后发出图像坐标（原图像素坐标）。"""

    pixel_clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._markers: List[Tuple[int, int]] = []  # 显示用的标记点（缩放后坐标）

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            self.pixel_clicked.emit(pos.x(), pos.y())
        super().mousePressEvent(event)


class ImageColorPickerDialog(QDialog):
    """
    图片取色对话框。

    调用方式：
        dlg = ImageColorPickerDialog(self, title="效果图取色", initial_path=None)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lab = dlg.get_result_lab()   # (L, a, b)，多点平均结果
    """

    def __init__(self, parent=None, title: str = "图片取色", initial_path: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(880, 560)

        self._original_image: Optional[QImage] = None
        self._scale_factor: float = 1.0
        # 采样点：[(x_img, y_img, R, G, B, L, a, b), ...]
        self._samples: List[Tuple[int, int, int, int, int, float, float, float]] = []

        self._build_ui()
        if initial_path:
            self._load_image(initial_path)

    # ---------------------------------------------------------- UI 搭建 ----

    def _build_ui(self):
        root = QHBoxLayout(self)

        # ---- 左侧：图片显示区 ----
        left = QVBoxLayout()

        toolbar = QHBoxLayout()
        open_btn = GhostButton("📂 打开图片")
        open_btn.clicked.connect(self._on_open_image)
        toolbar.addWidget(open_btn)

        toolbar.addWidget(QLabel("缩放："))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(20, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(140)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self.zoom_slider)
        self.zoom_label = QLabel("100%")
        toolbar.addWidget(self.zoom_label)
        toolbar.addStretch(1)
        left.addLayout(toolbar)

        self.image_label = _ClickableImageLabel()
        self.image_label.pixel_clicked.connect(self._on_pixel_clicked)
        self.image_label.setText("请点击左上角【打开图片】加载效果图 / 瓶身照片")
        self.image_label.setStyleSheet(
            "background-color:#f8fafc; border:1px dashed #cbd5e1; border-radius:8px; color:#94a3b8;"
        )

        scroll = QScrollArea()
        scroll.setWidget(self.image_label)
        scroll.setWidgetResizable(False)
        scroll.setMinimumWidth(560)
        left.addWidget(scroll, 1)

        hint = QLabel("💡 提示：在目标颜色区域多点几次（避开高光/阴影/反光边缘），系统会自动取多点平均色，更接近真实颜色。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        left.addWidget(hint)

        root.addLayout(left, 3)

        # ---- 右侧：采样点列表 + 平均结果 ----
        right = QVBoxLayout()
        right.addWidget(QLabel("已采样的颜色点："))
        self.sample_list = QListWidget()
        right.addWidget(self.sample_list, 1)

        clear_btn = GhostButton("清除全部采样点")
        clear_btn.clicked.connect(self._on_clear_samples)
        right.addWidget(clear_btn)

        right.addWidget(QLabel("多点平均目标色预览："))
        self.result_swatch = ColorSwatch(height=64)
        right.addWidget(self.result_swatch)

        self.result_label = QLabel("尚未采样")
        self.result_label.setStyleSheet("font-weight:700; font-size:13px;")
        right.addWidget(self.result_label)

        btn_row = QHBoxLayout()
        ok_btn = PrimaryButton("✅ 确定使用此颜色")
        ok_btn.clicked.connect(self._on_confirm)
        cancel_btn = GhostButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        right.addLayout(btn_row)

        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setMinimumWidth(260)
        root.addWidget(right_widget, 1)

    # ---------------------------------------------------------- 图片加载 ----

    def _on_open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择效果图 / 瓶身照片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._load_image(path)

    def _load_image(self, path: str):
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "加载失败", "无法读取该图片文件，请检查格式或路径。")
            return
        self._original_image = image
        self._samples.clear()
        self.sample_list.clear()
        self._refresh_result_display()
        self.zoom_slider.setValue(100)
        self._render_pixmap()

    def _render_pixmap(self):
        if self._original_image is None:
            return
        scaled = self._original_image.scaled(
            int(self._original_image.width() * self._scale_factor),
            int(self._original_image.height() * self._scale_factor),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)

        # 在缩放后的图上绘制已采样点的标记圈，方便用户看清点过哪些位置
        if self._samples:
            painter = QPainter(pixmap)
            pen = QPen(QColor("#0d9488"))
            pen.setWidth(2)
            painter.setPen(pen)
            for (xi, yi, *_rest) in self._samples:
                sx = int(xi * self._scale_factor)
                sy = int(yi * self._scale_factor)
                painter.drawEllipse(QPoint(sx, sy), 6, 6)
            painter.end()

        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())

    def _on_zoom_changed(self, value: int):
        self._scale_factor = value / 100.0
        self.zoom_label.setText(f"{value}%")
        self._render_pixmap()

    # ---------------------------------------------------------- 取色逻辑 ----

    def _on_pixel_clicked(self, x_disp: int, y_disp: int):
        if self._original_image is None:
            return
        # 缩放后坐标 -> 原图坐标
        x_img = int(x_disp / self._scale_factor)
        y_img = int(y_disp / self._scale_factor)
        w, h = self._original_image.width(), self._original_image.height()
        if not (0 <= x_img < w and 0 <= y_img < h):
            return

        r, g, b = _median_neighborhood(self._original_image, x_img, y_img, radius=3)
        L, a, bb = srgb_to_lab(r, g, b)
        self._samples.append((x_img, y_img, r, g, b, L, a, bb))

        item = QListWidgetItem(f"点{len(self._samples)}：RGB({r},{g},{b})  Lab({L:.1f},{a:.1f},{bb:.1f})")
        item.setBackground(QColor(r, g, b))
        # 根据亮度自动选择文字颜色，保证可读性
        item.setForeground(QColor("#ffffff" if (r * 0.299 + g * 0.587 + b * 0.114) < 140 else "#1e293b"))
        self.sample_list.addItem(item)

        self._refresh_result_display()
        self._render_pixmap()

    def _on_clear_samples(self):
        self._samples.clear()
        self.sample_list.clear()
        self._refresh_result_display()
        self._render_pixmap()

    def _refresh_result_display(self):
        if not self._samples:
            self.result_label.setText("尚未采样")
            self.result_swatch.set_rgb(255, 255, 255)
            return
        avg_L = sum(s[5] for s in self._samples) / len(self._samples)
        avg_a = sum(s[6] for s in self._samples) / len(self._samples)
        avg_b = sum(s[7] for s in self._samples) / len(self._samples)
        r, g, b = lab_to_srgb_approx(avg_L, avg_a, avg_b)
        self.result_swatch.set_rgb(r, g, b)
        self.result_label.setText(
            f"共{len(self._samples)}个采样点，平均 Lab = ({avg_L:.2f}, {avg_a:.2f}, {avg_b:.2f})"
        )

    # ---------------------------------------------------------- 结果输出 ----

    def _on_confirm(self):
        if not self._samples:
            QMessageBox.information(self, "提示", "请先在图片上点击至少一个目标颜色区域。")
            return
        self.accept()

    def get_result_lab(self) -> Tuple[float, float, float]:
        """返回多点采样的平均 Lab 值，仅在 exec() 返回 Accepted 后调用有效。"""
        if not self._samples:
            return (50.0, 0.0, 0.0)
        avg_L = sum(s[5] for s in self._samples) / len(self._samples)
        avg_a = sum(s[6] for s in self._samples) / len(self._samples)
        avg_b = sum(s[7] for s in self._samples) / len(self._samples)
        return (avg_L, avg_a, avg_b)

    def get_loaded_image_path_hint(self) -> Optional[str]:
        return None


# ============================================================================
# 多色位批量取色对话框（一张效果图 -> 多个色位：文字/LOGO/图案 各自的目标色）
# ============================================================================

class JobImageColorMapDialog(QDialog):
    """
    多色位批量取色对话框 —— 专为丝印多色工单场景设计。

    背景：一个瓶身的效果图上通常同时能看到文字、LOGO、图案等多个不同颜色
    的印刷区域（丝印工艺每种颜色对应一个独立网版）。这个对话框允许工人
    只打开一次效果图，依次点选每个区域并"归类"到对应色位（文字/LOGO/
    图案，或自定义名称），每个色位内部同样支持多点取平均、抗高光干扰。

    交互流程：
        1. 打开效果图
        2. 顶部选择"当前采集色位"（下拉框，可新建）
        3. 在图上点选该色位对应区域的若干个点
        4. 切换下拉框到下一个色位，重复点选
        5. 点击【完成，应用到工单】，返回 {色位名称: (L,a,b)} 字典
    """

    def __init__(self, parent=None, title: str = "效果图批量取色 —— 多色位识别"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(920, 600)

        self._original_image: Optional[QImage] = None
        self._scale_factor: float = 1.0
        # {station_name: [(x_img,y_img,r,g,b,L,a,b), ...]}
        self._station_samples: Dict[str, list] = {}
        self._current_station: Optional[str] = None

        self._build_ui()
        self._add_station("文字")
        self._add_station("LOGO")
        self._add_station("图案")
        self.station_combo.setCurrentIndex(0)

    # ---------------------------------------------------------- UI 搭建 ----

    def _build_ui(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        toolbar = QHBoxLayout()
        open_btn = GhostButton("📂 打开效果图")
        open_btn.clicked.connect(self._on_open_image)
        toolbar.addWidget(open_btn)
        toolbar.addWidget(QLabel("缩放："))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(20, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self.zoom_slider)
        self.zoom_label = QLabel("100%")
        toolbar.addWidget(self.zoom_label)
        toolbar.addStretch(1)
        left.addLayout(toolbar)

        station_row = QHBoxLayout()
        station_row.addWidget(QLabel("当前采集色位："))
        self.station_combo = QComboBox()
        self.station_combo.currentTextChanged.connect(self._on_station_changed)
        station_row.addWidget(self.station_combo, 1)
        new_station_btn = GhostButton("＋ 新建色位")
        new_station_btn.clicked.connect(self._on_new_station)
        station_row.addWidget(new_station_btn)
        left.addLayout(station_row)

        self.image_label = _ClickableImageLabel()
        self.image_label.pixel_clicked.connect(self._on_pixel_clicked)
        self.image_label.setText("请点击【打开效果图】加载客户渲染图")
        self.image_label.setStyleSheet(
            "background-color:#f8fafc; border:1px dashed #cbd5e1; border-radius:8px; color:#94a3b8;"
        )
        scroll = QScrollArea()
        scroll.setWidget(self.image_label)
        scroll.setWidgetResizable(False)
        scroll.setMinimumWidth(560)
        left.addWidget(scroll, 1)

        hint = QLabel("💡 先在上方下拉框选好色位（比如\"文字\"），再去图上点该颜色区域；切换色位继续点其他颜色区域。同一色位可多点取平均，避开高光/阴影。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        left.addWidget(hint)

        root.addLayout(left, 3)

        right = QVBoxLayout()
        right.addWidget(QLabel("各色位采集情况："))
        self.station_list = QListWidget()
        right.addWidget(self.station_list, 1)

        del_station_btn = GhostButton("删除当前色位")
        del_station_btn.clicked.connect(self._on_delete_current_station)
        right.addWidget(del_station_btn)

        clear_btn = GhostButton("清除当前色位采样点")
        clear_btn.clicked.connect(self._on_clear_current_station)
        right.addWidget(clear_btn)

        btn_row = QHBoxLayout()
        ok_btn = PrimaryButton("✅ 完成，应用到工单")
        ok_btn.clicked.connect(self._on_confirm)
        cancel_btn = GhostButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        right.addLayout(btn_row)

        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setMinimumWidth(260)
        root.addWidget(right_widget, 1)

    # ---------------------------------------------------------- 色位管理 ----

    def _add_station(self, name: str):
        if name in self._station_samples:
            return
        self._station_samples[name] = []
        self.station_combo.addItem(name)
        self._refresh_station_list()

    def _on_new_station(self):
        name, ok = QInputDialog.getText(self, "新建色位", "色位名称（例如：文字 / LOGO / 图案 / 底纹）：")
        name = name.strip()
        if ok and name:
            if name in self._station_samples:
                QMessageBox.information(self, "提示", "该色位名称已存在。")
                return
            self._add_station(name)
            self.station_combo.setCurrentText(name)

    def _on_station_changed(self, name: str):
        self._current_station = name if name else None
        self._render_pixmap()

    def _on_delete_current_station(self):
        if not self._current_station or self.station_combo.count() <= 1:
            QMessageBox.information(self, "提示", "至少需要保留一个色位。")
            return
        name = self._current_station
        del self._station_samples[name]
        idx = self.station_combo.findText(name)
        self.station_combo.removeItem(idx)
        self._refresh_station_list()
        self._render_pixmap()

    def _on_clear_current_station(self):
        if self._current_station:
            self._station_samples[self._current_station] = []
            self._refresh_station_list()
            self._render_pixmap()

    def _refresh_station_list(self):
        self.station_list.clear()
        for name, samples in self._station_samples.items():
            if samples:
                avg_L = sum(s[5] for s in samples) / len(samples)
                avg_a = sum(s[6] for s in samples) / len(samples)
                avg_b = sum(s[7] for s in samples) / len(samples)
                r, g, b = lab_to_srgb_approx(avg_L, avg_a, avg_b)
                text = f"{name}：{len(samples)}点  Lab({avg_L:.1f},{avg_a:.1f},{avg_b:.1f})"
            else:
                r, g, b = 255, 255, 255
                text = f"{name}：未采样"
            item = QListWidgetItem(text)
            item.setBackground(QColor(r, g, b))
            item.setForeground(QColor("#ffffff" if (r * 0.299 + g * 0.587 + b * 0.114) < 140 else "#1e293b"))
            self.station_list.addItem(item)

    # ---------------------------------------------------------- 图片加载/取色 ----

    def _on_open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择效果图", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            image = QImage(path)
            if image.isNull():
                QMessageBox.warning(self, "加载失败", "无法读取该图片文件，请检查格式或路径。")
                return
            self._original_image = image
            self.zoom_slider.setValue(100)
            self._render_pixmap()

    def _render_pixmap(self):
        if self._original_image is None:
            return
        scaled = self._original_image.scaled(
            int(self._original_image.width() * self._scale_factor),
            int(self._original_image.height() * self._scale_factor),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)

        painter = QPainter(pixmap)
        colors_cycle = ["#0d9488", "#dc2626", "#2563eb", "#d97706", "#7c3aed", "#059669"]
        for i, (name, samples) in enumerate(self._station_samples.items()):
            pen = QPen(QColor(colors_cycle[i % len(colors_cycle)]))
            pen.setWidth(2)
            painter.setPen(pen)
            for (xi, yi, *_rest) in samples:
                sx = int(xi * self._scale_factor)
                sy = int(yi * self._scale_factor)
                painter.drawEllipse(QPoint(sx, sy), 6, 6)
        painter.end()

        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())

    def _on_zoom_changed(self, value: int):
        self._scale_factor = value / 100.0
        self.zoom_label.setText(f"{value}%")
        self._render_pixmap()

    def _on_pixel_clicked(self, x_disp: int, y_disp: int):
        if self._original_image is None or not self._current_station:
            return
        x_img = int(x_disp / self._scale_factor)
        y_img = int(y_disp / self._scale_factor)
        w, h = self._original_image.width(), self._original_image.height()
        if not (0 <= x_img < w and 0 <= y_img < h):
            return

        r, g, b = _median_neighborhood(self._original_image, x_img, y_img, radius=3)
        L, a, bb = srgb_to_lab(r, g, b)
        self._station_samples[self._current_station].append((x_img, y_img, r, g, b, L, a, bb))
        self._refresh_station_list()
        self._render_pixmap()

    # ---------------------------------------------------------- 结果输出 ----

    def _on_confirm(self):
        if not any(self._station_samples.values()):
            QMessageBox.information(self, "提示", "请至少为一个色位采样后再确认。")
            return
        self.accept()

    def get_station_labs(self) -> Dict[str, Tuple[float, float, float]]:
        """返回 {色位名称: (L,a,b)}，仅包含已经采样过的色位。"""
        result = {}
        for name, samples in self._station_samples.items():
            if not samples:
                continue
            avg_L = sum(s[5] for s in samples) / len(samples)
            avg_a = sum(s[6] for s in samples) / len(samples)
            avg_b = sum(s[7] for s in samples) / len(samples)
            result[name] = (avg_L, avg_a, avg_b)
        return result
