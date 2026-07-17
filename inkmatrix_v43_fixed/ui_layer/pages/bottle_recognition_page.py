# -*- coding: utf-8 -*-
"""
bottle_recognition_page.py  (UI层 - 承印物识别与材质档案)
============================================================
两件事合在一页：

  ① 底色识别 —— 上传瓶身实拍照片，在照片上点选瓶身本体（避开高光/
     标签），自动算出承印物底色 Lab，不用人工估测查表。

  ② 材质档案（问题6新增）—— 选定这只瓶子是什么材质（PP/PE/PET/玻璃/
     铝/铜/纸…），系统随即知道三件在实际生产里真正要命的事：

        · 会不会掉墨 —— 附着力系数 + 必须做的前处理
        · 印出来偏不偏色 —— 材质吸墨会让墨膜变薄、颜色变浅，这个必须
          进配色算法做补偿，否则纸上和玻璃上用同一个配方，颜色差很远
        · 要不要打白底 —— 深色/金属底材遮盖需求高，浅色图案压不住

     选好材质存档后，以后在【配色工作台】/【多色工单】里选中这只瓶子，
     系统就自动带上这些参数去算配方，不用每次重新交代一遍。

材质的物理参数集中定义在 dal_layer.data_manager.MATERIAL_LIBRARY，
数值取自丝印行业通行的经验区间。⚠️ 正式投产前建议用自家油墨在每种
材质上打样标定一次，把数值改成现场实测的，配色才会真正准。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFormLayout, QFrame,
    QScrollArea
)

from core_layer.color_convert import lab_to_srgb_approx
from dal_layer.data_manager import (
    MATERIAL_LIBRARY, MATERIAL_FAMILIES, get_material_props, material_label,
)
from ui_layer.widgets import Card, PrimaryButton, GhostButton, DangerButton, ColorSwatch, ResponsiveRow, Badge
from ui_layer.color_pickers import ImageColorPickerDialog
from ui_layer.color_swatch_library import ColorSwatchPickerDialog

# 兼容旧数据：v31及更早的瓶型档案里存的是这几个老代码，映射到新材质库
LEGACY_SUBSTRATE_MAP = {
    "glass_clear": "glass_clear",
    "glass_amber": "glass_amber",
    "plastic_white": "plastic_pe",   # 老的"白色塑料(PE/PP)"按最保守的PE算
    "plastic_clear": "plastic_pet",
    "paper_kraft": "paper_kraft",
    "custom": "custom",
}


def _normalize_substrate(code: str) -> str:
    """旧代码 -> 新材质代码。未知的一律回落到 custom（中性默认值）。"""
    if code in MATERIAL_LIBRARY:
        return code
    return LEGACY_SUBSTRATE_MAP.get(code, "custom")


class BottleRecognitionPage(QWidget):

    bottle_db_changed = pyqtSignal()

    def __init__(self, bottle_repo, parent=None):
        super().__init__(parent)
        self.bottle_repo = bottle_repo
        self._captured_lab = None
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("承印物识别与材质档案")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "识别瓶身底色 + 登记材质（塑料/玻璃/金属/纸）。材质会直接参与配方计算："
            "吸墨的材质自动补偿颜色，深色/金属底材自动加强遮盖，低附着力材质提前预警掉墨风险"
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        body = ResponsiveRow(breakpoint=980)

        # 【小屏被切】修复：
        # 左边这张"识别底色+登记材质"卡片是个很长的表单（取色 + 材质选择 + 三个
        # 材质系数说明 + 建档字段），实测最小高度要 863px。而 1366×768 的笔记本
        # 扣掉标题栏和状态栏之后，页面可用高度只有约 658px——底部的【保存承印物
        # 档案】按钮直接被切在屏幕外，用户根本点不到。
        #
        # 别的页面（配色工作台、账户管理、进销存）的长表单都是包在滚动区里的，
        # 唯独这一页漏了。补上，跟其它页面保持一致。
        capture_scroll = QScrollArea()
        capture_scroll.setWidgetResizable(True)
        capture_scroll.setFrameShape(QFrame.Shape.NoFrame)
        capture_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        capture_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        capture_scroll.setWidget(self._build_capture_card())

        body.add_panel(capture_scroll, 1)
        body.add_panel(self._build_list_card(), 1)
        root.addWidget(body, 1)

    # ------------------------------------------------------------------
    # ① 识别 + 建档
    # ------------------------------------------------------------------

    def _build_capture_card(self) -> Card:
        card = Card("① 识别底色 + 登记材质")
        lay = card.body_layout

        hint = QLabel("💡 拍摄建议：自然光/标准光源下拍瓶身正面，避免强反光；点选时避开高光和标签文字区域。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        lay.addWidget(hint)

        capture_btn = PrimaryButton("📷 上传瓶身照片并识别底色")
        capture_btn.clicked.connect(self._on_capture)
        lay.addWidget(capture_btn)

        swatch_btn = GhostButton("🎨 或者：从色卡选择相近底色")
        swatch_btn.clicked.connect(self._on_pick_from_swatch)
        lay.addWidget(swatch_btn)

        lay.addWidget(QLabel("识别结果预览："))
        self.result_swatch = ColorSwatch(height=58)
        lay.addWidget(self.result_swatch)
        self.result_label = QLabel("尚未识别")
        self.result_label.setStyleSheet("font-weight:700;")
        lay.addWidget(self.result_label)

        divider = QFrame(); divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#e2e8f0;")
        lay.addWidget(divider)

        form = QFormLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("例如 BT-CUSTOM01")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 客户A新款白瓶")

        # 两级材质下拉：先选大类（塑料/玻璃/金属/纸），再选具体材质
        self.family_combo = QComboBox()
        for family in MATERIAL_FAMILIES:
            self.family_combo.addItem(family, family)
        self.family_combo.currentIndexChanged.connect(self._on_family_changed)

        self.material_combo = QComboBox()
        self.material_combo.currentIndexChanged.connect(self._on_material_changed)

        form.addRow("瓶型编号：", self.code_edit)
        form.addRow("瓶型名称：", self.name_edit)
        form.addRow("材质大类：", self.family_combo)
        form.addRow("具体材质：", self.material_combo)
        lay.addLayout(form)

        # 选中材质后，把这三件事直接摆出来给师傅看
        self.material_info = QLabel("")
        self.material_info.setWordWrap(True)
        self.material_info.setStyleSheet(
            "background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; "
            "padding:10px 12px; font-size:12px; color:#334155;"
        )
        lay.addWidget(self.material_info)

        # 附着力方案面板（选了材质才显示）
        self.adhesion_info = QLabel("")
        self.adhesion_info.setWordWrap(True)
        self.adhesion_info.setTextFormat(Qt.TextFormat.RichText)
        self.adhesion_info.setVisible(False)
        lay.addWidget(self.adhesion_info)

        save_btn = PrimaryButton("💾 保存至承印物库")
        save_btn.clicked.connect(self._on_save)
        lay.addWidget(save_btn)

        self._on_family_changed()  # 初始化二级下拉
        return card

    def _on_family_changed(self):
        family = self.family_combo.currentData()
        self.material_combo.blockSignals(True)
        self.material_combo.clear()
        for code in MATERIAL_FAMILIES.get(family, []):
            self.material_combo.addItem(MATERIAL_LIBRARY[code]["label"], code)
        self.material_combo.blockSignals(False)
        self._on_material_changed()

    def _on_material_changed(self):
        code = self.material_combo.currentData()
        if not code:
            self.material_info.setText("")
            return
        p = get_material_props(code)

        adhesion = p["adhesion_factor"]
        if adhesion >= 0.90:
            adh_txt = f"<span style='color:#16a34a;'><b>好（{adhesion:.2f}）</b></span>"
        elif adhesion >= 0.80:
            adh_txt = f"<span style='color:#ca8a04;'><b>一般（{adhesion:.2f}）</b></span>"
        else:
            adh_txt = f"<span style='color:#dc2626;'><b>差（{adhesion:.2f}）⚠️ 掉墨风险高</b></span>"

        film = p["film_factor"]
        if film >= 0.98:
            film_txt = "不吸墨，显色足（墨全留表面）"
        else:
            film_txt = (f"<span style='color:#ca8a04;'>会吸墨（留存 {film:.0%}），"
                        f"同一配方印上去颜色会偏浅——系统已在寻优时自动补偿</span>")

        boost = p["opacity_boost"]
        boost_txt = "常规" if boost <= 1.05 else \
            f"<span style='color:#ca8a04;'>需 {boost:.2f} 倍遮盖力（底色深/有金属光泽，浅色图案建议先打白底）</span>"

        self.material_info.setText(
            f"<b>配色影响</b><br>"
            f"　附着力：{adh_txt}<br>"
            f"　吸墨：{film_txt}<br>"
            f"　遮盖：{boost_txt}"
        )

        # ── 附着力方案（3M 百格测试）──────────────────────────────────
        # 这一段是丝印现场最容易翻车、也最容易被忽略的一环。
        # PP 只有 29 达因、PE 31 达因——不做前处理，用什么墨、加什么助剂都白搭。
        # 把这些直接摆在师傅眼前，比让他印完了做百格测试才发现掉墨强得多。
        plan = p.get("adhesion_plan") or {}
        if not plan:
            self.adhesion_info.setVisible(False)
            return

        risk = plan.get("risk", "unknown")
        colors = {
            "high":    ("#fef2f2", "#fecaca", "#991b1b", "🔴 高风险 —— 不做前处理必掉墨"),
            "medium":  ("#fff7ed", "#fed7aa", "#9a3412", "🟠 中等风险 —— 需要注意"),
            "low":     ("#f0fdf4", "#bbf7d0", "#166534", "🟢 低风险 —— 常规处理即可"),
            "none":    ("#f8fafc", "#e2e8f0", "#475569", "⚪ 不适用"),
            "unknown": ("#f8fafc", "#e2e8f0", "#475569", "⚫ 未知材质 —— 必须先打样验证"),
        }
        bg, border, fg, risk_label = colors.get(risk, colors["unknown"])

        dyne = plan.get("surface_energy_dyne")
        need = plan.get("required_dyne")
        dyne_line = ""
        if dyne is not None and need is not None:
            gap = need - dyne
            if gap > 0:
                dyne_line = (
                    f"<b>表面能：</b>只有 <b>{dyne} 达因</b>，"
                    f"而印刷需要 <b>≥{need} 达因</b>——<b>差 {gap} 达因</b>。"
                    f"<br>"
                )
            else:
                dyne_line = (
                    f"<b>表面能：</b>{dyne} 达因（≥{need} 的门槛），够用。<br>"
                )

        html = f"<b>🔬 附着力方案　{risk_label}</b><br><br>{dyne_line}"
        html += f"<b>① 前处理：</b>{plan.get('treatment','')}".replace(chr(10), "<br>　　") + "<br><br>"
        html += f"<b>② 油墨/固化剂：</b>{plan.get('hardener','')}".replace(chr(10), "<br>　　") + "<br><br>"
        html += f"<b>③ 干燥/烘烤：</b>{plan.get('bake','')}<br><br>"
        html += (
            f"<b>④ 验收（3M 百格测试）：</b>目标 <b>{plan.get('target_grade','')}</b><br>"
            f"　　做法：百格刀在墨层上划 10×10 个 1mm 小格（要划透到底材），"
            f"软毛刷扫掉碎屑，贴 3M 600/610 胶带压实，<b>90° 快速撕起</b>，数脱落格数。"
            f"同一位置重复 2~3 次。<br>"
            f"　　100 格全不脱 = 5B = 合格。"
        )

        self.adhesion_info.setText(html)
        self.adhesion_info.setStyleSheet(
            f"background:{bg}; border:1px solid {border}; color:{fg}; "
            f"border-radius:8px; padding:11px 13px; font-size:12px;"
        )
        self.adhesion_info.setVisible(True)

    # ------------------------------------------------------------------
    # ② 承印物库列表
    # ------------------------------------------------------------------

    def _build_list_card(self) -> Card:
        card = Card("② 承印物库")
        lay = card.body_layout

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["底色", "编号", "名称", "材质", "附着力"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(40)
        lay.addWidget(self.table, 1)

        del_btn = DangerButton("－ 删除选中瓶型")
        del_btn.setMinimumHeight(34)
        del_btn.clicked.connect(self._on_delete)
        lay.addWidget(del_btn)

        return card

    def refresh_table(self):
        records = self.bottle_repo.load_all()
        self.table.setRowCount(len(records))
        for row, r in enumerate(records):
            lab = r.get("base_lab", [90.0, 0.0, 0.0])
            rgb = lab_to_srgb_approx(*lab)
            mat_code = _normalize_substrate(r.get("substrate_type", ""))
            props = get_material_props(mat_code)

            swatch_item = QTableWidgetItem("")
            swatch_item.setBackground(QColor(*rgb))
            code_item = QTableWidgetItem(r["code"])
            code_item.setData(Qt.ItemDataRole.UserRole, r["code"])
            name_item = QTableWidgetItem(r["name"])
            mat_item = QTableWidgetItem(props["label"])

            adhesion = props["adhesion_factor"]
            adh_item = QTableWidgetItem(f"{adhesion:.2f}")
            if adhesion < 0.70:
                adh_item.setBackground(QColor("#fee2e2"))
                adh_item.setForeground(QColor("#b91c1c"))
                adh_item.setToolTip(f"⚠️ 掉墨风险高！前处理要求：{props['pretreatment']}")
            elif adhesion < 0.85:
                adh_item.setBackground(QColor("#fef9c3"))
                adh_item.setForeground(QColor("#b45309"))
                adh_item.setToolTip(f"前处理要求：{props['pretreatment']}")

            for item in (swatch_item, code_item, name_item, mat_item, adh_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            for col, item in enumerate((swatch_item, code_item, name_item, mat_item, adh_item)):
                self.table.setItem(row, col, item)

    # ------------------------------------------------------------------

    def _on_capture(self):
        dlg = ImageColorPickerDialog(self, title="承印物识别 —— 点选瓶身本体颜色")
        if dlg.exec():
            L, a, b = dlg.get_result_lab()
            self._captured_lab = (L, a, b)
            r, g, bb = lab_to_srgb_approx(L, a, b)
            self.result_swatch.set_rgb(r, g, bb)
            self.result_label.setText(f"识别底色 Lab = ({L:.2f}, {a:.2f}, {b:.2f})")

    def _on_pick_from_swatch(self):
        dlg = ColorSwatchPickerDialog(self, title="承印物识别 —— 从色卡选择相近底色")
        if dlg.exec():
            L, a, b = dlg.get_result_lab()
            self._captured_lab = (L, a, b)
            r, g, bb = lab_to_srgb_approx(L, a, b)
            self.result_swatch.set_rgb(r, g, bb)
            self.result_label.setText(f"色卡选定底色 Lab = ({L:.2f}, {a:.2f}, {b:.2f})")

    def _on_save(self):
        if self._captured_lab is None:
            QMessageBox.warning(self, "提示", "请先上传照片识别底色，或从色卡选一个相近底色。")
            return
        code = self.code_edit.text().strip()
        name = self.name_edit.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "提示", "请填写瓶型编号与名称。")
            return

        mat_code = self.material_combo.currentData() or "custom"
        props = get_material_props(mat_code)

        record = {
            "code": code,
            "name": name,
            "base_lab": list(self._captured_lab),
            "substrate_type": mat_code,
        }
        self.bottle_repo.upsert(record)
        self.refresh_table()
        self.bottle_db_changed.emit()

        msg = (
            f"瓶型档案 [{code}] {name} 已保存。\n\n"
            f"材质：{props['label']}\n"
            f"以后在【配色工作台】/【多色工单】选中这只瓶子，系统会自动按这个材质"
            f"调整配方（吸墨补偿 + 遮盖力要求）。\n"
        )
        if props["adhesion_factor"] < 0.80:
            msg += (
                f"\n⚠️ 开机前务必确认：{props['pretreatment']}\n"
                f"这个材质不做前处理，油墨指甲一刮就掉。"
            )
        QMessageBox.information(self, "已保存", msg)

        self.code_edit.clear()
        self.name_edit.clear()

    def _on_delete(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在表格中点击选中要删除的瓶型。")
            return
        code = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(self, "确认删除", f"确定要删除瓶型档案 [{code}] 吗？")
        if confirm == QMessageBox.StandardButton.Yes:
            self.bottle_repo.delete(code)
            self.refresh_table()
            self.bottle_db_changed.emit()
