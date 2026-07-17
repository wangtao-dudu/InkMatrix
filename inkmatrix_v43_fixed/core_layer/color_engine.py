# -*- coding: utf-8 -*-
"""
color_engine.py  (CORE层 - 核心算法层)
========================================
墨算 (InkMatrix) 智能调色系统 —— 非线性 Kubelka-Munk (K-M) 配色核心算法。

理论基础：
    (K/S)_mix(λ) = [ Σ w_i * K_i(λ) ] / [ Σ w_i * S_i(λ) ]

    再由 K-M 反函数将 (K/S) 转换为理论反射率 R(λ)：
        R = 1 + (K/S) - sqrt( (K/S)^2 + 2*(K/S) )

    最终对 31 点光谱反射率曲线做 CIE XYZ -> CIELAB 转换，
    得到该配方组合在 D65 光源下的理论 Lab 颜色。

本层完全独立于 UI 与硬件，只依赖 numpy / scipy，符合高内聚低耦合原则。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional

import numpy as np
from scipy.optimize import minimize

from core_layer.colorimetry_data import spectral_reflectance_to_lab


# --------------------------------------------------------------------------
# 数据结构定义
# --------------------------------------------------------------------------

@dataclass
class InkSpectralData:
    """单一油墨的光谱K/S物理常数封装。"""
    code: str
    name: str
    K: np.ndarray            # 吸收系数光谱 (31,)
    S: np.ndarray             # 散射系数光谱 (31,)
    category: str = "color"   # color / white / black / varnish
    dry_back_factor: float = 0.0   # 干燥色差修正系数 (0~1, 越大表示干燥后越暗)
    density: float = 1.0            # 油墨密度 g/ml，供后续体积-重量换算


@dataclass
class FormulaResult:
    """配方计算结果。"""
    weights: Dict[str, float]        # {ink_code: 百分比权重 0~1}
    predicted_lab: tuple             # (L, a, b)  —— 已包含承印物底色透出影响的表观色
    delta_e: float                   # 与目标色的色差
    grams: Dict[str, float] = field(default_factory=dict)  # {ink_code: 克重}
    white_auto_triggered: bool = False
    warning: Optional[str] = None
    opacity_estimate: float = 1.0    # 配方遮盖力估算(0~1)，1=完全不透
    ink_count_simplified: bool = False  # 是否经过"精简油墨种类"处理


# --------------------------------------------------------------------------
# 核心配色引擎
# --------------------------------------------------------------------------

class KubelkaMunkEngine:
    """
    非线性 K-M 配色核心引擎。

    职责：
        1. K/S 正向混合计算 -> 反射率 -> Lab。
        2. 基于 scipy SLSQP 的配方逆向寻优。
        3. 干燥色差修正、高遮盖白墨自动触发、透明冲淡剂通道支持。
    """

    # 亮度阈值：目标色 L* 高于该值视为浅色/浅淡色，若配方中未含白墨则自动触发
    WHITE_TRIGGER_L_THRESHOLD = 82.0
    # 色差报警阈值（工业通用容差，超过则界面需红字预警）
    DELTA_E_WARNING_THRESHOLD = 3.0

    def __init__(self, ink_library: List[InkSpectralData]):
        self.ink_library = {ink.code: ink for ink in ink_library}

    # ---------------------- 正向计算 ----------------------

    def mix_reflectance(self, weights: Dict[str, float]) -> np.ndarray:
        """
        根据给定权重字典，计算混合后的光谱反射率曲线 R(λ)。

        weights: {ink_code: weight(0~1)}，理论上 sum(weights) == 1.0
        
        P0-2 修复：权重必须归一化，保证 sum(weights) == 1.0
        """
        # 权重归一化：确保总权重为1.0
        total_weight = sum(weights.values())
        if total_weight <= 0:
            raise ValueError(f"权重总和必须 > 0，当前值: {total_weight}")
        
        normalized_weights = {
            code: w / total_weight
            for code, w in weights.items()
        }
        num_ks = None
        den_ks = None
        for code, w in normalized_weights.items():
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
            # 没有任何有效权重，返回全反射（视为空白/白板）
            return np.ones_like(self.ink_library[list(self.ink_library.keys())[0]].K)

        # 防止除零：散射系数极小时加保护
        den_ks = np.clip(den_ks, 1e-8, None)
        ks_mix = num_ks / den_ks

        # K-M 反函数：由 K/S 求解反射率 R
        reflectance = 1.0 + ks_mix - np.sqrt(ks_mix ** 2 + 2.0 * ks_mix)
        return np.clip(reflectance, 1e-6, 1.0)

    def apply_dry_back_correction(self, lab: tuple, weights: Dict[str, float]) -> tuple:
        """
        干燥色差（Dry-Back）修正：油墨湿态与干燥后的明度会有差异，
        通常干燥后颜色略深（L*降低）。此处按加权平均干燥系数对 L* 做线性修正。
        """
        total_w = sum(w for w in weights.values() if w > 0)
        if total_w <= 0:
            return lab
        weighted_dryback = sum(
            w * self.ink_library[code].dry_back_factor
            for code, w in weights.items() if w > 0
        ) / total_w

        L, a, b = lab
        # 干燥后 L* 略微降低，修正幅度与该配方的综合干燥系数成正比
        L_corrected = L * (1.0 - 0.05 * weighted_dryback)
        return (L_corrected, a, b)

    def compute_lab(self, weights: Dict[str, float], apply_dry_back: bool = True) -> tuple:
        reflectance = self.mix_reflectance(weights)
        lab = spectral_reflectance_to_lab(reflectance)
        if apply_dry_back:
            lab = self.apply_dry_back_correction(lab, weights)
        return lab

    # 遮盖力估算相关：散射系数S越高代表颜料本身越"实"、越不透光。
    # 这个阈值是从现有油墨数据校准出来的粗略经验值（不是严谨光学测量），
    # 详见 compute_apparent_lab 的说明。
    OPAQUE_S_THRESHOLD = 20.0

    def estimate_opacity(
        self,
        weights: Dict[str, float],
        material_props: Optional[Dict] = None,
    ) -> float:
        """
        粗略估算当前配方的"遮盖力"（0~1，1表示完全不透，看不到底材）。

        说明（重要，避免误解为精确光学测量）：
            严谨的做法需要"油墨层厚度 × 散射系数"这个光学厚度参数，
            但本软件目前没有对每种墨做真实的厚度标定，所以这里用一个
            简化的经验代理指标——配方里各油墨散射系数S的加权平均值，
            相对于一个从现有油墨数据校准出的"视为不透明"的阈值
            (OPAQUE_S_THRESHOLD) 来估算遮盖力比例。

            高遮盖白墨(W-001)的S远高于普通彩墨，配方里白墨占比越高，
            遮盖力估算值越接近1；纯冲淡剂/薄涂层配方遮盖力会明显偏低，
            提示瓶身底色可能透出来影响最终视觉效果。

            这是一个"方向正确、数值仅供参考"的估算，不是精确的分光
            测量替代品，实际生产建议以打样实测为准。

        承印物材质修正（material_props，见 DAL 层 MATERIAL_LIBRARY）：
            同一个配方印在不同材质上，实际遮盖效果差别很大，原因有两个：

            ① film_factor（墨膜留存系数）——纸质、粗糙塑料会把一部分油墨
               吸进材质里，留在表面形成显色的墨膜就变薄了，遮盖力自然下降。
               牛皮纸只有0.72，意思是同样的墨印上去，实际起作用的墨膜只有
               光滑玻璃的七成左右，颜色会明显偏浅偏灰。

            ② opacity_boost（遮盖需求倍数）——深棕药瓶、铜、铝这类底色深或
               带金属光泽的材质，要盖住它需要比盖住白塑料强得多的遮盖力。
               这里用除法把"需求变高"等价地表达成"有效遮盖力变低"，寻优时
               就会自动往配方里多加白墨去压住底色。

            不传 material_props 时行为跟旧版本完全一致（等价于两个系数都=1）。
        """
        total_w = sum(w for w in weights.values() if w > 0)
        if total_w <= 0:
            return 0.0
        weighted_s = sum(
            w * float(np.mean(self.ink_library[code].S))
            for code, w in weights.items() if w > 0 and code in self.ink_library
        ) / total_w
        opacity = weighted_s / self.OPAQUE_S_THRESHOLD

        if material_props:
            film_factor = material_props.get("film_factor", 1.0) or 1.0
            opacity_boost = material_props.get("opacity_boost", 1.0) or 1.0
            if opacity_boost <= 0:
                opacity_boost = 1.0
            opacity = opacity * film_factor / opacity_boost

        return float(np.clip(opacity, 0.0, 1.0))

    def compute_apparent_lab(
        self,
        weights: Dict[str, float],
        substrate_lab: Optional[tuple] = None,
        apply_dry_back: bool = True,
        material_props: Optional[Dict] = None,
    ) -> tuple:
        """
        计算"考虑瓶身/承印物底色透出 + 材质吸墨"之后的表观颜色。

        原理（简化近似，非严谨分光级K-M底材叠加公式）：
            1. 先按现有逻辑算出油墨本身在"完全不透明"假设下的颜色
               (masstone_lab)。
            2. 用 estimate_opacity() 估算这个配方在【这种材质上】的实际遮盖力
               （已含 film_factor / opacity_boost 两个材质修正）。
            3. 遮盖力不足100%时，在Lab空间按遮盖力比例跟承印物底色
               做线性混合，模拟"底色透过油墨层影响观感"这个真实现象。

        没有提供 substrate_lab（比如瓶身选了"未指定"）时，直接返回
        masstone_lab，行为跟旧版本完全一致，不影响没有选瓶身底色的场景。
        """
        masstone_lab = self.compute_lab(weights, apply_dry_back=apply_dry_back)
        if substrate_lab is None:
            return masstone_lab

        opacity = self.estimate_opacity(weights, material_props)
        if opacity >= 0.999:
            return masstone_lab

        blended = tuple(
            opacity * m + (1.0 - opacity) * s
            for m, s in zip(masstone_lab, substrate_lab)
        )
        return blended

    @staticmethod
    def delta_e_76(lab1: tuple, lab2: tuple) -> float:
        """CIE76 色差公式（工业现场常用的简化色差判定）。"""
        return float(np.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2))))

    # ---------------------- 逆向寻优（配方计算） ----------------------

    def solve_formula(
        self,
        target_lab: tuple,
        candidate_codes: List[str],
        white_codes: Optional[List[str]] = None,
        substrate_lab: Optional[tuple] = None,
        simplify: bool = True,
        simplify_tolerance: float = 1.2,
        min_practical_weight: float = 0.03,
        material_props: Optional[Dict] = None,
    ) -> FormulaResult:
        """
        在给定候选油墨范围内，寻找使预测Lab最接近目标Lab的配方权重。

        约束：
            sum(w_i) == 1.0
            0.0 <= w_i <= 1.0   （每个分量的边界）

        白墨自动触发机制：
            若目标色 L* 较高（浅色/粉彩色）且候选墨中未包含任何白墨，
            自动将库存中遮盖力最高的白墨加入候选池参与寻优。

        承印物底色影响（substrate_lab）：
            若传入瓶身/承印物底色，寻优目标会切换成"表观色"（masstone
            颜色按遮盖力跟底色混合后的结果），而不是简单假设油墨完全
            不透明——这样配方会自动倾向于在遮盖力不够时多用一点白墨
            压住底色，更贴近实际印出来的效果。不传则完全等价于旧版本。

        配方精简（simplify）：
            工业现场不希望"为了把ΔE压低0.3而多用一种权重只有1%的墨"
            ——这种极小比例现场几乎没法准确称量，反而增加操作复杂度
            和出错概率。默认开启的精简逻辑会在保证ΔE不明显变差的前提
            下，贪心地尝试去掉权重很小、贡献可有可无的油墨，优先给出
            "够用的最少种类配方"而不是"库里勾选的墨全部用一遍"。
        """
        white_codes = white_codes or []
        candidates = list(candidate_codes)
        white_auto_triggered = False
        warning = None

        target_L = target_lab[0]
        has_white_selected = any(c in white_codes for c in candidates)

        if target_L >= self.WHITE_TRIGGER_L_THRESHOLD and not has_white_selected:
            # 自动挑选库存中"遮盖力"（这里以S散射系数均值近似代表遮盖力）最高的白墨
            best_white = None
            best_scattering = -1.0
            for code in white_codes:
                if code in self.ink_library:
                    ink = self.ink_library[code]
                    avg_s = float(np.mean(ink.S))
                    if avg_s > best_scattering:
                        best_scattering = avg_s
                        best_white = code
            if best_white is not None:
                candidates.append(best_white)
                white_auto_triggered = True
                warning = f"目标色偏浅，系统已自动加入高遮盖白墨 [{best_white}] 参与寻优"

        candidates = [c for c in candidates if c in self.ink_library]
        if not candidates:
            raise ValueError("候选油墨列表为空，无法进行配方寻优，请至少勾选一种在库油墨。")

        final_weights = self._optimize(candidates, target_lab, substrate_lab, material_props)

        # 中性色（黑/白/灰）实用性修正：
        # 求解器有时会为了把 ΔE 压低一点点，给纯黑/纯灰配出"橙+蓝混黑"这种
        # 数学最优但现场很荒谬的配方——没有师傅会用橙加蓝去调黑色。
        # 如果目标是中性色，而库里就有黑墨/白墨，且"直接用黑墨/白墨"的色差
        # 跟花哨混色差不多（在同一档次），就改用简单的纯墨方案：现场好操作、
        # 好复现、不容易出错，这比多压那零点几个 ΔE 重要得多。
        neutral_weights = self._prefer_neutral_ink(
            target_lab, candidates, final_weights, substrate_lab, material_props
        )
        if neutral_weights is not None:
            final_weights = neutral_weights

        ink_count_simplified = False
        if simplify and len(final_weights) > 1:
            simplified_weights, was_simplified = self._simplify_formula(
                final_weights, target_lab, substrate_lab, simplify_tolerance,
                min_practical_weight, material_props
            )
            if was_simplified:
                final_weights = simplified_weights
                ink_count_simplified = True

        predicted_lab = self.compute_apparent_lab(
            final_weights, substrate_lab, apply_dry_back=True, material_props=material_props
        )
        delta_e = self.delta_e_76(predicted_lab, target_lab)
        opacity_estimate = self.estimate_opacity(final_weights, material_props)

        if delta_e > self.DELTA_E_WARNING_THRESHOLD:
            # 先判断一种特殊而常见的情况：目标是"数字纯白/纯黑"。
            # 设计稿（AI/PS导出的PDF）里的白通常是 L*=100（屏幕纯白 255,255,255），
            # 黑通常是 L*≈0~5（屏幕纯黑）。但任何真实油墨都印不出屏幕的纯白纯黑——
            # 最白的白墨物理极限约 L*95，最黑的黑墨约 L*16。这是颜料的物理规律，
            # 不是配方没配好。这种情况下已经用对了墨（就是白墨/黑墨本身），
            # 不该报"配不出、建议加红墨"这种吓人又误导的警告。
            special = self._diagnose_white_black_limit(target_lab, final_weights)
            if special:
                warning = f"{warning}；{special}" if warning else special
            else:
                de_warning = f"警告：预测配方色差 ΔE={delta_e:.2f} 超过工业容差阈值 {self.DELTA_E_WARNING_THRESHOLD}"
                # 配不出来时，别只甩一个色差数字——诊断到底为什么调不出、缺什么、怎么办。
                # 这直接回应"工厂能调出、系统调不出"的困惑：多半是可用油墨不够。
                diagnosis = self._diagnose_gamut_miss(target_lab, candidates)
                if diagnosis:
                    de_warning = f"{de_warning}。{diagnosis}"
                warning = f"{warning}；{de_warning}" if warning else de_warning

        if substrate_lab is not None and opacity_estimate < 0.7:
            mat_label = (material_props or {}).get("label", "该承印物")
            cover_warning = (
                f"提示：在【{mat_label}】上，当前配方遮盖力估算约{opacity_estimate*100:.0f}%，"
                f"底色可能会透出影响实际效果，建议增加白墨占比或先打一层白底"
            )
            warning = f"{warning}；{cover_warning}" if warning else cover_warning

        # 附着力风险：这是"能不能印"的问题，比"颜色准不准"更要命，必须提前说
        if material_props:
            adhesion = material_props.get("adhesion_factor", 1.0) or 1.0
            if adhesion < 0.80:
                mat_label = material_props.get("label", "该材质")
                pretreat = material_props.get("pretreatment", "请查阅材质说明")
                adh_warning = (
                    f"⚠️ 掉墨风险：【{mat_label}】附着力系数仅 {adhesion:.2f}，"
                    f"不做前处理油墨会刮掉。前处理要求：{pretreat}"
                )
                warning = f"{warning}；{adh_warning}" if warning else adh_warning

        return FormulaResult(
            weights=final_weights,
            predicted_lab=predicted_lab,
            delta_e=delta_e,
            white_auto_triggered=white_auto_triggered,
            warning=warning,
            opacity_estimate=opacity_estimate,
            ink_count_simplified=ink_count_simplified,
        )

    def _prefer_neutral_ink(self, target_lab, candidates, opt_weights,
                            substrate_lab, material_props):
        """
        目标是中性色（黑/白/灰）时，优先用单一黑墨或白墨的简单方案。

        返回替换后的权重字典；如果不适用（目标不是中性色、库里没黑/白墨、
        或纯墨方案色差明显更差），返回 None 表示保持优化器的原方案。
        """
        try:
            L, a, b = target_lab
            chroma = (a * a + b * b) ** 0.5
            if chroma > 6:
                return None   # 有明显颜色，不是中性色，不干预

            # 目标偏黑找黑墨，偏白找白墨，中灰两者都试
            picks = []
            for code in candidates:
                ink = self.ink_library.get(code)
                if ink is None:
                    continue
                name = ink.name
                is_black = ("黑" in name or "black" in name.lower())
                is_white = (getattr(ink, "category", "") == "white"
                            or "白" in name or "white" in name.lower())
                if L <= 35 and is_black:
                    picks.append(code)
                elif L >= 70 and is_white:
                    picks.append(code)

            if not picks:
                return None

            # 优化器方案的色差
            opt_lab = self.compute_apparent_lab(opt_weights, substrate_lab,
                                                apply_dry_back=True, material_props=material_props)
            opt_de = self.delta_e_76(opt_lab, target_lab)

            # 逐个试纯墨方案，取最好的
            best_code, best_de = None, None
            for code in picks:
                lab = self.compute_apparent_lab({code: 1.0}, substrate_lab,
                                                apply_dry_back=True, material_props=material_props)
                de = self.delta_e_76(lab, target_lab)
                if best_de is None or de < best_de:
                    best_de, best_code = de, code

            if best_code is None:
                return None

            # 纯墨方案只要"没有明显更差"（放宽 2.5 个 ΔE 的余量），就采用它，
            # 因为它的现场实用性远胜过那点色差优势——而且黑/白本来就受物理极限
            # 限制，混色也压不下去多少。
            margin = 2.5
            # 特殊情况：目标是【极端】中性黑/白（数字纯黑纯白，如设计稿里的
            # 0,0,0 或 255,255,255）。这时优化器可能用花哨混色（如橙+蓝调黑）
            # 把 L* 压得更接近，数学 ΔE 更低——但在纯黑/纯白区域，这点 L* 差异
            # 肉眼根本分辨不出，而"橙+蓝调黑"会让现场师傅完全懵掉。所以极端
            # 中性色无条件优先纯墨，放宽余量到 10。
            if L <= 12 or L >= 93:
                margin = 10.0
            if best_de <= opt_de + margin:
                return {best_code: 1.0}
            return None
        except Exception:
            return None

    def _diagnose_white_black_limit(self, target_lab: tuple, weights: Dict[str, float]) -> str:
        """
        判断"配不出"是不是因为目标是数字纯白/纯黑（超出油墨物理极限）。

        如果是，返回一句正确的、不吓人的解释；否则返回空串（让常规诊断接手）。

        判断只看【目标本身】：
          · 彩度很低（a*、b* 都接近 0，是中性色）
          · 且 L* 极高（→数字纯白）或极低（→数字纯黑）

        为什么不看"配方主力是不是白墨/黑墨"：因为求解器可能发现别的组合更接近。
        比如配纯黑(L*4)时，橙+射光蓝混出的深色(L*9.7)居然比纯黑墨(L*17)更黑、
        更接近目标——求解器选它没错。但根本矛盾还是"设计稿用了油墨印不出的数字
        纯黑"，所以只要目标是数字纯白/纯黑，就该给这个解释，跟用什么墨配无关。
        """
        try:
            L, a, b = target_lab
            chroma = (a * a + b * b) ** 0.5
            if chroma > 8:
                return ""   # 有明显颜色，不是纯白/纯黑

            # 目标偏白：L* 极高（设计稿数字纯白通常 L*≈100）
            if L >= 90:
                return (f"目标是接近纯白（L*={L:.0f}）。任何油墨都印不出屏幕上的纯白——"
                        f"最白的白墨物理极限约 L*95，而设计稿里的白通常是 L*100（数字纯白），"
                        f"这 5 个点的差距就是全部色差来源。这不是配方问题：实际印刷中，"
                        f"白色部分直接用白墨即可；若承印物本身就是白色，这里甚至可以留白不印")

            # 目标偏黑：L* 极低（设计稿数字纯黑通常 L*≈0~5）
            if L <= 20:
                return (f"目标是接近纯黑（L*={L:.0f}）。任何油墨都印不出屏幕上的纯黑——"
                        f"最黑的黑墨物理极限约 L*16，而设计稿里的黑通常是 L*0~5（数字纯黑），"
                        f"这点差距就是全部色差来源。这不是配方问题：实际印刷中直接用黑墨即可，"
                        f"印出来就是肉眼认可的黑")
            return ""
        except Exception:
            return ""

    def _diagnose_gamut_miss(self, target_lab: tuple, candidates: List[str]) -> str:
        """
        配不出目标色时，诊断到底为什么、缺什么、怎么办。

        这是问题2的答案。"工厂能调出、系统调不出"，绝大多数情况是因为：
        系统里可用的油墨（用户勾选的那几支）太少，而工厂师傅手边有几十种
        专色墨随便挑。诊断分两种情况：

          1. 可用油墨本来就少（≤5支）：先建议把库里其他墨也勾上试试
          2. 目标色的饱和度/色相超出了所有可用油墨能达到的包络：这是真的
             色域不够，需要添加某个方向的高饱和专色墨——并说清是哪个方向

        返回一句给用户看的、可操作的话。诊断不出明确原因就返回空串。
        """
        try:
            L0, a0, b0 = target_lab
            # 目标色的彩度（离中性灰有多远）
            target_chroma = (a0 * a0 + b0 * b0) ** 0.5

            # 看看可用油墨里，每支纯色能到达的 Lab，圈出可用色域的边界
            reachable = []
            for code in candidates:
                ink = self.ink_library.get(code)
                if ink is None:
                    continue
                lab = self.compute_apparent_lab({code: 1.0}, None, apply_dry_back=False)
                reachable.append((code, lab))

            if not reachable:
                return ""

            # 可用油墨里最高的彩度
            max_reach_chroma = max(
                (la[1] ** 2 + la[2] ** 2) ** 0.5 for _, la in reachable
            )

            n = len(candidates)
            # 情况1：可用油墨太少
            if n <= 5:
                return (f"当前只勾选了 {n} 种油墨，可调色域有限。"
                        f"工厂能调出是因为手边专色墨多——建议先把油墨库里其他颜色也勾上再试，"
                        f"尤其是和目标色相近的专色墨")

            # 情况2：目标饱和度超出可用油墨包络
            if target_chroma > max_reach_chroma + 5:
                # 判断目标偏哪个方向，指名道姓建议加什么墨
                direction = self._chroma_direction(a0, b0)
                return (f"目标色饱和度（彩度{target_chroma:.0f}）超出了现有油墨能达到的范围"
                        f"（最高约{max_reach_chroma:.0f}）。这是真正的色域限制，靠现有墨调不出——"
                        f"建议添加一支高饱和的{direction}专色墨")

            # 情况3：够得到饱和度，但配不准（可能缺某个色相的墨）
            direction = self._chroma_direction(a0, b0)
            return (f"现有油墨勉强够到这个饱和度，但色相配不准。"
                    f"建议补一支更接近目标的{direction}方向专色墨，或检查是否勾选了合适的基色")
        except Exception:
            return ""

    @staticmethod
    def _chroma_direction(a: float, b: float) -> str:
        """根据 a*/b* 判断颜色大致偏哪个方向，用于建议添加什么墨。"""
        import math
        # 色相角
        hue = math.degrees(math.atan2(b, a)) % 360
        if hue < 20 or hue >= 340:
            return "红"
        if hue < 50:
            return "橙红"
        if hue < 75:
            return "橙黄"
        if hue < 105:
            return "黄"
        if hue < 150:
            return "黄绿"
        if hue < 195:
            return "绿"
        if hue < 240:
            return "青蓝"
        if hue < 285:
            return "蓝"
        if hue < 320:
            return "紫"
        return "品红"

    def _optimize(
        self,
        candidates: List[str],
        target_lab: tuple,
        substrate_lab: Optional[tuple],
        material_props: Optional[Dict] = None,
    ) -> Dict[str, float]:
        """
        对给定候选墨集合做多起点SLSQP寻优，返回清理过数值噪声的权重字典。

        性能说明：候选墨越多，起点也越多（均分+每种墨单独100%的n个顶点）。
        如果每个起点都跑到完全收敛（maxiter=200），候选墨到十几种时总耗时
        会拖到几秒甚至更久，界面上感觉像卡死。这里改成两阶段：
            阶段一"粗筛"：所有起点都用很低的maxiter快速跑一遍，只是为了
                找到"看起来最有希望"的那个起点，不追求完全收敛。
            阶段二"精修"：只对粗筛胜出的那一个起点，用完整maxiter重新
                跑一次，保证最终结果依然是充分收敛的精确解。
        这样总耗时从"起点数 × 完整收敛成本"降到"起点数 × 粗筛成本 +
        1次完整收敛成本"，候选墨多的时候效果尤其明显。
        """
        n = len(candidates)

        def objective(w):
            weights = {code: float(w[i]) for i, code in enumerate(candidates)}
            lab = self.compute_apparent_lab(
                weights, substrate_lab, apply_dry_back=True, material_props=material_props
            )
            return self.delta_e_76(lab, target_lab)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 1.0) for _ in range(n)]

        start_points = [np.ones(n) / n]
        vertex_indices = list(range(n))
        if n > 8:
            # 候选墨很多时，没必要把所有n个顶点都当粗筛起点——按"这支墨
            # 单独的颜色离目标色有多远"粗排一下，只挑最有希望的一部分
            # （加上目标本来就等价于"贴着某支墨的原色去微调"的情况，
            # 排序越靠前的顶点越可能是精修阶段真正需要的起点）。
            def _single_ink_distance(idx):
                code = candidates[idx]
                ink = self.ink_library[code]
                lab = self.compute_apparent_lab(
                    {code: 1.0}, substrate_lab, apply_dry_back=True, material_props=material_props
                )
                return self.delta_e_76(lab, target_lab)
            vertex_indices = sorted(range(n), key=_single_ink_distance)[:8]

        for i in vertex_indices:
            vertex = np.zeros(n)
            vertex[i] = 1.0
            start_points.append(vertex)

        # ---- 阶段一：粗筛（低maxiter，只为了挑出最有希望的起点） ----
        screen_maxiter = 30 if n > 6 else 200  # 候选少的时候没必要省，直接跑到底最简单可靠
        best_x0 = start_points[0]
        best_screen_de = float("inf")
        for x0 in start_points:
            result = minimize(
                objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
                options={"maxiter": screen_maxiter, "ftol": 1e-9},
            )
            if result.fun < best_screen_de:
                best_screen_de = result.fun
                best_x0 = result.x  # 直接拿粗筛跑出的中间解作为精修起点，比原始顶点更接近答案

        # ---- 阶段二：精修（完整maxiter，保证充分收敛） ----
        final_result = minimize(
            objective, best_x0, method="SLSQP", bounds=bounds, constraints=constraints,
            options={"maxiter": 200, "ftol": 1e-9},
        )

        final_weights = {candidates[i]: max(0.0, float(final_result.x[i])) for i in range(n)}
        final_weights = {k: (v if v >= 0.001 else 0.0) for k, v in final_weights.items()}
        total = sum(final_weights.values())
        if total > 0:
            final_weights = {k: v / total for k, v in final_weights.items()}
        return final_weights

    def _simplify_formula(
        self,
        weights: Dict[str, float],
        target_lab: tuple,
        substrate_lab: Optional[tuple],
        tolerance: float,
        min_practical_weight: float,
        material_props: Optional[Dict] = None,
    ) -> tuple:
        """
        贪心地尝试去掉权重很小、现场基本没法准确称量的油墨，
        只要去掉后重新寻优的ΔE没有明显变差（增幅不超过tolerance），
        就采用精简后的配方，尽量减少配方里的油墨种类数。

        性能说明：候选油墨较多时，如果每一步剔除尝试都用完整的多起点
        SLSQP搜索（_optimize），总耗时会随候选数量近似三次方增长，
        17种候选墨实测能卡到20秒以上，界面上跟卡死没区别。这里改用
        "warm-start单次优化"——剔除某支墨后，直接拿"去掉它、把它的
        权重按比例分给其余油墨"的结果作为SLSQP的唯一起点重新求解，
        而不是从n个顶点重新search一遍，把每一步的开销从O(n)次SLSQP
        降到O(1)次，实测复杂度从三次方降到接近线性。
        """
        current_weights = dict(weights)
        baseline_lab = self.compute_apparent_lab(
            current_weights, substrate_lab, apply_dry_back=True, material_props=material_props
        )
        baseline_de = self.delta_e_76(baseline_lab, target_lab)
        was_simplified = False

        while True:
            active_codes = [c for c, w in current_weights.items() if w > 0]
            if len(active_codes) <= 1:
                break

            candidate_to_remove = min(active_codes, key=lambda c: current_weights[c])
            if current_weights[candidate_to_remove] >= min_practical_weight:
                break

            trial_codes = [c for c in active_codes if c != candidate_to_remove]
            trial_weights = self._reoptimize_warm_start(
                trial_codes, current_weights, target_lab, substrate_lab, material_props
            )
            trial_lab = self.compute_apparent_lab(
                trial_weights, substrate_lab, apply_dry_back=True, material_props=material_props
            )
            trial_de = self.delta_e_76(trial_lab, target_lab)

            if trial_de <= baseline_de + tolerance:
                current_weights = trial_weights
                baseline_de = trial_de
                was_simplified = True
            else:
                break

        return current_weights, was_simplified

    def _reoptimize_warm_start(
        self,
        candidates: List[str],
        previous_weights: Dict[str, float],
        target_lab: tuple,
        substrate_lab: Optional[tuple],
        material_props: Optional[Dict] = None,
    ) -> Dict[str, float]:
        """用"剔除某支墨、剩余按比例归一"作为唯一起点做单次SLSQP，供精简步骤内部使用（快）。"""
        n = len(candidates)

        def objective(w):
            weights = {code: float(w[i]) for i, code in enumerate(candidates)}
            lab = self.compute_apparent_lab(
                weights, substrate_lab, apply_dry_back=True, material_props=material_props
            )
            return self.delta_e_76(lab, target_lab)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 1.0) for _ in range(n)]

        raw_x0 = np.array([previous_weights.get(c, 0.0) for c in candidates])
        total = raw_x0.sum()
        x0 = raw_x0 / total if total > 1e-6 else np.ones(n) / n

        result = minimize(
            objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
            options={"maxiter": 150, "ftol": 1e-9},
        )
        final_weights = {candidates[i]: max(0.0, float(result.x[i])) for i in range(n)}
        final_weights = {k: (v if v >= 0.001 else 0.0) for k, v in final_weights.items()}
        total = sum(final_weights.values())
        if total > 0:
            final_weights = {k: v / total for k, v in final_weights.items()}
        return final_weights

    def weights_to_grams(self, weights: Dict[str, float], total_grams: float) -> Dict[str, float]:
        """将百分比权重换算为实际称重克数（供UI表格与天平称量目标使用）。"""
        return {code: round(w * total_grams, 3) for code, w in weights.items() if w > 0}
