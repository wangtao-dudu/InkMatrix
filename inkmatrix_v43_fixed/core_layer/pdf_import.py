# -*- coding: utf-8 -*-
"""
pdf_import.py  (CORE层 - PDF设计稿导入)
==========================================
"上传PDF设计稿，自动识别背景色和印刷色"功能的转换逻辑。

思路：PDF本身也是矢量格式，用 poppler 自带的 pdftocairo 工具把PDF页面
转成SVG（不是转成图片！），转换过程保留矢量图形的精确填充颜色数值，
然后直接复用已经验证过的 core_layer.svg_import.parse_svg_fill_colors
做精确解色——不是"渲染成图再猜色"，是"读文件里的精确数字"，这一点
跟效果图取色（像素采样）有本质区别，精度更高。

依赖：系统需要安装 poppler-utils（提供 pdftocairo 命令）。
"""

import os
import subprocess
import tempfile
from typing import List, Dict

from core_layer.svg_import import parse_svg_fill_colors


def get_pdf_page_count(pdf_path: str) -> int:
    """用 pdfinfo 读取PDF页数。找不到 pdfinfo 或解析失败时返回1（保守假设单页）。"""
    try:
        output = subprocess.run(
            ["pdfinfo", pdf_path], capture_output=True, text=True, timeout=15
        ).stdout
        for line in output.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except Exception:
        pass
    return 1


def convert_pdf_page_to_svg(pdf_path: str, page_number: int = 1) -> str:
    """
    把PDF的指定页转换成一个临时SVG文件，返回SVG文件路径。

    Raises:
        RuntimeError: 系统没有装 pdftocairo，或转换失败时抛出，
                      调用方应该捕获并给用户明确的提示。
    """
    tmp_dir = tempfile.mkdtemp(prefix="inkmatrix_pdf_")
    svg_path = os.path.join(tmp_dir, "page.svg")

    try:
        result = subprocess.run(
            ["pdftocairo", "-svg", "-f", str(page_number), "-l", str(page_number), pdf_path, svg_path],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "未找到 pdftocairo 命令。该功能依赖 poppler-utils 工具包，"
            "请先在系统上安装 poppler-utils（Windows可搜索'poppler for windows'下载，"
            "解压后把bin目录加入系统PATH环境变量）。"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("PDF转换超时，文件可能过大或过于复杂。")

    if result.returncode != 0 or not os.path.exists(svg_path):
        raise RuntimeError(f"PDF转换失败：{result.stderr.strip() or '未知错误'}")

    return svg_path


def extract_colors_from_pdf(pdf_path: str, page_number: int = 1) -> List[Dict]:
    """
    从PDF指定页里提取所有精确填充颜色（按估算覆盖面积从大到小排序，
    面积最大的通常就是背景色/底色，其余多为需要印刷的图案/文字颜色）。
    """
    svg_path = convert_pdf_page_to_svg(pdf_path, page_number)
    try:
        return parse_svg_fill_colors(svg_path)
    finally:
        try:
            os.remove(svg_path)
            os.rmdir(os.path.dirname(svg_path))
        except OSError:
            pass
