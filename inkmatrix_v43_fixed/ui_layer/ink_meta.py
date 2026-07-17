# -*- coding: utf-8 -*-
"""
ink_meta.py  (UI层 - 共享元数据)
===================================
油墨"类别"的中文展示名 + 徽标颜色，供【油墨库管理】页面表格与
【在库油墨勾选】组件共用，避免同一份映射写两遍。
"""

CATEGORY_META = {
    "color":   {"label": "彩色油墨",   "color": "#0d9488"},
    "white":   {"label": "高遮盖白",   "color": "#64748b"},
    "varnish": {"label": "透明冲淡剂", "color": "#2563eb"},
}


def category_label(code: str) -> str:
    return CATEGORY_META.get(code, {}).get("label", code or "未分类")


def category_color(code: str) -> str:
    return CATEGORY_META.get(code, {}).get("color", "#94a3b8")


def ink_fingerprint(ink_record: dict) -> tuple:
    """
    给一支油墨的K/S数据算一个轻量"指纹"(平均K, 平均S)，用来判断这支墨
    后续有没有被改过——配方寻优时会把当时用到的每支墨的指纹存下来，
    之后如果发现某支墨的指纹变了，就能提醒"这份配方所用的油墨数据已经
    更新，建议重新寻优"，避免拿着基于旧油墨数据算出的配方去实际印刷。

    注：只用平均值做指纹是简化做法——理论上光谱形状变了但平均值恰好
    没变的极端情况会漏检，但这种概率很低，用来做"是否需要提醒重新
    寻优"这个用途已经足够。
    """
    k = ink_record.get("K", [])
    s = ink_record.get("S", [])
    if not k or not s:
        return (0.0, 0.0)
    return (round(sum(k) / len(k), 4), round(sum(s) / len(s), 4))
