# -*- coding: utf-8 -*-
"""
inventory_page.py  (UI层 - 进销存管理页面)
================================================
参照客户原有《XX月产量表》Excel模板的字段习惯（日期/客户/产品名称/
印次/数量/单价/金额/包装/单号/刮数/备注），新增"类型"(进货/出货)
字段，进出货后库存结余自动增减，不需要人工再拿计算器/Excel公式对。

⚠️ 边界说明：这是【进销存记录】模块，跟【生产追踪】页是两回事——
    进销存是文员统计的"这批货进了多少、出了多少"，生产追踪是丝印
    师傅记录的"机台在干什么活"，两者角色、时间点都不同，故意分开
    成两个独立页面，不混在一起。
"""

import datetime
from typing import List, Dict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QDoubleSpinBox, QDateEdit, QTextEdit, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea
)
from PyQt6.QtCore import QDate

from ui_layer.widgets import Card, PrimaryButton, GhostButton, DangerButton, StatCard, Badge, ResponsiveRow
from ui_layer.receipt_print import print_receipt

_STATUS_STYLE = {
    "已出完":   {"bg": "#f0fdf4", "fg": "#16a34a"},
    "部分未出": {"bg": "#fef9c3", "fg": "#b45309"},
    "全部未出": {"bg": "#fee2e2", "fg": "#b91c1c"},
}


def _shipment_status(in_qty: float, out_qty: float) -> str:
    if out_qty >= in_qty and in_qty > 0:
        return "已出完"
    if out_qty > 0:
        return "部分未出"
    return "全部未出"


class InventoryPage(QWidget):

    # 进销存数据一变，财务页的应收账款就得跟着重算（数量/单价都可能变了）
    inventory_changed = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, inventory_repo, company_repo=None, finance_repo=None, parent=None):
        super().__init__(parent)
        self.inventory_repo = inventory_repo
        self.company_repo = company_repo
        # 删除进货记录时要检查财务那边有没有挂着收款——已收过钱的账不能悄悄删掉
        self.finance_repo = finance_repo
        self._editing_id = None
        self._editing_created_at = ""
        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("进销存管理")
        title.setObjectName("PageTitle")
        subtitle = QLabel("进货/出货记录（文员统计） + 库存结余总览，一眼看出哪些客户的货已出、哪些还压在仓库")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)
        self.stat_in = StatCard("0", "累计入库件数", accent_hex="#2563eb")
        self.stat_out = StatCard("0", "累计出库件数", accent_hex="#0d9488")
        self.stat_balance = StatCard("0", "当前库存结余", accent_hex="#d97706")
        self.stat_pending = StatCard("0", "未出完的客户/产品数", accent_hex="#dc2626")
        for card in (self.stat_in, self.stat_out, self.stat_balance, self.stat_pending):
            stat_row.addWidget(card)
        stat_row.addStretch(1)
        root.addLayout(stat_row)

        body = ResponsiveRow(breakpoint=900)
        body.add_panel(self._wrap_scrollable(self._build_new_record_card()), 1)
        body.add_panel(self._wrap_scrollable(self._build_stock_overview_card()), 1)
        root.addWidget(body, 1)

        root.addWidget(self._build_history_card(), 1)

    @staticmethod
    def _wrap_scrollable(inner: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(inner)
        return scroll

    # ---------------- ① 新增进出货记录 ----------------

    def _build_new_record_card(self) -> Card:
        card = Card("① 新增进出货记录")
        lay = card.body_layout

        lay.addWidget(QLabel("类型："))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["进货", "出货"])
        lay.addWidget(self.type_combo)

        lay.addWidget(QLabel("日期："))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        lay.addWidget(self.date_edit)

        lay.addWidget(QLabel("客户："))
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("例如：客户A")
        lay.addWidget(self.customer_edit)

        lay.addWidget(QLabel("产品名称："))
        self.product_edit = QLineEdit()
        self.product_edit.setPlaceholderText("例如：100ml白瓶套色")
        lay.addWidget(self.product_edit)

        row1 = QHBoxLayout()
        qty_col = QVBoxLayout()
        qty_col.addWidget(QLabel("数量："))
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0, 10000000)
        self.qty_spin.setDecimals(0)
        self.qty_spin.valueChanged.connect(self._update_amount_preview)
        qty_col.addWidget(self.qty_spin)
        price_col = QVBoxLayout()
        price_col.addWidget(QLabel("单价(元)："))
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1000000)
        self.price_spin.setDecimals(2)
        self.price_spin.valueChanged.connect(self._update_amount_preview)
        price_col.addWidget(self.price_spin)
        row1.addLayout(qty_col)
        row1.addLayout(price_col)
        lay.addLayout(row1)

        self.amount_label = QLabel("金额：¥0.00")
        self.amount_label.setStyleSheet("color:#0f172a; font-weight:600;")
        lay.addWidget(self.amount_label)

        row2 = QHBoxLayout()
        print_col = QVBoxLayout()
        print_col.addWidget(QLabel("印次(选填)："))
        self.print_count_spin = QDoubleSpinBox()
        self.print_count_spin.setRange(0, 100)
        self.print_count_spin.setDecimals(0)
        print_col.addWidget(self.print_count_spin)
        scrape_col = QVBoxLayout()
        scrape_col.addWidget(QLabel("刮数(选填)："))
        self.scrape_count_spin = QDoubleSpinBox()
        self.scrape_count_spin.setRange(0, 100)
        self.scrape_count_spin.setDecimals(0)
        scrape_col.addWidget(self.scrape_count_spin)
        row2.addLayout(print_col)
        row2.addLayout(scrape_col)
        lay.addLayout(row2)

        lay.addWidget(QLabel("包装(选填)："))
        self.packaging_edit = QLineEdit()
        self.packaging_edit.setPlaceholderText("例如：纸箱/50个")
        lay.addWidget(self.packaging_edit)

        lay.addWidget(QLabel("单号(选填)："))
        self.order_no_edit = QLineEdit()
        lay.addWidget(self.order_no_edit)

        lay.addWidget(QLabel("收货单位(选填，不填默认用客户名称，打印单据用)："))
        self.receiving_unit_edit = QLineEdit()
        self.receiving_unit_edit.setPlaceholderText("例如：客户A仓库/客户A收货部")
        lay.addWidget(self.receiving_unit_edit)

        row3 = QHBoxLayout()
        handler_col = QVBoxLayout()
        handler_col.addWidget(QLabel("经手人(选填)："))
        self.handler_edit = QLineEdit()
        handler_col.addWidget(self.handler_edit)
        plate_col = QVBoxLayout()
        plate_col.addWidget(QLabel("车牌号(选填)："))
        self.vehicle_plate_edit = QLineEdit()
        self.vehicle_plate_edit.setPlaceholderText("例如：粤B12345")
        plate_col.addWidget(self.vehicle_plate_edit)
        row3.addLayout(handler_col)
        row3.addLayout(plate_col)
        lay.addLayout(row3)

        lay.addWidget(QLabel("备注："))
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(60)
        lay.addWidget(self.notes_edit)

        save_btn = PrimaryButton("💾 保存记录")
        save_btn.clicked.connect(self._on_save_record)
        self.save_btn = save_btn

        # 编辑模式横幅（平时隐藏）
        self.edit_banner = QLabel("")
        self.edit_banner.setWordWrap(True)
        self.edit_banner.setStyleSheet(
            "color:#92400e; background:#fffbeb; border:1px solid #fde68a; "
            "border-radius:8px; padding:9px 12px; font-size:12px;"
        )
        self.edit_banner.setVisible(False)
        lay.addWidget(self.edit_banner)

        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn, 1)
        self.cancel_edit_btn = GhostButton("✖ 取消编辑")
        self.cancel_edit_btn.clicked.connect(self._on_cancel_edit)
        self.cancel_edit_btn.setVisible(False)
        btn_row.addWidget(self.cancel_edit_btn)
        lay.addLayout(btn_row)

        return card

    def _update_amount_preview(self):
        amount = self.qty_spin.value() * self.price_spin.value()
        self.amount_label.setText(f"金额：¥{amount:,.2f}")

    def _on_save_record(self):
        customer = self.customer_edit.text().strip()
        product = self.product_edit.text().strip()
        if not customer or not product:
            QMessageBox.warning(self, "提示", "请填写客户与产品名称。")
            return
        if self.qty_spin.value() <= 0:
            QMessageBox.warning(self, "提示", "数量需要大于0。")
            return

        now = datetime.datetime.now()

        # 编辑模式：沿用原来的 id 和 created_at。
        #
        # 为什么必须保留 id：财务模块的应收账款是用 inventory_id 挂在这条记录
        # 上的。如果编辑时换一个新 id，那条已经记了收款的账就会瞬间"失联"——
        # 客户明明付过钱，系统里却变成一笔全新的、未付款的账。所以改记录
        # 绝不能是"删了重建"。
        editing_id = getattr(self, "_editing_id", None)
        record_id = editing_id or f"INV-{now.strftime('%Y%m%d%H%M%S%f')}"
        created = self._editing_created_at if editing_id else now.strftime("%Y-%m-%d %H:%M")

        record = {
            "id": record_id,
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "customer": customer,
            "product_name": product,
            "movement_type": self.type_combo.currentText(),
            "print_count": self.print_count_spin.value(),
            "quantity": self.qty_spin.value(),
            "unit_price": self.price_spin.value(),
            "amount": round(self.qty_spin.value() * self.price_spin.value(), 2),
            "packaging": self.packaging_edit.text().strip(),
            "order_no": self.order_no_edit.text().strip(),
            "scrape_count": self.scrape_count_spin.value(),
            "receiving_unit": self.receiving_unit_edit.text().strip(),
            "handler": self.handler_edit.text().strip(),
            "vehicle_plate": self.vehicle_plate_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
            "created_at": created,
        }
        self.inventory_repo.upsert(record)

        if editing_id:
            QMessageBox.information(
                self, "已更新",
                f"记录已更新，库存结余已重新计算。\n"
                f"（如果这条记录在【财务管理】里已经记过收款，收款流水会原样保留，"
                f"只是应收金额按新的数量重新算。）"
            )
        else:
            QMessageBox.information(
                self, "已保存",
                f"【{self.type_combo.currentText()}】记录已保存，库存结余已自动更新。"
            )
        self._exit_edit_mode()
        self.inventory_changed.emit()
        self.customer_edit.clear()
        self.product_edit.clear()
        self.qty_spin.setValue(0)
        self.price_spin.setValue(0)
        self.packaging_edit.clear()
        self.order_no_edit.clear()
        self.receiving_unit_edit.clear()
        self.handler_edit.clear()
        self.vehicle_plate_edit.clear()
        self.notes_edit.clear()
        self.refresh_all()

    def _enter_edit_mode(self, record: dict):
        """把一条已有记录灌回上面的表单，进入编辑状态。"""
        self._editing_id = record["id"]
        self._editing_created_at = record.get("created_at", "")

        self.date_edit.setDate(QDate.fromString(record.get("date", ""), "yyyy-MM-dd"))
        self.customer_edit.setText(record.get("customer", ""))
        self.product_edit.setText(record.get("product_name", ""))
        idx = self.type_combo.findText(record.get("movement_type", "进货"))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.print_count_spin.setValue(record.get("print_count", 0) or 0)
        self.qty_spin.setValue(record.get("quantity", 0) or 0)
        self.price_spin.setValue(record.get("unit_price", 0) or 0)
        self.packaging_edit.setText(record.get("packaging", "") or "")
        self.order_no_edit.setText(record.get("order_no", "") or "")
        self.scrape_count_spin.setValue(record.get("scrape_count", 0) or 0)
        self.receiving_unit_edit.setText(record.get("receiving_unit", "") or "")
        self.handler_edit.setText(record.get("handler", "") or "")
        self.vehicle_plate_edit.setText(record.get("vehicle_plate", "") or "")
        self.notes_edit.setPlainText(record.get("notes", "") or "")

        self.save_btn.setText("💾 保存修改")
        self.edit_banner.setText(
            f"✏️ 正在编辑：{record.get('date','')}　{record.get('customer','')}　"
            f"{record.get('product_name','')}　—— 改完点【保存修改】"
        )
        self.edit_banner.setVisible(True)
        self.cancel_edit_btn.setVisible(True)

    def _exit_edit_mode(self):
        self._editing_id = None
        self._editing_created_at = ""
        self.save_btn.setText("💾 保存记录")
        self.edit_banner.setVisible(False)
        self.cancel_edit_btn.setVisible(False)

    def _on_cancel_edit(self):
        self._exit_edit_mode()
        self.customer_edit.clear()
        self.product_edit.clear()
        self.qty_spin.setValue(0)
        self.price_spin.setValue(0)
        self.packaging_edit.clear()
        self.order_no_edit.clear()
        self.receiving_unit_edit.clear()
        self.handler_edit.clear()
        self.vehicle_plate_edit.clear()
        self.notes_edit.clear()

    def _on_edit_record(self):
        """
        修改一条录错的进出货记录。

        以前只能删掉重录，那样会出两个问题：
          1. 记录的 id 变了，财务模块里挂在旧 id 上的收款流水会瞬间失联——
             客户明明付过钱，系统里却变成一笔全新的未付款账
          2. created_at 丢了，查不出这条是什么时候录进来的
        所以改记录必须是"原地改"，不能是"删了重建"。
        """
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在下面的表格里点击选中要修改的那条记录。")
            return
        record_id = self.history_table.item(row, 3).data(Qt.ItemDataRole.UserRole)
        record = self.inventory_repo.get_by_id(record_id)
        if record is None:
            QMessageBox.warning(self, "提示", "这条记录已不存在，请刷新后重试。")
            return
        self._enter_edit_mode(record)
        self.status_message.emit("已载入到上方表单，改完点【保存修改】。")

    def _on_print_by_order_no(self):
        """
        按单号打印 —— 同一次送货就该是一张单。

        以前只能在表格里按住 Ctrl 一行一行多选，客户一次送来五款产品就得
        准确点中五行，漏一行少一行都不知道。现在选中任意一行，系统自动把
        同一单号、同一客户、同一类型的所有产品归集到一张单上。
        """
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中这次送货里的任意一条记录。")
            return
        record_id = self.history_table.item(row, 3).data(Qt.ItemDataRole.UserRole)
        anchor_rec = self.inventory_repo.get_by_id(record_id)
        if anchor_rec is None:
            return

        order_no = (anchor_rec.get("order_no") or "").strip()
        if not order_no:
            QMessageBox.information(
                self, "这条记录没有单号",
                "按单号打印需要记录上填了【单号】。\n\n"
                "这条记录的单号是空的，所以系统没法判断哪几款产品属于同一次送货。\n"
                "你可以：\n"
                "  · 用【✏️ 修改选中】给这次送货的每条记录都补上同一个单号，或者\n"
                "  · 在表格里按住 Ctrl 手动多选，再点【🖨 打印选中】"
            )
            return

        group = [
            r for r in self.inventory_repo.load_all()
            if (r.get("order_no") or "").strip() == order_no
            and r.get("customer") == anchor_rec.get("customer")
            and r.get("movement_type") == anchor_rec.get("movement_type")
        ]
        if not group:
            return

        doc_type = "进货单" if anchor_rec.get("movement_type") == "进货" else "出货单"
        company_info = self.company_repo.load() if self.company_repo else {}
        self.status_message.emit(f"单号 {order_no} 下共 {len(group)} 款产品，已归集到一张{doc_type}。")
        print_receipt(self, company_info, doc_type, group)

    # ---------------- ② 库存结余总览（一眼看出已出/未出） ----------------

    def _build_stock_overview_card(self) -> Card:
        card = Card("② 库存结余总览（按客户+产品汇总）")
        lay = card.body_layout

        self.overview_table = QTableWidget(0, 5)
        self.overview_table.setHorizontalHeaderLabels(["客户", "产品名称", "累计入库", "累计出库", "结余/状态"])
        self.overview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.overview_table.verticalHeader().setDefaultSectionSize(34)
        lay.addWidget(self.overview_table, 1)

        legend = QHBoxLayout()
        for status in ("已出完", "部分未出", "全部未出"):
            style = _STATUS_STYLE[status]
            badge = Badge(status, bg_hex=style["fg"])
            legend.addWidget(badge)
        legend.addStretch(1)
        lay.addLayout(legend)

        return card

    def _refresh_stock_overview(self):
        summary = self.inventory_repo.stock_summary()
        self.overview_table.setRowCount(len(summary))

        total_in = sum(g["in_qty"] for g in summary)
        total_out = sum(g["out_qty"] for g in summary)
        total_balance = sum(g["balance"] for g in summary)
        pending_count = sum(1 for g in summary if _shipment_status(g["in_qty"], g["out_qty"]) != "已出完")
        self.stat_in.set_value(f"{total_in:g}")
        self.stat_out.set_value(f"{total_out:g}")
        self.stat_balance.set_value(f"{total_balance:g}")
        self.stat_pending.set_value(str(pending_count))

        for row, g in enumerate(summary):
            status = _shipment_status(g["in_qty"], g["out_qty"])
            style = _STATUS_STYLE[status]

            customer_item = QTableWidgetItem(g["customer"])
            product_item = QTableWidgetItem(g["product_name"])
            in_item = QTableWidgetItem(f"{g['in_qty']:g}")
            out_item = QTableWidgetItem(f"{g['out_qty']:g}")
            balance_item = QTableWidgetItem(f"{g['balance']:g}  {status}")

            for item in (customer_item, product_item, in_item, out_item, balance_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            balance_item.setBackground(QColor(style["bg"]))
            balance_item.setForeground(QColor(style["fg"]))
            balance_item.setFont(self._bold_font())

            self.overview_table.setItem(row, 0, customer_item)
            self.overview_table.setItem(row, 1, product_item)
            self.overview_table.setItem(row, 2, in_item)
            self.overview_table.setItem(row, 3, out_item)
            self.overview_table.setItem(row, 4, balance_item)

    @staticmethod
    def _bold_font():
        from PyQt6.QtGui import QFont
        f = QFont()
        f.setBold(True)
        return f

    # ---------------- ③ 进出货历史（可搜索/导出） ----------------

    def _build_history_card(self) -> Card:
        card = Card("③ 进出货记录历史")
        lay = card.body_layout

        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 按客户/产品名称/单号搜索…")
        self.search_edit.setMinimumWidth(260)
        self.search_edit.textChanged.connect(self._refresh_history_table)
        toolbar.addWidget(self.search_edit)

        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型", "进货", "出货"])
        self.type_filter.currentIndexChanged.connect(self._refresh_history_table)
        toolbar.addWidget(self.type_filter)
        toolbar.addStretch(1)

        export_btn = GhostButton("📊 导出Excel")
        export_btn.clicked.connect(self._on_export_excel)
        edit_btn = PrimaryButton("✏️ 修改选中")
        edit_btn.setToolTip("录错了可以直接改，不用删掉重录——删了重录会让财务那边已记的收款流水失联")
        edit_btn.clicked.connect(self._on_edit_record)
        order_print_btn = PrimaryButton("🖨️ 按单号打印")
        order_print_btn.setToolTip(
            "选中这次送货里的任意一条，自动把同一单号下的所有产品归集到一张单上。\n"
            "客户一次送来几款产品，就该打成一张单。"
        )
        order_print_btn.clicked.connect(self._on_print_by_order_no)
        print_btn = GhostButton("🖨️ 打印选中")
        print_btn.setToolTip("按住 Ctrl 手动多选若干行（需同一客户、同一类型）后打印")
        print_btn.clicked.connect(self._on_print_receipt)
        del_btn = DangerButton("－ 删除选中记录")
        del_btn.setMinimumHeight(34)
        del_btn.clicked.connect(self._on_delete_record)
        toolbar.addWidget(export_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(order_print_btn)
        toolbar.addWidget(print_btn)
        toolbar.addWidget(del_btn)
        lay.addLayout(toolbar)

        self.history_table = QTableWidget(0, 11)
        self.history_table.setHorizontalHeaderLabels(
            ["日期", "客户", "产品名称", "类型", "印次", "数量", "单价", "金额", "包装", "单号", "刮数"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.verticalHeader().setDefaultSectionSize(32)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        lay.addWidget(self.history_table, 1)

        hint = QLabel("💡 打印单据：先在下方表格勾选一条或多条记录（按住Ctrl/Shift可多选同一客户同一类型的多条产品明细，会合并成一张单据打印），再点【打印单据】。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94a3b8; font-size:11px;")
        lay.addWidget(hint)

        return card

    def _filtered_records(self) -> List[Dict]:
        records = self.inventory_repo.load_all()
        keyword = self.search_edit.text().strip().lower()
        type_filter = self.type_filter.currentText()
        if type_filter != "全部类型":
            records = [r for r in records if r.get("movement_type") == type_filter]
        if keyword:
            records = [
                r for r in records
                if keyword in (r.get("customer", "") or "").lower()
                or keyword in (r.get("product_name", "") or "").lower()
                or keyword in (r.get("order_no", "") or "").lower()
            ]
        return records

    def _refresh_history_table(self):
        records = self._filtered_records()
        self.history_table.setRowCount(len(records))
        for row, r in enumerate(records):
            type_text = r.get("movement_type", "")
            type_item = QTableWidgetItem(type_text)
            type_item.setData(Qt.ItemDataRole.UserRole, r["id"])
            type_item.setForeground(QColor("#2563eb" if type_text == "进货" else "#0d9488"))

            items = [
                QTableWidgetItem(r.get("date", "")),
                QTableWidgetItem(r.get("customer", "")),
                QTableWidgetItem(r.get("product_name", "")),
                type_item,
                QTableWidgetItem(f"{r.get('print_count', 0):g}" if r.get("print_count") else "-"),
                QTableWidgetItem(f"{r.get('quantity', 0):g}"),
                QTableWidgetItem(f"{r.get('unit_price', 0):.2f}"),
                QTableWidgetItem(f"{r.get('amount', 0):.2f}"),
                QTableWidgetItem(r.get("packaging", "") or "-"),
                QTableWidgetItem(r.get("order_no", "") or "-"),
                QTableWidgetItem(f"{r.get('scrape_count', 0):g}" if r.get("scrape_count") else "-"),
            ]
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.history_table.setItem(row, col, item)

    def _on_delete_record(self):
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中要删除的记录。")
            return
        record_id = self.history_table.item(row, 3).data(Qt.ItemDataRole.UserRole)

        # 这条记录在财务那边有没有挂着收款？有的话必须先说清楚。
        fin = self.finance_repo.get_by_inventory_id(record_id) if self.finance_repo else None
        paid = 0.0
        if fin:
            from dal_layer.data_manager import FinanceRepository
            paid = FinanceRepository.paid_total(fin)

        msg = "确定要删除这条进出货记录吗？删除后库存结余会重新计算。"
        if paid > 0.001:
            msg = (
                f"⚠️ 这条记录在【财务管理】里已经收过款了（累计 ¥{paid:.2f}）。\n\n"
                f"删除进货记录，等于这笔应收账款连同它的收款流水一起消失——"
                f"客户明明付过的钱，账上就查不到了。\n\n"
                f"如果只是录错了数量/单价，请点【✏️ 修改选中】改，不要删。\n\n"
                f"确定还是要删吗？"
            )
        elif fin:
            msg += "\n\n（这条记录在财务里设过单价/优惠，会一并删除。尚未收过款。）"

        box = QMessageBox(self)
        box.setWindowTitle("确认删除")
        box.setIcon(QMessageBox.Icon.Warning if paid > 0.001 else QMessageBox.Icon.Question)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        self.inventory_repo.delete(record_id)
        if self.finance_repo:
            self.finance_repo.delete_by_inventory_id(record_id)
        self._exit_edit_mode()
        self.refresh_all()
        self.inventory_changed.emit()

    def _on_print_receipt(self):
        selected_rows = sorted({idx.row() for idx in self.history_table.selectedIndexes()})
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先在表格中勾选要打印的一条或多条记录（同一客户、同一类型）。")
            return

        record_ids = [self.history_table.item(row, 3).data(Qt.ItemDataRole.UserRole) for row in selected_rows]
        records = [self.inventory_repo.get_by_id(rid) for rid in record_ids]
        records = [r for r in records if r is not None]
        if not records:
            QMessageBox.warning(self, "提示", "选中的记录未找到，请刷新后重试。")
            return

        movement_types = {r.get("movement_type") for r in records}
        customers = {r.get("customer") for r in records}
        if len(movement_types) > 1:
            QMessageBox.warning(self, "提示", "选中的记录里同时包含\"进货\"和\"出货\"，请只选同一种类型的记录再打印。")
            return
        if len(customers) > 1:
            QMessageBox.warning(self, "提示", "选中的记录属于不同客户，请只选同一个客户的记录再打印一张单据。")
            return

        doc_type = "进货单" if records[0].get("movement_type") == "进货" else "出货单"
        company_info = self.company_repo.load() if self.company_repo else {}
        print_receipt(self, company_info, doc_type, records)

    def _on_export_excel(self):
        records = self._filtered_records()
        if not records:
            QMessageBox.information(self, "提示", "没有可导出的记录。")
            return
        default_name = f"进出货记录_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "导出进出货记录Excel", default_name, "Excel文件 (*.xlsx)")
        if not path:
            return
        try:
            self._write_excel(records, path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"生成Excel文件时出错：{exc}")
            return
        QMessageBox.information(self, "导出成功", f"进出货记录已保存到：\n{path}")

    def _write_excel(self, records: List[Dict], path: str):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "进出货记录"

        headers = ["日期", "客户", "产品名称", "类型", "印次", "数量", "单价(元)", "金额(元)", "包装", "单号", "刮数", "备注"]
        header_fill = PatternFill(start_color="0D9488", end_color="0D9488", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col, text in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col, value=text)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        in_fill = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
        out_fill = PatternFill(start_color="CCFBF1", end_color="CCFBF1", fill_type="solid")

        for row_idx, r in enumerate(records, start=2):
            values = [
                r.get("date", ""), r.get("customer", ""), r.get("product_name", ""), r.get("movement_type", ""),
                r.get("print_count", 0), r.get("quantity", 0), r.get("unit_price", 0), r.get("amount", 0),
                r.get("packaging", ""), r.get("order_no", ""), r.get("scrape_count", 0), r.get("notes", ""),
            ]
            fill = in_fill if r.get("movement_type") == "进货" else out_fill
            for col, v in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=v)
                cell.fill = fill

        # 追加一张"库存结余总览"工作表
        ws2 = wb.create_sheet("库存结余总览")
        headers2 = ["客户", "产品名称", "累计入库", "累计出库", "结余", "状态"]
        for col, text in enumerate(headers2, start=1):
            cell = ws2.cell(row=1, column=col, value=text)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for row_idx, g in enumerate(self.inventory_repo.stock_summary(), start=2):
            status = _shipment_status(g["in_qty"], g["out_qty"])
            ws2.cell(row=row_idx, column=1, value=g["customer"])
            ws2.cell(row=row_idx, column=2, value=g["product_name"])
            ws2.cell(row=row_idx, column=3, value=g["in_qty"])
            ws2.cell(row=row_idx, column=4, value=g["out_qty"])
            ws2.cell(row=row_idx, column=5, value=g["balance"])
            status_cell = ws2.cell(row=row_idx, column=6, value=status)
            color_hex = {"已出完": "DCFCE7", "部分未出": "FEF9C3", "全部未出": "FEE2E2"}[status]
            status_cell.fill = PatternFill(start_color=color_hex, end_color=color_hex, fill_type="solid")

        for ws_ in (ws, ws2):
            for col in range(1, 13):
                ws_.column_dimensions[get_column_letter(col)].width = 16

        wb.save(path)

    # ---------------- 统一刷新 ----------------

    def refresh_all(self):
        self._refresh_stock_overview()
        self._refresh_history_table()
