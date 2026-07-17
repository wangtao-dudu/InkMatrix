# -*- coding: utf-8 -*-
"""
ink_import.py  (CORE层 - 从Excel导入油墨数据)
===================================================
解决"我之前已经有一份油墨清单（Excel），想导进软件里，还要自动分类"
这个需求。

设计思路：
    1. 灵活识别表头——不强求你的Excel列名跟软件内部字段名一模一样，
       常见的中英文写法（编号/code、名称/name、颜色/颜色值/RGB/HEX、
       类别/category、库存/stock、单价/price）都能认出来。
    2. 自动分类：如果Excel里没写类别，就按名称关键字猜（含"白"的猜
       高遮盖白，含"光油/亮油/冲淡"的猜透明冲淡剂，其余归为彩色油墨）。
    3. 自动推导光谱：如果Excel里提供了颜色值（RGB或HEX），直接复用
       色相环那套"目标Lab反推K/S光谱"的算法，让导入的油墨真的带有
       对应色相，而不是随便给个默认灰阶浪费掉这个信息。没提供颜色值
       的，就用一个默认的中性灰占位，并在结果里标注"需要后续手动
       用色相环调色"，不会不声不响地当成灰色墨用。
"""

import re
from typing import List, Dict, Optional

from core_layer.color_convert import srgb_to_lab
from core_layer.ink_synthesis import synthesize_ink_spectrum

# 常见表头写法 -> 内部字段名 的映射（全部转小写后做包含匹配）
_HEADER_ALIASES = {
    "code": ["编号", "代码", "code", "货号", "型号", "序号"],
    "name": ["名称", "品名", "name", "油墨名称", "颜色名称", "专色"],
    "category": ["类别", "分类", "category", "种类"],
    "color": ["颜色", "颜色值", "color", "rgb", "hex", "色号", "颜色代码"],
    "stock": ["库存", "数量", "stock", "毫升", "ml"],
    "price": ["单价", "价格", "price", "单价(元)", "元/ml"],
    # ── Lab 三个分量 ──
    # 匹配要够宽：现实里的表头五花八门——"L*"、"L* (明度)"、"L值"、"Lightness"…
    # 但也要够窄：不能把"名称"里的字母误当成 L/a/b 列。所以用带星号/括号/
    # 中文注解的组合模式去认，纯粹一个孤零零的字母 "a" 反而不认（太容易误伤）。
    "lab_l": ["l*", "l值", "明度", "lightness", "l (", "l*("],
    "lab_a": ["a*", "a值", "红/绿", "红绿", "a (", "a*("],
    "lab_b": ["b*", "b值", "黄/蓝", "黄蓝", "b (", "b*("],
    # 允许色差：ΔE / △E / delta e / 色差 / 容差
    "tolerance": ["允许色差", "色差", "δe", "δe*ab", "deltae", "delta e", "de*ab",
                  "容差", "公差", "tolerance", "ΔE".lower(), "△e"],
}

_CATEGORY_KEYWORDS = {
    "white": ["白", "white", "钛白"],
    "varnish": ["光油", "亮油", "冲淡", "varnish", "调墨油"],
}


def _guess_column(headers: List[str], field: str) -> Optional[int]:
    aliases = _HEADER_ALIASES.get(field, [])
    for idx, h in enumerate(headers):
        h_norm = str(h).strip().lower()
        for alias in aliases:
            if alias.lower() in h_norm:
                return idx
    return None


def _guess_category(name: str, explicit: Optional[str]) -> str:
    if explicit:
        text = explicit.strip().lower()
        if "白" in text or "white" in text:
            return "white"
        if "光油" in text or "冲淡" in text or "varnish" in text:
            return "varnish"
        if "彩" in text or "color" in text:
            return "color"
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return cat
    return "color"


def _parse_color_value(value) -> Optional[tuple]:
    """解析Excel里五花八门的颜色写法：#RRGGBB / RRGGBB / (R,G,B) / R,G,B。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none"):
        return None

    hex_match = re.match(r"^#?([0-9a-fA-F]{6})$", text)
    if hex_match:
        h = hex_match.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    nums = re.findall(r"\d+", text)
    if len(nums) >= 3:
        r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
        if all(0 <= v <= 255 for v in (r, g, b)):
            return (r, g, b)
    return None


def _parse_float(value) -> Optional[float]:
    """
    从单元格里抠出一个数。

    要能扛住现实里的写法："≤ 1.5"、"<=2.0"、"1.5以内"、"±1.2"、" 1.5 "。
    直接 float() 全都会炸，所以先用正则把数字（含负号和小数点）捞出来。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "-", "/"):
        return None
    m = re.search(r"[-+]?\d*\.?\d+", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _lab_looks_valid(L, a, b) -> bool:
    """三个数看起来像不像一组合法的 Lab。防止把别的列误当成 Lab 读进来。"""
    if L is None or a is None or b is None:
        return False
    return 0.0 <= L <= 100.0 and -128.0 <= a <= 127.0 and -128.0 <= b <= 127.0


def _make_code(name: str, index: int, used: set) -> str:
    """
    没填编号时自动生成一个【看得懂】的编号，而不是一串 IMP-001 的流水号。

    规则：按名称里的颜色关键字给个语义前缀（大红→R、青→C、黄→Y…），
    这样师傅在配方单上看到 "R-01" 就知道大概是个红墨，比 "IMP-006" 有用得多。
    认不出来的才回落到流水号。
    """
    prefix_rules = [
        (("青", "cyan", "process blue", "过程蓝"), "C"),
        (("洋红", "品红", "magenta"), "M"),
        (("黄", "yellow"), "Y"),
        (("黑", "black"), "K"),
        (("白", "white"), "W"),
        (("蓝", "blue", "violet", "紫"), "B"),
        (("红", "red"), "R"),
        (("绿", "green"), "G"),
        (("橙", "orange"), "O"),
        (("冲淡", "光油", "varnish", "调墨油"), "V"),
    ]
    low = name.lower()
    prefix = None
    for keys, p in prefix_rules:
        if any(k in low or k in name for k in keys):
            prefix = p
            break
    if prefix is None:
        prefix = "IMP"

    n = 1
    while True:
        candidate = f"{prefix}-{n:02d}"
        if candidate not in used:
            return candidate
        n += 1


def parse_ink_excel(file_path: str) -> List[Dict]:
    """
    解析Excel文件，返回一批"待导入"的油墨记录草稿（还没写进数据库，
    先给调用方展示预览确认）。

    Returns:
        [
            {
                "code": "...", "name": "...", "category": "color",
                "category_guessed": True,   # 类别是猜的还是Excel里明确写的
                "K": [...], "S": [...],
                "has_color_source": True,   # 光谱是不是真的从颜色值推导出来的
                "stock_ml": 0.0, "price": 0.0,
            }, ...
        ]
    """
    import pandas as pd

    df = pd.read_excel(file_path, header=None)
    # 找表头所在行：找第一行"看起来像表头"（非纯数字、非空单元格数>=2）的行
    header_row_idx = 0
    for i in range(min(5, len(df))):
        row = df.iloc[i]
        non_empty = [str(v) for v in row if str(v).strip() not in ("", "nan")]
        if len(non_empty) >= 2 and not all(_is_number(v) for v in non_empty):
            header_row_idx = i
            break

    headers = [str(v) for v in df.iloc[header_row_idx]]
    data_rows = df.iloc[header_row_idx + 1:]

    col_code = _guess_column(headers, "code")
    col_name = _guess_column(headers, "name")
    col_category = _guess_column(headers, "category")
    col_color = _guess_column(headers, "color")
    col_stock = _guess_column(headers, "stock")
    col_price = _guess_column(headers, "price")
    col_lab_l = _guess_column(headers, "lab_l")
    col_lab_a = _guess_column(headers, "lab_a")
    col_lab_b = _guess_column(headers, "lab_b")
    col_tol = _guess_column(headers, "tolerance")

    results = []
    used_codes = set()
    for _, row in data_rows.iterrows():
        name_val = str(row[col_name]).strip() if col_name is not None else ""
        if not name_val or name_val.lower() == "nan":
            continue  # 没有名称的行跳过，大概率是空行

        code_val = str(row[col_code]).strip() if col_code is not None and str(row[col_code]).strip().lower() != "nan" else ""
        # Excel 里第一列常常是"序号"（1、2、3…），那不是油墨编号。
        # 一个纯数字当编号既没有意义、又容易跟别的墨撞车，所以当成没填。
        if code_val and _is_number(code_val):
            code_val = ""
        if not code_val:
            code_val = _make_code(name_val, len(results), used_codes)
        used_codes.add(code_val)

        explicit_category = str(row[col_category]).strip() if col_category is not None else None
        category = _guess_category(name_val, explicit_category)
        category_guessed = explicit_category is None or str(explicit_category).strip().lower() in ("nan", "")

        # ── 颜色来源：Lab 优先，RGB 次之 ──────────────────────────────
        # 为什么 Lab 优先：Lab 是仪器直接测出来的、设备无关的绝对色彩坐标。
        # RGB 是显示设备相关的，同一个 RGB 在不同屏幕上是不同的颜色，而且
        # sRGB 色域装不下丝印能印出来的很多饱和色（比如高饱和的橙和绿），
        # 强行走 RGB 会把这些颜色压扁。有 Lab 就绝不用 RGB。
        ref_lab = None
        source = ""
        if col_lab_l is not None and col_lab_a is not None and col_lab_b is not None:
            L = _parse_float(row[col_lab_l])
            a = _parse_float(row[col_lab_a])
            b = _parse_float(row[col_lab_b])
            if _lab_looks_valid(L, a, b):
                ref_lab = (L, a, b)
                source = "lab"

        if ref_lab is None:
            rgb = _parse_color_value(row[col_color]) if col_color is not None else None
            if rgb is not None:
                ref_lab = srgb_to_lab(*rgb)
                source = "rgb"

        if ref_lab is not None:
            synth = synthesize_ink_spectrum(ref_lab)
            k_list = [float(v) for v in synth["K"]]
            s_list = [float(v) for v in synth["S"]]
            has_color_source = True
        else:
            k_list = [20.0] * 31
            s_list = [10.0] * 31
            has_color_source = False
            source = ""

        # 允许色差：来料检验时用。没填的按经验给个默认值——
        # 黑色人眼最敏感（1.2），常规彩色 1.5，饱和度极高的色（射光蓝、紫罗兰、
        # 绿）本来就难做准，行业惯例放宽到 2.0。
        tol_val = _parse_float(row[col_tol]) if col_tol is not None else None
        if tol_val is None:
            tol_val = 2.0

        stock_val = 0.0
        if col_stock is not None:
            try:
                stock_val = float(row[col_stock])
            except (ValueError, TypeError):
                stock_val = 0.0

        price_val = 0.0
        if col_price is not None:
            try:
                price_val = float(row[col_price])
            except (ValueError, TypeError):
                price_val = 0.0

        rec = {
            "code": code_val,
            "name": name_val,
            "category": category,
            "category_guessed": category_guessed,
            "K": k_list,
            "S": s_list,
            "has_color_source": has_color_source,
            "color_source": source,          # "lab" / "rgb" / ""，预览时告诉用户颜色是从哪来的
            "delta_e_tolerance": tol_val,
            "stock_ml": stock_val,
            "low_stock_threshold_ml": 100.0,
            "price": price_val,
            "density": 1.05,
            "dry_back_factor": 0.25,
        }
        if ref_lab is not None:
            # 标准 Lab 存下来：这是【来料检验】的基准——供应商送来的墨，
            # 实测 Lab 跟它比，ΔE 超过允许色差就是不合格。
            rec["ref_lab"] = [round(float(v), 2) for v in ref_lab]
            # 标记 K/S 是从 Lab 推的，不是分光光度计实测的。UI 会据此提醒用户，
            # 避免他们误以为这和实测数据是一个精度级别。
            rec["ks_from_lab"] = True
        results.append(rec)
    return results


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
