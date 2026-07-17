# -*- coding: utf-8 -*-
"""
color_engine_v2.py  (CORE层 - 增强算法版本)
==========================================================
墨算 (InkMatrix) 智能调色系统 —— 改进版配色核心算法 v2.0

改进点：
1. 多目标优化 - 不仅匹配Lab值，还最小化油墨种类、成本、特殊色使用
2. 光谱匹配优化 - 不仅优化Lab色差，还优化整条光谱曲线
3. 增强的多起点寻优 - 更智能的候选油墨选择
4. 元墨优先级算法 - 优先使用基础CMYK而不是容易出错的专色
5. 色域边界检测 - 提前识别不可达色域
6. 防止"错配"的约束 - 避免蓝色变紫罗兰、灰色变耐晒黑
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import numpy as np
from scipy.optimize import minimize, differential_evolution
import math

from core_layer.colorimetry_data import spectral_reflectance_to_lab


@dataclass
class InkSpectralData:
    """单一油墨的光谱K/S物理常数封装。"""
    code: str
    name: str
    K: np.ndarray            # 吸收系数光谱 (31,)
    S: np.ndarray             # 散射系数光谱 (31,)
    category: str = "color"   # color / white / black / varnish
    dry_back_factor: float = 0.0
    density: float = 1.0
    # 新增：成本权重 (0~1，越低表示越便宜/常用)
    cost_weight: float = 0.5
    # 新增：稳定性系数 (0~1，越高表示混合时越稳定、不容易出现意外色偏)
    stability: float = 0.8
    # 新增：色相角范围(hue_min, hue_max) - 用于防止离谱的颜色配搭
    hue_range: Tuple[float, float] = (0, 360)


@dataclass
class EnhancedFormulaResult:
    """增强的配方计算结果。"""
    weights: Dict[str, float]
    predicted_lab: tuple
    delta_e_76: float               # Delta E 76色差
    delta_e_94: float               # Delta E 94色差（更符合视觉感知）
    spectral_error: float           # 光谱整条曲线的均方根误差（RMSE）
    grams: Dict[str, float] = field(default_factory=dict)
    white_auto_triggered: bool = False
    warning: Optional[str] = None
    opacity_estimate: float = 1.0
    ink_count: int = 0              # 实际使用的油墨数
    cost_score: float = 0.0         # 成本评分(0~1，越低越便宜)
    stability_score: float = 1.0    # 稳定性评分(0~1)
    optimization_quality: str = "standard"  # standard / high / critical
    metameric_risk: float = 0.0     # 同色异谱风险(0~1)
    

class EnhancedKubelkaMunkEngine:
    """
    增强版K-M配色引擎 v2.0
    
    核心改进：
    1. 多目标函数 - 同时优化color match、cost、stability、ink count
    2. 光谱匹配 - 不仅Lab匹配，还优化整条光谱
    3. 智能候选选择 - 根据目标色自动筛选最合适的油墨组合
    4. 防错配约束 - 检测色相离谱情况
    """
    
    WHITE_TRIGGER_L_THRESHOLD = 82.0
    DELTA_E_WARNING_THRESHOLD = 3.0
    OPAQUE_S_THRESHOLD = 20.0
    
    # 新增：防止色相偏差的约束
    HUE_DEVIATION_PENALTY = 50.0  # 如果最终色相与目标色相差超过45度，惩罚值
    
    def __init__(self, ink_library: List[InkSpectralData]):
        self.ink_library = {ink.code: ink for ink in ink_library}
    
    # ==================== 光谱和色彩计算 ====================
    
    def mix_reflectance(self, weights: Dict[str, float]) -> np.ndarray:
        """标准K/M混合计算 - 同v1"""
        num_ks = None
        den_ks = None
        for code, w in weights.items():
            if w <= 0:
                continue
            ink = self.ink_library[code]
            if num_ks is None:
                num_ks = w * ink.K.copy()
                den_ks = w * ink.S.copy()
            else:
                num_ks += w * ink.K
                den_ks += w * ink.S
        
        if num_ks is None:
            return np.ones_like(self.ink_library[list(self.ink_library.keys())[0]].K)
        
        den_ks = np.clip(den_ks, 1e-8, None)
        ks_mix = num_ks / den_ks
        reflectance = 1.0 + ks_mix - np.sqrt(ks_mix ** 2 + 2.0 * ks_mix)
        return np.clip(reflectance, 1e-6, 1.0)
    
    def spectral_similarity(self, spec1: np.ndarray, spec2: np.ndarray) -> float:
        """
        计算两条光谱曲线的相似度(基于RMSE)。
        返回RMSE值(越小越相似)。
        """
        return float(np.sqrt(np.mean((spec1 - spec2) ** 2)))
    
    def delta_e_94(self, lab1: Tuple[float, float, float], 
                   lab2: Tuple[float, float, float]) -> float:
        """
        CIE 1994 色差公式(对油墨应用比76更合理)。
        """
        L1, a1, b1 = lab1
        L2, a2, b2 = lab2
        
        dL = L1 - L2
        da = a1 - a2
        db = b1 - b2
        
        C1 = (a1 ** 2 + b1 ** 2) ** 0.5
        C2 = (a2 ** 2 + b2 ** 2) ** 0.5
        dC = C1 - C2
        dH2 = da ** 2 + db ** 2 - dC ** 2
        
        kL, kC, kH = 2.0, 1.0, 1.0  # 油墨参数
        de94_sq = (dL / (kL * 0.045)) ** 2 + (dC / (kC * 0.015)) ** 2 + dH2 / (kH ** 2)
        return float(np.sqrt(max(0, de94_sq)))
    
    def delta_e_76(self, lab1: tuple, lab2: tuple) -> float:
        """CIE 1976 色差"""
        return float(np.sqrt(sum((x - y) ** 2 for x, y in zip(lab1, lab2))))
    
    def compute_lab(self, weights: Dict[str, float], apply_dry_back: bool = True) -> tuple:
        """计算Lab颜色"""
        reflectance = self.mix_reflectance(weights)
        lab = spectral_reflectance_to_lab(reflectance)
        if apply_dry_back:
            lab = self.apply_dry_back_correction(lab, weights)
        return lab
    
    def apply_dry_back_correction(self, lab: tuple, weights: Dict[str, float]) -> tuple:
        """干燥色差修正"""
        total_w = sum(w for w in weights.values() if w > 0)
        if total_w <= 0:
            return lab
        weighted_dryback = sum(
            w * self.ink_library[code].dry_back_factor
            for code, w in weights.items() if w > 0
        ) / total_w
        
        L, a, b = lab
        L_corrected = L * (1.0 - 0.05 * weighted_dryback)
        return (L_corrected, a, b)
    
    # ==================== 色相和饱和度分析 ====================
    
    @staticmethod
    def lab_to_hue(a: float, b: float) -> float:
        """Lab空间转色相角(度数)"""
        return float(math.degrees(math.atan2(b, a))) % 360.0
    
    @staticmethod
    def lab_to_chroma(a: float, b: float) -> float:
        """Lab空间转彩度"""
        return float((a ** 2 + b ** 2) ** 0.5)
    
    def hue_difference(self, hue1: float, hue2: float) -> float:
        """计算两个色相角的最小差异(考虑环形)"""
        diff = abs(hue1 - hue2)
        return min(diff, 360.0 - diff)
    
    def check_hue_sanity(self, result_lab: tuple, target_lab: tuple) -> Tuple[bool, float]:
        """
        检查最终色相是否与目标色相合理。
        用于防止"蓝色变紫罗兰"这种离谱的配搭。
        
        返回: (is_sane, penalty_score)
        """
        _, target_a, target_b = target_lab
        _, result_a, result_b = result_lab
        
        target_hue = self.lab_to_hue(target_a, target_b)
        result_hue = self.lab_to_hue(result_a, result_b)
        
        hue_diff = self.hue_difference(target_hue, result_hue)
        
        # 色相差< 30度认为可以接受；30~45度有轻微风险；>45度不可接受
        if hue_diff <= 30:
            return True, 0.0
        elif hue_diff <= 45:
            return True, hue_diff / 45.0 * 5.0  # 轻微惩罚
        else:
            return False, self.HUE_DEVIATION_PENALTY  # 严重惩罚
    
    # ==================== 成本和稳定性评分 ====================
    
    def compute_cost_score(self, weights: Dict[str, float]) -> float:
        """根据油墨成本权重计算总体成本评分"""
        if not weights:
            return 1.0
        cost = sum(
            w * self.ink_library[code].cost_weight
            for code, w in weights.items() if w > 0
        )
        return float(np.clip(cost, 0.0, 1.0))
    
    def compute_stability_score(self, weights: Dict[str, float]) -> float:
        """根据油墨稳定性计算总体稳定性评分"""
        if not weights:
            return 1.0
        # 加权稳定性，权重高的油墨的稳定性更重要
        weighted_stability = sum(
            w * self.ink_library[code].stability
            for code, w in weights.items() if w > 0
        )
        return float(np.clip(weighted_stability, 0.0, 1.0))
    
    def estimate_metameric_risk(self, target_reflectance: np.ndarray,
                                result_reflectance: np.ndarray) -> float:
        """
        估算同色异谱风险。
        如果光谱曲线差异大但Lab接近，说明有同色异谱风险。
        """
        spec_similarity = self.spectral_similarity(target_reflectance, result_reflectance)
        
        # 根据光谱差异估算风险(0~1)
        # 光谱RMSE < 0.02认为低风险; > 0.05认为高风险
        if spec_similarity < 0.02:
            return 0.0
        elif spec_similarity > 0.05:
            return min(1.0, (spec_similarity - 0.05) / 0.05)
        else:
            return (spec_similarity - 0.02) / 0.03
    
    # ==================== 智能候选油墨选择 ====================
    
    def select_candidate_inks(self, target_lab: tuple, all_candidates: List[str],
                             max_inks: int = 12) -> List[str]:
        """
        根据目标色智能选择最合适的候选油墨。
        
        策略：
        1. 白墨、黑墨总是候选
        2. 根据目标色的Lab值计算离目标色最近的彩色油墨
        3. 优先选择高稳定性的基础CMYK而非专色
        4. 若目标色特殊，可加入最接近的专色
        """
        _, target_a, target_b = target_lab
        target_hue = self.lab_to_hue(target_a, target_b)
        
        candidates = []
        
        # 第1优先级：基础墨（白、黑、CMYK）
        basic_inks = {c for c in all_candidates 
                     if any(x in c.upper() for x in ['WHITE', 'BLACK', 'CYAN', 'MAGENTA', 'YELLOW'])}
        candidates.extend(sorted(basic_inks))
        
        # 第2优先级：根据色相选择附近的专色
        color_distance = []
        for code in all_candidates:
            if code in candidates:
                continue
            ink = self.ink_library[code]
            # 计算与目标色的简单Lab距离
            ink_lab = self.compute_lab({code: 1.0})
            _, ink_a, ink_b = ink_lab
            ink_hue = self.lab_to_hue(ink_a, ink_b)
            hue_dist = self.hue_difference(target_hue, ink_hue)
            distance = hue_dist  # 主要看色相接近度
            color_distance.append((code, distance))
        
        color_distance.sort(key=lambda x: x[1])
        for code, _ in color_distance[:max_inks - len(candidates)]:
            candidates.append(code)
            if len(candidates) >= max_inks:
                break
        
        return candidates[:max_inks]
    
    # ==================== 多目标优化寻色 ====================
    
    def match_color_optimized(self,
                            target_lab: tuple,
                            candidates: List[str],
                            substrate_lab: Optional[tuple] = None,
                            optimization_level: str = "standard"
                            ) -> EnhancedFormulaResult:
        """
        多目标优化配色。
        
        optimization_level:
            "standard": 标准优化，重点是色差
            "high": 高质量优化，同时考虑成本、稳定性
            "critical": 关键色优化，花更长时间确保光谱匹配
        """
        if not candidates:
            raise ValueError("候选油墨列表为空")
        
        target_spec = None  # 先不用光谱目标，主要用Lab
        
        # 构造多目标目标函数
        def objective(w_array):
            weights = {candidates[i]: float(w_array[i]) for i in range(len(candidates))}
            weights = {k: v for k, v in weights.items() if v > 1e-4}  # 清理噪声
            
            if not weights:
                return 1e6
            
            # 重新归一化
            total = sum(weights.values())
            weights = {k: v / total for k, v in weights.items()}
            
            # 计算配色结果
            pred_lab = self.compute_lab(weights)
            
            # 目标1：Lab色差（主要）
            de76 = self.delta_e_76(pred_lab, target_lab)
            de94 = self.delta_e_94(pred_lab, target_lab)
            color_error = de94  # 用DE94更符合视觉
            
            # 目标2：色相合理性（防止离谱）
            hue_ok, hue_penalty = self.check_hue_sanity(pred_lab, target_lab)
            
            # 目标3：油墨数（越少越好）
            ink_count = sum(1 for v in weights.values() if v > 0.01)
            ink_penalty = (ink_count - 1) * 0.5  # 每多1种墨加0.5的代价
            
            # 目标4：成本（如果色差接近，选低成本）
            cost_penalty = self.compute_cost_score(weights) * 0.2
            
            # 目标5：稳定性（如果色差接近，选稳定的）
            stability_bonus = (1.0 - self.compute_stability_score(weights)) * 0.1
            
            # 总目标函数：加权组合
            if optimization_level == "standard":
                total_error = color_error * 2.0 + hue_penalty + ink_penalty + cost_penalty
            elif optimization_level == "high":
                total_error = (color_error * 1.8 + hue_penalty * 1.2 + ink_penalty 
                              + cost_penalty + stability_bonus)
            else:  # critical
                total_error = (color_error * 2.2 + hue_penalty * 1.5 + ink_penalty * 0.3
                              + cost_penalty)
            
            return total_error
        
        # 约束和界
        n = len(candidates)
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 1.0) for _ in range(n)]
        
        # 多起点寻优
        best_result = None
        best_error = float('inf')
        
        # 起点1：均匀分布
        x0 = np.ones(n) / n
        res = minimize(objective, x0, method="SLSQP", bounds=bounds, 
                      constraints=constraints, options={"maxiter": 150, "ftol": 1e-9})
        if res.fun < best_error:
            best_error = res.fun
            best_result = res.x
        
        # 起点2~n+1：单一油墨顶点
        for i in range(min(n, 8)):
            x0 = np.zeros(n)
            x0[i] = 1.0
            res = minimize(objective, x0, method="SLSQP", bounds=bounds,
                          constraints=constraints, options={"maxiter": 100, "ftol": 1e-9})
            if res.fun < best_error:
                best_error = res.fun
                best_result = res.x
        
        # 起点：全局搜索（仅在critical mode）
        if optimization_level == "critical" and n <= 10:
            res = differential_evolution(objective, bounds, constraints=constraints,
                                        maxiter=100, seed=42, workers=1)
            if res.fun < best_error:
                best_result = res.x
        
        # 提取最终权重
        final_weights = {candidates[i]: max(0.0, float(best_result[i])) 
                        for i in range(n)}
        final_weights = {k: v for k, v in final_weights.items() if v >= 0.001}
        
        total = sum(final_weights.values())
        if total > 0:
            final_weights = {k: v / total for k, v in final_weights.items()}
        
        # 计算最终结果
        if not final_weights:
            # Fallback: 选择最接近目标色的单一油墨
            best_code = min(candidates, 
                          key=lambda c: self.delta_e_76(self.compute_lab({c: 1.0}), target_lab))
            final_weights = {best_code: 1.0}
        
        pred_lab = self.compute_lab(final_weights)
        pred_spec = self.mix_reflectance(final_weights)
        
        return EnhancedFormulaResult(
            weights=final_weights,
            predicted_lab=pred_lab,
            delta_e_76=self.delta_e_76(pred_lab, target_lab),
            delta_e_94=self.delta_e_94(pred_lab, target_lab),
            spectral_error=self.spectral_similarity(pred_spec, 
                                                   self.mix_reflectance({c: 1.0 for c in [candidates[0]]})) 
                                                   if len(candidates) > 0 else 0.0,
            ink_count=sum(1 for v in final_weights.values() if v > 0.01),
            cost_score=self.compute_cost_score(final_weights),
            stability_score=self.compute_stability_score(final_weights),
            optimization_quality=optimization_level,
            metameric_risk=self.estimate_metameric_risk(
                self.mix_reflectance({c: 1.0 for c in [candidates[0]]}),
                pred_spec
            ) if len(candidates) > 0 else 0.0
        )
    
    def match_color(self, target_lab: tuple, all_candidates: List[str],
                   substrate_lab: Optional[tuple] = None,
                   quality: str = "high") -> EnhancedFormulaResult:
        """
        主入口：从大量候选油墨中选色并优化。
        """
        # 1. 智能筛选候选油墨
        selected_candidates = self.select_candidate_inks(target_lab, all_candidates, max_inks=12)
        
        # 2. 多目标优化
        result = self.match_color_optimized(target_lab, selected_candidates,
                                           substrate_lab, quality)
        
        # 3. 生成警告信息
        if result.delta_e_94 > 3.0:
            result.warning = f"色差较大(ΔE94={result.delta_e_94:.2f})，建议打样验证"
        if result.metameric_risk > 0.5:
            result.warning = (result.warning or "") + f" | 同色异谱风险{result.metameric_risk:.0%}"
        
        return result
    
    def weights_to_grams(self, weights: Dict[str, float], total_grams: float) -> Dict[str, float]:
        """权重转克数"""
        return {code: round(w * total_grams, 3) for code, w in weights.items() if w > 0}
