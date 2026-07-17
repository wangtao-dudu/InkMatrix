# -*- coding: utf-8 -*-
"""
receipt_print.py  (UI层 - 进出货单据打印)
================================================
"系统上直接打印出来"——用Qt原生的 QPrinter + QPrintPreviewDialog 实现，
不是导出一个文件让你自己去打印，是打开系统打印预览窗口，里面就有
"打印"按钮，直接选打印机送出去。

────────────────────────────────────────────────────────────────
【问题4修复】为什么之前打出来字小得看不清、内容只占纸的一小角
────────────────────────────────────────────────────────────────
旧代码是这么写的：

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)   # ← 1200 DPI
    doc = QTextDocument()
    doc.setHtml(html)                                          # ← HTML里字号用 px
    doc.print(printer)                                         # ← 直接怼给打印机

问题出在这两句的组合上。HighResolution 模式下打印设备是 1200 DPI，而
HTML/CSS 里写的 `font-size: 13px` 是【设备像素】——在 96 DPI 的屏幕上，
13px 约等于 3.4 毫米，看着正常；可到了 1200 DPI 的打印机上，同样的
13px 只有 0.27 毫米，肉眼几乎看不见。整个表格也因此缩成纸角上小小的
一团。这就是截图里看到的现象。

正确做法（本文件采用的方案）：
    不要让 QTextDocument 直接面对 1200 DPI 的设备。而是——
        1. 先把文档按【96 DPI 逻辑画布】排版（此时 px 的含义跟屏幕一致，
           15px 就是正常的 15px，排版结果符合预期）
        2. 再用 QPainter.scale(dpi/96) 把这张逻辑画布整体放大到打印机的
           真实分辨率上去画

    这样字号、行高、表格线宽全部按比例等比放大，1200 DPI 打印机上打出来
    的字，物理尺寸跟 96 DPI 屏幕上看到的完全一致，而且因为是矢量缩放，
    边缘依然锐利，不会糊。

    这套"逻辑画布 + QPainter.scale"的思路，就是之前修工单打印时用过的
    那一套，这次把进销存单据也统一到同一个方案上。
"""

from typing import List, Dict

from PyQt6.QtCore import QMarginsF, QSizeF, QRectF
from PyQt6.QtGui import QTextDocument, QPageLayout, QPageSize, QPainter
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog

# 逻辑画布的 DPI。96 是 Windows/Qt 的标准屏幕 DPI，也就是"CSS px 的家"。
# 所有 HTML 里的 px 数值都按这个基准排版，最后再整体缩放到打印机分辨率。
LOGICAL_DPI = 96.0


def _build_receipt_html(company_info: Dict, doc_type: str, records: List[Dict]) -> str:
    company_name = (company_info or {}).get("company_name") or "（未设置公司名称，请在【公司信息】页面填写）"
    address = (company_info or {}).get("address", "")
    phone = (company_info or {}).get("contact_phone", "")

    first = records[0]
    date = first.get("date", "")
    customer = first.get("customer", "")
    receiving_unit = first.get("receiving_unit", "") or customer
    handler = first.get("handler", "")
    vehicle_plate = first.get("vehicle_plate", "")
    order_no = first.get("order_no", "")

    rows_html = ""
    total_amount = 0.0
    total_qty = 0.0
    has_notes = any((r.get("notes") or "").strip() for r in records)
    for r in records:
        qty = r.get("quantity", 0) or 0
        price = r.get("unit_price", 0) or 0
        amount = r.get("amount", qty * price) or (qty * price)
        total_qty += qty
        total_amount += amount
        notes_cell = ""
        if has_notes:
            notes_cell = f'<td style="padding:8px 6px; font-size:13px;">{(r.get("notes") or "").strip() or "-"}</td>'
        rows_html += f"""
        <tr>
            <td style="padding:8px 6px;">{r.get('product_name', '')}</td>
            <td align="center" style="padding:8px 6px;">{r.get('print_count', '') or '-'}</td>
            <td align="center" style="padding:8px 6px;">{qty:g}</td>
            <td align="center" style="padding:8px 6px;">{price:.2f}</td>
            <td align="center" style="padding:8px 6px;">{amount:.2f}</td>
            <td align="center" style="padding:8px 6px;">{r.get('packaging', '') or '-'}</td>
            <td align="center" style="padding:8px 6px;">{r.get('scrape_count', '') or '-'}</td>
            {notes_cell}
        </tr>"""

    accent = "#0d9488" if doc_type == "进货单" else "#2563eb"
    notes_th = '<th style="padding:10px 6px;">备注</th>' if has_notes else ""
    notes_foot = '<td style="padding:10px 6px;"></td>' if has_notes else ""

    # 字号整体调大：单据是要给仓管、司机、客户在现场核对的，甚至可能是在
    # 光线不好的库房里看，字太小就是不能用。正文/表格 15px、标题 30px，是
    # 在 A4 上兼顾"信息装得下"和"一眼能看清"的平衡点。
    return f"""
    <html>
    <body style="font-family: 'Microsoft YaHei', 'SimSun', sans-serif; font-size: 15px; color:#1e293b;">
        <div style="font-size:22px; font-weight:bold; margin-bottom:4px;">{company_name}</div>
        <div style="color:#475569; font-size:13px; margin-bottom:8px;">{address}　电话：{phone}</div>
        <hr style="border:none; border-top:2px solid #334155;">
        <div style="font-size:30px; font-weight:bold; color:{accent}; text-align:center;
                    letter-spacing:8px; margin:14px 0 18px 0;">{doc_type}</div>

        <table width="100%" cellpadding="5" style="margin-bottom:14px; font-size:15px;">
            <tr>
                <td width="50%">日期：{date}</td>
                <td width="50%">单号：{order_no or '-'}</td>
            </tr>
            <tr>
                <td>客户：{customer}</td>
                <td>收货单位：{receiving_unit}</td>
            </tr>
            <tr>
                <td>经手人：{handler or '-'}</td>
                <td>车牌号：{vehicle_plate or '-'}</td>
            </tr>
        </table>

        <table width="100%" border="1" cellspacing="0" cellpadding="8"
               style="border-collapse:collapse; border-color:#94a3b8; font-size:15px;">
            <tr style="background-color:{accent}; color:white; font-weight:bold;">
                <th style="padding:10px 6px;">产品名称</th>
                <th style="padding:10px 6px;">印次</th>
                <th style="padding:10px 6px;">数量</th>
                <th style="padding:10px 6px;">单价(元)</th>
                <th style="padding:10px 6px;">金额(元)</th>
                <th style="padding:10px 6px;">包装</th>
                <th style="padding:10px 6px;">刮数</th>
                {notes_th}
            </tr>
            {rows_html}
            <tr style="font-weight:bold; background-color:#f1f5f9;">
                <td align="right" style="padding:10px 6px;">合计</td>
                <td style="padding:10px 6px;"></td>
                <td align="center" style="padding:10px 6px;">{total_qty:g}</td>
                <td style="padding:10px 6px;"></td>
                <td align="center" style="padding:10px 6px;">{total_amount:.2f}</td>
                <td style="padding:10px 6px;"></td>
                <td style="padding:10px 6px;"></td>
                {notes_foot}
            </tr>
        </table>

        <div style="height:50px;"></div>
        <table width="100%" cellpadding="6" style="font-size:15px;">
            <tr>
                <td>经手人签字：____________</td>
                <td>送货人签字：____________</td>
                <td>收货人签字：____________</td>
            </tr>
        </table>
    </body>
    </html>
    """


def render_html_to_printer(printer: QPrinter, html: str):
    """
    把 HTML 按 96 DPI 逻辑画布排版，再等比放大画到打印机上。

    这是本文件的核心，也是【问题4】的修复所在。逐步说明：

        1. 从 printer 拿到真实分辨率（HighResolution 下通常是 1200 DPI）
           和可打印区域的尺寸。
        2. 算出缩放比 scale = 真实DPI / 96。
        3. 把可打印区域的宽高【除以 scale】，换算成"这张纸在 96 DPI 逻辑
           坐标系下有多大"，用这个尺寸去给 QTextDocument 排版。这样文档
           里的 15px 字号，在逻辑坐标系里就是货真价实的 15px。
        4. 最后 painter.scale(scale, scale)，把整张逻辑画布等比放大到
           打印机的物理分辨率上——字号、线宽、间距全部一起放大，物理
           尺寸正确，且因为是矢量缩放所以依然清晰。

    多页处理：文档排完版如果超过一页，用 painter.translate 把画布往上
    推一页的高度，配合 drawContents 的裁剪矩形，循环画完所有页。
    """
    dpi = printer.resolution()        # 打印机真实分辨率，HighResolution 下一般 1200
    scale = dpi / LOGICAL_DPI         # 例如 1200/96 = 12.5

    page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
    page_w_logical = page_rect.width() / scale
    page_h_logical = page_rect.height() / scale

    doc = QTextDocument()
    doc.setDocumentMargin(0)  # 页边距已由 QPrinter.setPageMargins 负责，这里不要重复留
    doc.setHtml(html)
    doc.setPageSize(QSizeF(page_w_logical, page_h_logical))

    painter = QPainter(printer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # ★ 关键一行：把 96 DPI 的逻辑画布整体放大到打印机真实分辨率
    painter.scale(scale, scale)

    total_height = doc.size().height()
    page_count = max(1, int(total_height / page_h_logical) + (1 if total_height % page_h_logical else 0))

    for page_index in range(page_count):
        if page_index > 0:
            printer.newPage()
        painter.save()
        clip_top = page_h_logical * page_index
        # 把画布往上推 page_index 页，露出当前这一页要画的那一段
        painter.translate(0, -clip_top)
        doc.drawContents(painter, QRectF(0, clip_top, page_w_logical, page_h_logical))
        painter.restore()

    painter.end()


def print_receipt(parent, company_info: Dict, doc_type: str, records: List[Dict]):
    """
    弹出Qt原生打印预览窗口（里面自带"打印"按钮，直接选打印机送出去）。

    Args:
        doc_type: "进货单" 或 "出货单"
        records: 要打印在同一张单据上的记录（通常是同一客户+同一类型+
                 同一单号的多条明细，比如一次送货里有好几种产品）
    """
    if not records:
        return

    html = _build_receipt_html(company_info, doc_type, records)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)

    preview = QPrintPreviewDialog(printer, parent)
    preview.setWindowTitle(f"打印预览 - {doc_type}")
    # 预览窗口开大一点：默认那个小窗口 + 38% 缩放，是"看不清"的第二个原因
    preview.resize(1000, 800)

    def _render(p: QPrinter):
        render_html_to_printer(p, html)

    preview.paintRequested.connect(_render)
    preview.exec()
