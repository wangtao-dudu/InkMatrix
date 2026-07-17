# -*- coding: utf-8 -*-
"""
colorimetry_data.py  (CORE层 - 色度学常数与转换函数)
======================================================
CIE 标准光源定义、XYZ 观察者定义、色彩空间转换（XYZ ↔ Lab）函数库。

P1 修复：
  1. 支持 D50 / D65 光源切换（行业标准）
  2. 实现 ΔE2000 色差计算（替代ΔE76）
  3. 可配置观察者角度 (2° / 10°)
"""

import numpy as np
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# ==================== P1: 光源与观察者配置 ====================

# CIE 标准光源定义
ILLUMINANTS = {
    'D50': {
        '2': (0.96422, 1.00000, 0.82521),  # D50 2°
        '10': (0.96720, 1.00000, 0.81427),  # D50 10°
    },
    'D65': {
        '2': (0.95047, 1.00000, 1.08883),  # D65 2°
        '10': (0.94811, 1.00000, 1.07304),  # D65 10°
    }
}

# 标准 XYZ → sRGB 转换矩阵 (D65/2°)
XYZ_TO_SRGB_D65 = np.array([
    [3.2406, -1.5372, -0.4986],
    [-0.9689, 1.8758, 0.0415],
    [0.0557, -0.2040, 1.0570]
])

# 标准 sRGB → XYZ 转换矩阵 (D65/2°)
SRGB_TO_XYZ_D65 = np.array([
    [0.4124, 0.3576, 0.1805],
    [0.2126, 0.7152, 0.0722],
    [0.0193, 0.1192, 0.9505]
])

# 默认配置（向后兼容）
DEFAULT_ILLUMINANT = 'D65'
DEFAULT_OBSERVER = '2'


class ColorimetryConfig:
    """色度学全局配置。"""
    
    def __init__(self, illuminant: str = 'D65', observer: str = '2'):
        """
        Args:
            illuminant: 光源 ('D50' 或 'D65')
            observer: 观察者角度 ('2' 或 '10')
        """
        if illuminant not in ILLUMINANTS:
            raise ValueError(f"不支持的光源: {illuminant}，支持: {list(ILLUMINANTS.keys())}")
        if observer not in ILLUMINANTS[illuminant]:
            raise ValueError(f"不支持的观察者角度: {observer}°")
        
        self.illuminant = illuminant
        self.observer = observer
        self.reference_white = ILLUMINANTS[illuminant][observer]
        
        logger.info(f"色度学配置: 光源={illuminant}, 观察者={observer}°")
    
    def get_reference_white(self) -> Tuple[float, float, float]:
        """获取参考白点 (Xr, Yr, Zr)."""
        return self.reference_white


# 全局配置实例（可在应用启动时修改）
_global_colorimetry_config = ColorimetryConfig(DEFAULT_ILLUMINANT, DEFAULT_OBSERVER)


def set_colorimetry_config(illuminant: str = 'D65', observer: str = '2'):
    """设置全局色度学配置（应在应用启动时调用）。"""
    global _global_colorimetry_config
    _global_colorimetry_config = ColorimetryConfig(illuminant, observer)


def get_colorimetry_config() -> ColorimetryConfig:
    """获取当前全局色度学配置。"""
    return _global_colorimetry_config


# ==================== XYZ ↔ Lab 转换 ====================

def xyz_to_lab(xyz: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """
    XYZ → Lab 转换（使用全局配置的参考白点）。
    
    Args:
        xyz: (X, Y, Z) 元组
    
    Returns:
        (L*, a*, b*) 元组
    """
    config = get_colorimetry_config()
    Xr, Yr, Zr = config.reference_white
    
    X, Y, Z = xyz
    
    # 归一化
    xr = X / Xr
    yr = Y / Yr
    zr = Z / Zr
    
    # 非线性变换
    delta = 6.0 / 29.0
    delta_sq = delta ** 2
    delta_cb = delta ** 3
    
    def f(t):
        if t > delta_cb:
            return t ** (1/3)
        else:
            return t / (3 * delta_sq) + 4.0 / 29.0
    
    fx = f(xr)
    fy = f(yr)
    fz = f(zr)
    
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    
    return (L, a, b)


def lab_to_xyz(lab: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Lab → XYZ 转换（使用全局配置的参考白点）。"""
    config = get_colorimetry_config()
    Xr, Yr, Zr = config.reference_white
    
    L, a, b = lab
    
    # 反向计算
    fy = (L + 16) / 116
    fx = a / 500 + fy
    fz = fy - b / 200
    
    # 反向非线性变换
    delta = 6.0 / 29.0
    delta_sq = delta ** 2
    
    def f_inv(t):
        if t > delta:
            return t ** 3
        else:
            return 3 * delta_sq * (t - 4.0 / 29.0)
    
    xr = f_inv(fx)
    yr = f_inv(fy)
    zr = f_inv(fz)
    
    X = xr * Xr
    Y = yr * Yr
    Z = zr * Zr
    
    return (X, Y, Z)


# ==================== P1: ΔE 色差计算 ====================

def delta_e_76(lab1: Tuple[float, float, float], 
               lab2: Tuple[float, float, float]) -> float:
    """
    ΔE76 (CIE 1976) 色差计算（旧标准，不推荐用于精密应用）。
    
    ΔE = sqrt((ΔL)² + (Δa)² + (Δb)²)
    """
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    
    dL = L2 - L1
    da = a2 - a1
    db = b2 - b1
    
    return np.sqrt(dL**2 + da**2 + db**2)


def delta_e_94(lab1: Tuple[float, float, float],
               lab2: Tuple[float, float, float],
               kL: float = 1.0, kC: float = 1.0, kH: float = 1.0) -> float:
    """
    ΔE94 (CIE 1994) 色差计算（改进的不均匀加权）。
    
    适用于纺织印刷行业。
    """
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    
    dL = L2 - L1
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)
    dC = C2 - C1
    da = a2 - a1
    db = b2 - b1
    dH = np.sqrt(da**2 + db**2 - dC**2)
    
    SL = 1.0
    SC = 1.0 + 0.045 * C1
    SH = 1.0 + 0.015 * C1
    
    term1 = (dL / (kL * SL)) ** 2
    term2 = (dC / (kC * SC)) ** 2
    term3 = (dH / (kH * SH)) ** 2
    
    return np.sqrt(term1 + term2 + term3)


def delta_e_2000(lab1: Tuple[float, float, float],
                 lab2: Tuple[float, float, float],
                 kL: float = 1.0, kC: float = 1.0, kH: float = 1.0) -> float:
    """
    ΔE2000 (CIEDE2000) 色差计算 - 工业标准 (P1修复)。
    
    这是目前最先进的色差公式，特别适合：
    - 浅色、灰色、皮肤色等中低饱和度颜色
    - 印刷、涂料、塑料等工业应用
    - 精度要求 ΔE < 1 的场景
    
    参考文献: Luo, M. R., Cui, G., & Rigg, B. (2001).
    "The development of the CIE 2000 colour-difference formula: CIEDE2000"
    
    Args:
        lab1: (L*, a*, b*) 参考色
        lab2: (L*, a*, b*) 样品色
        kL, kC, kH: 加权系数（工业通常为1.0）
    
    Returns:
        ΔE2000 值（0=完全相同，< 1 视为优秀配方）
    """
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    
    # Step 1: 计算 C1 和 C2（色度）
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)
    C_avg = (C1 + C2) / 2.0
    
    # Step 2: 计算 G 因子（减弱低饱和度的 a* 权重）
    G = 0.5 * (1 - np.sqrt(C_avg**7 / (C_avg**7 + 25**7)))
    
    # Step 3: 修正后的 a* 和 C
    a1_prime = (1 + G) * a1
    a2_prime = (1 + G) * a2
    C1_prime = np.sqrt(a1_prime**2 + b1**2)
    C2_prime = np.sqrt(a2_prime**2 + b2**2)
    
    # Step 4: 计算 h（色调角）
    def hue_angle(a, b):
        h = np.arctan2(b, a)
        if h < 0:
            h += 2 * np.pi
        return np.degrees(h)
    
    h1_prime = hue_angle(a1_prime, b1)
    h2_prime = hue_angle(a2_prime, b2)
    
    # Step 5: 计算色差分量
    dL_prime = L2 - L1
    dC_prime = C2_prime - C1_prime
    
    # 色调差的计算（考虑圆形性）
    if C1_prime * C2_prime == 0:
        dH_prime = 0
    else:
        dh = h2_prime - h1_prime
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
        dH_prime = 2 * np.sqrt(C1_prime * C2_prime) * np.sin(np.radians(dh / 2.0))
    
    # Step 6: 计算平均值用于权重
    L_avg_prime = (L1 + L2) / 2.0
    C_avg_prime = (C1_prime + C2_prime) / 2.0
    
    # 平均色调角
    if C1_prime * C2_prime == 0:
        h_avg_prime = h1_prime + h2_prime
    else:
        h_sum = h1_prime + h2_prime
        if abs(h1_prime - h2_prime) > 180:
            if h_sum < 360:
                h_avg_prime = (h_sum + 360) / 2.0
            else:
                h_avg_prime = (h_sum - 360) / 2.0
        else:
            h_avg_prime = h_sum / 2.0
    
    # Step 7: 权重系数
    T = 1 - 0.17 * np.cos(np.radians(h_avg_prime - 30))           + 0.24 * np.cos(np.radians(2 * h_avg_prime))           + 0.32 * np.cos(np.radians(3 * h_avg_prime + 6))           - 0.20 * np.cos(np.radians(4 * h_avg_prime - 63))
    
    dh_deg = h2_prime - h1_prime
    if dh_deg > 180:
        dh_deg -= 360
    elif dh_deg < -180:
        dh_deg += 360
    
    # Step 8: SL, SC, SH 计算
    SL = 1 + (0.015 * (L_avg_prime - 50)**2) / np.sqrt(20 + (L_avg_prime - 50)**2)
    SC = 1 + 0.045 * C_avg_prime
    SH = 1 + 0.015 * C_avg_prime * T
    
    # Step 9: ΔE2000 最终公式
    term1 = (dL_prime / (kL * SL)) ** 2
    term2 = (dC_prime / (kC * SC)) ** 2
    term3 = (dH_prime / (kH * SH)) ** 2
    
    # 色调旋转 Rt 项（对高饱和度蓝色特别重要）
    theta = 30 * np.exp(-((h_avg_prime - 275) / 25) ** 2)
    C_avg_7 = C_avg_prime ** 7
    Rt = -2 * np.sin(np.radians(2 * theta)) * np.sqrt(C_avg_7 / (C_avg_7 + 25**7))
    term4 = Rt * (dC_prime / (kC * SC)) * (dH_prime / (kH * SH))
    
    de2000 = np.sqrt(term1 + term2 + term3 + term4)
    
    return de2000


def spectral_reflectance_to_lab(reflectance: np.ndarray) -> Tuple[float, float, float]:
    """
    光谱反射率曲线 → Lab 色空间转换。
    
    Args:
        reflectance: (31,) 光谱反射率曲线（400-700nm，10nm步长）
    
    Returns:
        (L*, a*, b*) Lab 颜色
    """
    # 标准观察者的 CIE 1931 2° 等色函数（31个波长点）
    x_bar = np.array([0.0014, 0.0022, 0.0042, 0.0076, 0.0143, 0.0232, 0.0435, 0.0776, 0.1344, 0.2148, 0.2839, 0.3285, 0.3483, 0.3481, 0.3362, 0.3187, 0.2908, 0.2511, 0.1954, 0.1421, 0.0956, 0.0570, 0.0320, 0.0147, 0.0049, 0.0024, 0.0093, 0.0291, 0.0633, 0.1096, 0.1655])
    y_bar = np.array([0.0001, 0.0001, 0.0002, 0.0004, 0.0006, 0.0012, 0.0022, 0.0040, 0.0068, 0.0107, 0.0141, 0.0168, 0.0170, 0.0160, 0.0137, 0.0107, 0.0077, 0.0057, 0.0039, 0.0027, 0.0017, 0.0011, 0.0008, 0.0004, 0.0002, 0.0001, 0.0004, 0.0012, 0.0027, 0.0049, 0.0083])
    z_bar = np.array([0.0065, 0.0105, 0.0201, 0.0362, 0.0679, 0.1102, 0.2074, 0.3713, 0.6456, 1.0391, 1.3856, 1.6230, 1.7471, 1.7721, 1.7441, 1.6692, 1.5281, 1.2876, 0.9300, 0.6162, 0.3810, 0.1649, 0.0469, 0.0093, 0.0001, 0.0000, 0.0001, 0.0003, 0.0008, 0.0014, 0.0020])
    
    # D65 照明
    config = get_colorimetry_config()
    
    if config.illuminant == 'D50':
        # D50 光谱功率分布（近似）
        D_illum = np.array([48.0, 50.0, 52.0, 54.0, 56.0, 57.0, 59.0, 61.0, 62.0, 63.0, 63.0, 63.0, 62.0, 62.0, 61.0, 59.0, 57.0, 54.0, 50.0, 45.0, 40.0, 36.0, 32.0, 27.0, 23.0, 20.0, 20.0, 21.0, 22.0, 23.0, 25.0])
    else:  # D65
        # D65 照明标准相对光谱功率分布
        D_illum = np.array([49.9755, 52.3118, 54.6482, 68.7015, 78.0087, 89.3517, 90.9761, 96.0212, 93.2357, 104.8658, 106.8786, 117.0081, 114.9060, 115.9243, 108.8278, 109.3871, 107.8887, 104.4759, 107.6860, 104.8449, 101.0227, 96.3252, 96.0567, 89.6991, 90.0871, 87.0894, 83.6538, 83.2888, 80.0268, 80.1449, 74.0027])
    
    # 计算 XYZ
    k = 100.0 / (y_bar * D_illum).sum()
    X = k * (reflectance * D_illum * x_bar).sum()
    Y = k * (reflectance * D_illum * y_bar).sum()
    Z = k * (reflectance * D_illum * z_bar).sum()
    
    # XYZ → Lab
    return xyz_to_lab((X, Y, Z))
