# -*- coding: utf-8 -*-
"""
svg_import.py  (CORE层 - SVG矢量颜色解析)
================================================
"上传SVG矢量图，自动识别里面所有颜色并计算配比" 功能的核心解析逻辑。

跟"效果图取色"（点像素猜颜色）的本质区别：
    - 效果图取色：读的是渲染后的像素颜色，会受抗锯齿/压缩/光照影响，
      是"看图猜色"。
    - 本模块：直接解析SVG文件XML里每个图形写的 fill 属性精确数值
      （比如 fill="#1E3A8A"），是"读数值"，没有渲染损失。

只依赖 Python 标准库 xml.etree，不依赖 PyQt/UI，符合 CORE 层
"只做纯计算，不感知UI"的原则。
"""

import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional

from core_layer.color_convert import srgb_to_lab

_SVG_SHAPE_TAGS = {"rect", "circle", "ellipse", "polygon", "polyline", "path", "text", "tspan"}

# CSS/SVG 命名颜色的常用子集（覆盖率已经很高；更完整的名字很少在设计文件里出现）
_NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "orange": (255, 165, 0), "purple": (128, 0, 128),
    "brown": (165, 42, 42), "pink": (255, 192, 203), "navy": (0, 0, 128),
    "teal": (0, 128, 128), "lime": (0, 255, 0), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "silver": (192, 192, 192), "gold": (255, 215, 0),
}

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_RE = re.compile(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_RGB_PERCENT_RE = re.compile(r"rgb\s*\(\s*([\d.]+)%\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)")
_STYLE_FILL_RE = re.compile(r"fill\s*:\s*([^;]+)")


def _parse_color_string(value: str) -> Optional[Tuple[int, int, int]]:
    """把 fill 属性里的各种颜色写法（#hex / rgb() / 命名色）统一解析成 (r,g,b)。"""
    if not value:
        return None
    value = value.strip()
    if value in ("none", "transparent", ""):
        return None

    m = _HEX_RE.match(value)
    if m:
        hexpart = m.group(1)
        if len(hexpart) == 3:
            hexpart = "".join(c * 2 for c in hexpart)
        r = int(hexpart[0:2], 16)
        g = int(hexpart[2:4], 16)
        b = int(hexpart[4:6], 16)
        return (r, g, b)

    m = _RGB_RE.match(value)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _RGB_PERCENT_RE.match(value)
    if m:
        r = round(float(m.group(1)) / 100.0 * 255)
        g = round(float(m.group(2)) / 100.0 * 255)
        b = round(float(m.group(3)) / 100.0 * 255)
        return (r, g, b)

    lower = value.lower()
    if lower in _NAMED_COLORS:
        return _NAMED_COLORS[lower]

    return None


def _extract_fill(elem) -> Optional[str]:
    """从元素的 fill 属性或 style 属性里提取原始颜色字符串（未解析前）。"""
    fill_attr = elem.get("fill")
    if fill_attr:
        return fill_attr
    style_attr = elem.get("style")
    if style_attr:
        m = _STYLE_FILL_RE.search(style_attr)
        if m:
            return m.group(1).strip()
    return None


def _estimate_area(elem, tag: str) -> float:
    """
    估算一个图形元素覆盖的面积（用于区分"大面积背景色块" vs "很多小碎片
    图案"——按"出现次数"排序会让背景色被大量小图案盖过去，按面积排序
    才能正确识别出真正的背景色）。

    对 rect/circle/ellipse 用精确几何公式；对 path/polygon/polyline 用
    坐标点的包围盒面积做近似（不是精确的路径面积，但足够用来做"这块
    大致有多大"的排序判断）。
    """
    try:
        if tag == "rect":
            w = float(elem.get("width", 0) or 0)
            h = float(elem.get("height", 0) or 0)
            return w * h
        if tag == "circle":
            r = float(elem.get("r", 0) or 0)
            return 3.14159 * r * r
        if tag == "ellipse":
            rx = float(elem.get("rx", 0) or 0)
            ry = float(elem.get("ry", 0) or 0)
            return 3.14159 * rx * ry
        if tag in ("polygon", "polyline"):
            points_str = elem.get("points", "") or ""
            coords = [float(v) for v in re.split(r"[\s,]+", points_str.strip()) if v]
            xs, ys = coords[0::2], coords[1::2]
            if xs and ys:
                return (max(xs) - min(xs)) * (max(ys) - min(ys))
        if tag == "path":
            d = elem.get("d", "") or ""
            nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", d)]
            xs, ys = nums[0::2], nums[1::2]
            if len(xs) >= 2 and len(ys) >= 2:
                return (max(xs) - min(xs)) * (max(ys) - min(ys))
    except (ValueError, IndexError, ZeroDivisionError):
        pass
    return 0.0


def parse_svg_fill_colors(svg_path: str) -> List[Dict]:
    """
    解析SVG文件，提取所有图形元素使用到的、互不相同的填充颜色。

    Returns:
        按估算覆盖面积从大到小排序的列表（面积大的更可能是背景色/主色，
        面积小但数量多的通常是文字笔画、图案细节），每项：
        {
            "hex": "#1e3a8a",
            "rgb": (30, 58, 138),
            "lab": (L, a, b),
            "count": 3,          # 有几个图形用了这个颜色
            "area": 12345.6,     # 估算总覆盖面积（同一坐标系单位，仅供相对排序参考）
            "sample_ids": [...]  # 用到这个颜色的元素id（若有），便于溯源
        }

    说明：
        - 跳过 fill="none" / 无填充 / 渐变引用（url(#xxx)）等无法给出单一
          精确颜色的情况——渐变色本身就不是一个单一颜色，需要人工确认。
        - <defs> 内部的元素（通常是被引用的模板，不直接可见）会被跳过。
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()

    color_groups: Dict[str, Dict] = {}

    def walk(elem, in_defs: bool):
        tag = elem.tag.split("}")[-1]  # 去掉命名空间前缀
        is_defs = in_defs or tag == "defs"

        if tag in _SVG_SHAPE_TAGS and not is_defs:
            raw = _extract_fill(elem)
            if raw and not raw.strip().startswith("url("):
                rgb = _parse_color_string(raw)
                if rgb is not None:
                    hex_code = "#%02x%02x%02x" % rgb
                    if hex_code not in color_groups:
                        color_groups[hex_code] = {
                            "hex": hex_code,
                            "rgb": rgb,
                            "lab": srgb_to_lab(*rgb),
                            "count": 0,
                            "area": 0.0,
                            "sample_ids": [],
                        }
                    color_groups[hex_code]["count"] += 1
                    color_groups[hex_code]["area"] += _estimate_area(elem, tag)
                    elem_id = elem.get("id")
                    if elem_id and elem_id not in color_groups[hex_code]["sample_ids"]:
                        color_groups[hex_code]["sample_ids"].append(elem_id)

        for child in elem:
            walk(child, is_defs)

    walk(root, in_defs=False)

    results = list(color_groups.values())
    results.sort(key=lambda x: -x["area"])
    return results
