# -*- coding: utf-8 -*-
"""
color_convert.py  (CORE层 - 通用颜色空间转换)
================================================
提供与硬件/图像无关的纯数学颜色空间转换函数，供：
    - ui_layer.color_pickers  （效果图/瓶身照片取色）
    - ui_layer 的 CMYK 输入模式（客户CDR文件色值换算）
共用。保持 CORE 层"只依赖数学/科学计算，不感知UI"的高内聚原则。

包含：
    srgb_to_lab(r, g, b)      : 从图片/取色器采集到的 sRGB (0-255) 转 CIELAB
    cmyk_to_lab(c, m, y, k)   : CMYK(0-100) 近似转 CIELAB（无ICC描述文件的简化模型）
    lab_to_srgb_approx(L,a,b): Lab 转近似 sRGB，仅用于界面色块预览
"""

import numpy as np

# D65 标准光源白点 (CIE 1931 2°观察者)，与 colorimetry_data.py 保持一致
_XN, _YN, _ZN = 95.047, 100.000, 108.883

# sRGB(线性) -> CIE XYZ (D65) 标准转换矩阵
_RGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)


def _f_xyz_to_lab(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta ** 3:
        return t ** (1.0 / 3.0)
    return t / (3 * delta ** 2) + 4.0 / 29.0


def _f_inv_lab_to_xyz(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta:
        return t ** 3
    return 3 * delta ** 2 * (t - 4.0 / 29.0)


def _srgb_gamma_decode(c: float) -> float:
    """sRGB 伽马解码：0-1 的 sRGB 分量 -> 线性光分量。"""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _srgb_gamma_encode(c: float) -> float:
    """线性光分量 -> sRGB 伽马编码分量，并裁剪到 [0,1]。"""
    c = max(0.0, min(1.0, c))
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_lab(r: float, g: float, b: float) -> tuple:
    """
    将取色器 / 图片像素采样得到的 sRGB (0-255整数或浮点) 转换为 CIELAB (D65)。

    用于：效果图取色、瓶身照片取色 —— 把"看到的颜色"变成算法可用的目标Lab。

    Args:
        r, g, b: sRGB 三通道，取值范围 0~255

    Returns:
        (L, a, b) 三元组
    """
    rl = _srgb_gamma_decode(r / 255.0)
    gl = _srgb_gamma_decode(g / 255.0)
    bl = _srgb_gamma_decode(b / 255.0)

    xyz = _RGB_TO_XYZ @ np.array([rl, gl, bl])
    x, y, z = xyz[0] * 100.0, xyz[1] * 100.0, xyz[2] * 100.0

    fx, fy, fz = _f_xyz_to_lab(x / _XN), _f_xyz_to_lab(y / _YN), _f_xyz_to_lab(z / _ZN)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    bb = 200.0 * (fy - fz)
    return (float(L), float(a), float(bb))


def lab_to_srgb_approx(L: float, a: float, b: float) -> tuple:
    """
    Lab -> 近似 sRGB（0-255整数），仅供UI色块预览使用，不作为工业计算依据。
    """
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0

    x = _f_inv_lab_to_xyz(fx) * _XN
    y = _f_inv_lab_to_xyz(fy) * _YN
    z = _f_inv_lab_to_xyz(fz) * _ZN

    xyz = np.array([x, y, z]) / 100.0
    rl, gl, bl = _XYZ_TO_RGB @ xyz

    r = _srgb_gamma_encode(rl)
    g = _srgb_gamma_encode(gl)
    bb = _srgb_gamma_encode(bl)
    return (int(round(r * 255)), int(round(g * 255)), int(round(bb * 255)))


def cmyk_to_lab(c: float, m: float, y: float, k: float) -> tuple:
    """
    CMYK(0-100百分比) -> CIELAB 近似换算。

    ⚠️ 重要说明：本换算未绑定任何印刷ICC描述文件（如 SWOP/GRACoL/FOGRA），
    采用的是"简化减色法"模型：
        R = 255 * (1-C/100) * (1-K/100)
        G = 255 * (1-M/100) * (1-K/100)
        B = 255 * (1-Y/100) * (1-K/100)
    这只能给出一个"大致方向正确"的Lab估算值，同样的CMYK数值在不同纸张/
    油墨/印刷工艺下实际呈现的颜色会有明显差异。客户CDR文件里的CMYK数值
    仅建议作为配方寻优的"初始参考目标"，最终仍应结合效果图取色或实物
    比色确认，避免直接以此CMYK换算结果作为最终交付判定依据。

    Args:
        c, m, y, k: 0~100 的百分比数值

    Returns:
        (L, a, b) 三元组（近似值）
    """
    c, m, y, k = (max(0.0, min(100.0, v)) / 100.0 for v in (c, m, y, k))
    r = 255.0 * (1.0 - c) * (1.0 - k)
    g = 255.0 * (1.0 - m) * (1.0 - k)
    b = 255.0 * (1.0 - y) * (1.0 - k)
    return srgb_to_lab(r, g, b)


def hsl_to_rgb(h: float, s: float, l: float) -> tuple:
    """
    HSL (h:0-360, s:0-100, l:0-100) -> sRGB (0-255整数)。

    供色卡网格 (color_swatch_library.py) 与色相环控件 (color_wheel.py)
    共用，避免同一份转换逻辑写两遍。
    """
    s /= 100.0
    l /= 100.0
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
    if 0 <= h < 60:
        r, g, b = c, x, 0.0
    elif 60 <= h < 120:
        r, g, b = x, c, 0.0
    elif 120 <= h < 180:
        r, g, b = 0.0, c, x
    elif 180 <= h < 240:
        r, g, b = 0.0, x, c
    elif 240 <= h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (int(round((r + m) * 255)), int(round((g + m) * 255)), int(round((b + m) * 255)))
