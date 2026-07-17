# -*- coding: utf-8 -*-
"""
ink_checklist.py  (UI层 - 可复用组件，视觉升级版)
=====================================================
"在库油墨勾选"这个交互（工人勾选今天仓库有什么墨，算法就在什么墨里
寻优）在【配色工作台】与【多色印刷工单】两个页面都要用到，抽成独立
组件避免重复代码，也保证两处行为完全一致。

视觉升级说明：原来是塞在一个140px高小方框里的纯文字QListWidget，
油墨种类一多就完全看不清、挤成一团。现在改成"可勾选色卡网格"：
    - 每支油墨一张卡片：勾选框 + 大色块 + 名称 + 类别徽标
    - 支持搜索框按名称/编号过滤，油墨种类多起来也能快速定位
    - 卡片式网格铺开，比塞进一个小列表框清晰得多
"""

from typing import List, Callable, Optional, Dict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QCheckBox, QScrollArea, QFrame
)

from core_layer.color_convert import lab_to_srgb_approx
from ui_layer.ink_meta import category_label, category_color
from ui_layer.widgets import Badge, GhostButton


class _InkCard(QFrame):
    """单支油墨的可勾选卡片：勾选框 + 色块 + 名称 + 类别徽标。"""

    toggled = pyqtSignal(str, bool)  # (ink_code, checked)

    def __init__(self, code: str, name: str, category: str, rgb: tuple, checked: bool = False,
                 stock_status: str = "正常", parent=None):
        super().__init__(parent)
        self.code = code
        self.stock_status = stock_status
        self.setObjectName("InkCard")
        self.setStyleSheet(
            "#InkCard { background-color:#ffffff; border:1px solid #e2e8f0; border-radius:10px; }"
            "#InkCard:hover { border-color:#0d9488; background-color:#f0fdfa; }"
        )
        self.setMinimumHeight(58)
        self.setMaximumHeight(58)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 12, 6)
        lay.setSpacing(10)

        self.checkbox = QCheckBox()
        is_out_of_stock = stock_status == "缺货"
        self.checkbox.setChecked(checked and not is_out_of_stock)
        self.checkbox.setEnabled(not is_out_of_stock)
        if is_out_of_stock:
            self.setToolTip("该油墨库存已用完，请先在【油墨库管理】补充库存或联系油墨供应商，暂时无法参与配方寻优。")
        self.checkbox.stateChanged.connect(
            lambda state: self.toggled.emit(self.code, state == Qt.CheckState.Checked.value)
        )
        lay.addWidget(self.checkbox)

        swatch = QFrame()
        swatch.setFixedSize(34, 34)
        swatch_style = (
            f"background-color: rgb({rgb[0]},{rgb[1]},{rgb[2]}); "
            f"border-radius: 7px; border: 1px solid #d1d5db;"
        )
        swatch.setStyleSheet(swatch_style)
        if is_out_of_stock:
            swatch.setEnabled(False)
        lay.addWidget(swatch)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        display_text = f"[{code}] {name}"
        if len(display_text) > 22:
            display_text = display_text[:21] + "…"
        name_label = QLabel(display_text)
        label_color = "#94a3b8" if is_out_of_stock else "#1e293b"
        name_label.setStyleSheet(f"font-size:12px; font-weight:600; color:{label_color};")
        name_label.setWordWrap(False)
        name_label.setToolTip(f"[{code}] {name}")  # 名称被截断时,鼠标悬停能看到完整名称
        text_col.addWidget(name_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(4)
        badge = Badge(category_label(category), bg_hex=category_color(category))
        badge.setFixedHeight(18)
        badge_row.addWidget(badge)
        self._stock_badge = None
        if is_out_of_stock:
            self._stock_badge = Badge("缺货", bg_hex="#dc2626")
            self._stock_badge.setFixedHeight(18)
            badge_row.addWidget(self._stock_badge)
        elif stock_status == "库存不足":
            self._stock_badge = Badge("库存不足", bg_hex="#d97706")
            self._stock_badge.setFixedHeight(18)
            badge_row.addWidget(self._stock_badge)
        badge_row.addStretch(1)
        self._badge_row = badge_row
        self._name_label = name_label
        self._swatch = swatch
        text_col.addLayout(badge_row)
        lay.addLayout(text_col, 1)

    def update_stock_status(self, stock_status: str):
        """
        运行时更新库存状态（比如执行配墨消耗后库存变了），不重新创建卡片
        （重建卡片会触发之前修过的"浮空残影重叠"bug，这里只更新已有控件的显示）。
        """
        if stock_status == self.stock_status:
            return
        self.stock_status = stock_status
        is_out_of_stock = stock_status == "缺货"

        self.checkbox.setEnabled(not is_out_of_stock)
        if is_out_of_stock:
            self.checkbox.setChecked(False)
            self.setToolTip("该油墨库存已用完，请先在【油墨库管理】补充库存或联系油墨供应商，暂时无法参与配方寻优。")
        else:
            self.setToolTip("")
        self._swatch.setEnabled(not is_out_of_stock)
        self._name_label.setStyleSheet(
            f"font-size:12px; font-weight:600; color:{'#94a3b8' if is_out_of_stock else '#1e293b'};"
        )

        if self._stock_badge is not None:
            self._badge_row.removeWidget(self._stock_badge)
            self._stock_badge.deleteLater()
            self._stock_badge = None
        if is_out_of_stock:
            self._stock_badge = Badge("缺货", bg_hex="#dc2626")
        elif stock_status == "库存不足":
            self._stock_badge = Badge("库存不足", bg_hex="#d97706")
        if self._stock_badge is not None:
            self._stock_badge.setFixedHeight(18)
            self._badge_row.insertWidget(1, self._stock_badge)

    def set_checked(self, checked: bool):
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def mousePressEvent(self, event):
        # 点卡片任意位置（不只是勾选框本身）都能切换勾选状态，操作区域更大更好点
        # 缺货的墨勾选框本身是禁用的，这里也要拦住，不能整卡点击绕过去
        if event.button() == Qt.MouseButton.LeftButton and self.checkbox.isEnabled():
            self.checkbox.setChecked(not self.checkbox.isChecked())
        super().mousePressEvent(event)


class InkChecklistWidget(QWidget):
    """在库油墨勾选组件：卡片网格 + 搜索框，勾选状态在 refresh() 之间尽量保留。"""

    def __init__(self, ink_repo, get_engine: Optional[Callable[[], object]] = None,
                 get_allowed_codes: Optional[Callable[[], Optional[set]]] = None,
                 auto_select_all: bool = False, parent=None):
        super().__init__(parent)
        self.ink_repo = ink_repo
        self.get_engine = get_engine
        self.get_allowed_codes = get_allowed_codes  # 返回None=不限制(管理员); 返回set=只显示这些油墨(子账户)
        self.auto_select_all = auto_select_all
        self._checked_codes: set = set()
        self._initial_load_done = False
        self._cards: Dict[str, _InkCard] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索油墨名称或编号…")
        self.search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_edit, 1)

        select_all_btn = GhostButton("全选")
        select_all_btn.setMinimumHeight(28)
        select_all_btn.clicked.connect(self.select_all)
        toolbar.addWidget(select_all_btn)

        deselect_all_btn = GhostButton("清空")
        deselect_all_btn.setMinimumHeight(28)
        deselect_all_btn.clicked.connect(self.deselect_all)
        toolbar.addWidget(deselect_all_btn)
        root.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(280)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(8)
        self._grid_layout.setContentsMargins(2, 2, 2, 2)
        self.scroll.setWidget(self._grid_container)
        root.addWidget(self.scroll, 1)

        self.summary_label = QLabel("已勾选 0 种")
        self.summary_label.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(self.summary_label)

    # ================================================================
    # 全选 / 清空
    # ================================================================

    def select_all(self):
        """一键勾选当前筛选结果里的全部油墨（不用逐个点）。"""
        for card in self._cards.values():
            if card.isVisible():  # 只勾选当前搜索筛选后看得到的那些，跟用户预期一致
                card.set_checked(True)
                self._checked_codes.add(card.code)
        self._update_summary()

    def deselect_all(self):
        for card in self._cards.values():
            if card.isVisible():
                card.set_checked(False)
                self._checked_codes.discard(card.code)
        self._update_summary()

    # ================================================================
    # 数据刷新
    # ================================================================

    def refresh(self):
        self._checked_codes = set(self.get_checked_codes())

        # ------------------------------------------------------------
        # 注意（曾经的重叠bug教训）：这里绝不能用 card.setParent(None) 来
        # "销毁"旧卡片再重新创建——Qt在这种destructive重建方式下，被
        # setParent(None)的旧卡片会短暂变成孤立的顶层浮动窗口，残留在
        # 屏幕上跟其他控件重叠（表现为按钮/文字互相穿透）。
        # 正确做法：卡片对象常驻不销毁，用 hide()/show() 切换可见性，
        # 网格位置变化时直接 addWidget() 让Qt自己挪动即可。
        # ------------------------------------------------------------
        engine = self.get_engine() if self.get_engine else None
        all_records = self.ink_repo.load_all()

        allowed_codes = self.get_allowed_codes() if self.get_allowed_codes else None
        if allowed_codes is not None:
            records = [r for r in all_records if r["code"] in allowed_codes]
        else:
            records = all_records
        current_codes = {r["code"] for r in records}

        # 首次加载且开启了"默认全选"：把当前可见的油墨全部预先标记为已勾选
        if self.auto_select_all and not self._initial_load_done:
            self._checked_codes = set(current_codes)
            self._initial_load_done = True

        # 油墨库里已经删掉的墨、或者这个账户没有分配权限看到的墨，把对应卡片彻底清理掉
        for stale_code in list(self._cards.keys()):
            if stale_code not in current_codes:
                stale_card = self._cards.pop(stale_code)
                stale_card.hide()
                stale_card.deleteLater()

        for record in records:
            rgb = (200, 200, 200)
            if engine is not None:
                try:
                    lab = engine.compute_lab({record["code"]: 1.0}, apply_dry_back=False)
                    rgb = lab_to_srgb_approx(*lab)
                except Exception:
                    pass

            existing_card = self._cards.get(record["code"])
            if existing_card is not None:
                # 已存在的卡片：保留其当前勾选状态，只刷新库存状态显示，不重新创建
                existing_card.update_stock_status(self.ink_repo.stock_status(record))
                continue

            checked = record["code"] in self._checked_codes
            stock_status = self.ink_repo.stock_status(record)
            card = _InkCard(record["code"], record["name"], record.get("category", "color"), rgb, checked, stock_status)
            card.setParent(self._grid_container)
            card.toggled.connect(self._on_card_toggled)
            self._cards[record["code"]] = card

        self._relayout_grid(records)
        self._update_summary()

    def _relayout_grid(self, records: List[dict]):
        # 先把所有卡片从网格布局摘出来（不改变parent，不触发浮动残影问题），
        # 摘出后统一 hide()，再按当前筛选结果重新按顺序 addWidget() + show()。
        while self._grid_layout.count():
            self._grid_layout.takeAt(0)
        for card in self._cards.values():
            card.hide()

        columns = 1
        visible_records = self._filtered_records(records)
        row = col = 0
        for record in visible_records:
            card = self._cards.get(record["code"])
            if card is None:
                continue
            self._grid_layout.addWidget(card, row, col)
            card.show()
            col += 1
            if col >= columns:
                col = 0
                row += 1

    def _filtered_records(self, records: List[dict]) -> List[dict]:
        keyword = self.search_edit.text().strip().lower()
        if not keyword:
            return records
        return [r for r in records if keyword in r["code"].lower() or keyword in r["name"].lower()]

    def _apply_filter(self):
        self._relayout_grid(self.ink_repo.load_all())

    def _on_card_toggled(self, code: str, checked: bool):
        if checked:
            self._checked_codes.add(code)
        else:
            self._checked_codes.discard(code)
        self._update_summary()

    def _update_summary(self):
        self.summary_label.setText(f"已勾选 {len(self._checked_codes)} 种 / 共 {len(self._cards)} 种")

    # ================================================================
    # 对外接口（保持跟旧版一致，workbench_page / print_job_page 不用改调用方式）
    # ================================================================

    def get_checked_codes(self) -> List[str]:
        if not self._cards:
            return list(self._checked_codes)
        return [code for code, card in self._cards.items() if card.is_checked()]
