# -*- coding: utf-8 -*-
"""
worker.py  (UI层 - 后台工作线程)
==================================
全自动滴定模式下的后台执行线程。

使用 QThread + 信号槍机制，实现：
    - 以 10Hz（每秒10次）频率轮询 AbstractScale.get_stable_weight()
    - 依据实时重量反馈驱动 AbstractDispenser 的三段式滴定状态机
    - 通过Qt信号将阶段变化、重量变化、完成/异常状态回传给主线程UI

严禁在主线程中执行任何阻塞式硬件轮询循环，所有耗时操作必须在本线程内完成。

P0-1 修复：统一异常分类捕获，确保后台线程异常被正确处理和报告。
"""

import logging
from PyQt6.QtCore import QThread, pyqtSignal

from hal_layer.interfaces import AbstractScale, AbstractDispenser, DispenseStage

logger = logging.getLogger(__name__)
POLL_INTERVAL_HZ = 10  # 闭环轮询频率：10Hz


class AutoDispenseWorker(QThread):
    """全自动滴定后台线程。"""

    # 信号定义：(油墨代码, 阶段中文描述, 当前重量)
    stage_changed = pyqtSignal(str, str, float)
    # 信号定义：(油墨代码, 是否成功, 最终重量)
    ink_finished = pyqtSignal(str, bool, float)
    # 全部油墨滴定完成
    all_finished = pyqtSignal(bool)
    # 异常/急停信息
    error_occurred = pyqtSignal(str)

    def __init__(self, scale: AbstractScale, dispenser: AbstractDispenser,
                 grams_plan: dict, parent=None):
        """
        Args:
            scale: 天平硬件抽象接口实例
            dispenser: 注墨执行器硬件抽象接口实例
            grams_plan: {ink_code: target_grams} 待执行的分油墨称重目标序列
        """
        super().__init__(parent)
        self._scale = scale
        self._dispenser = dispenser
        self._grams_plan = grams_plan
        self._abort_requested = False

    def request_abort(self):
        """供主线程调用：请求急停中止当前后台任务。"""
        self._abort_requested = True

    def _is_aborted(self) -> bool:
        return self._abort_requested

    def run(self):
        """
        QThread 主执行体：按顺序对每一种油墨执行三段式滴定注墨。
        
        P0-1 修复：分类异常捕获
          - HardwareError: 硬件通信失败
          - ValueError: 参数校验失败
          - TimeoutError: 操作超时
          - Exception: 未分类的异常（最后兜底）
        """
        all_ok = True
        
        try:
            for ink_code, target_grams in self._grams_plan.items():
                if self._abort_requested:
                    all_ok = False
                    break

                try:
                    # 检查安全联锁
                    if not self._dispenser.check_safety_gate():
                        error_msg = f"安全联锁未通过：无法对 {ink_code} 执行注墨（请检查桶位/急停按钮）"
                        logger.error(error_msg)
                        self.error_occurred.emit(error_msg)
                        all_ok = False
                        break

                    # 每种油墨注墨前先去皮
                    self._scale.tare()

                    def stage_cb(stage: DispenseStage, weight: float, _code=ink_code):
                        self.stage_changed.emit(_code, stage.value, weight)

                    # 执行滴定管道
                    success = self._dispenser.dispense_pipeline(
                        ink_code=ink_code,
                        target_grams=target_grams,
                        weight_reader=self._scale.get_stable_weight,
                        stage_callback=stage_cb,
                        abort_flag=self._is_aborted,
                    )

                    final_weight = self._scale.get_stable_weight()
                    self.ink_finished.emit(ink_code, success, final_weight)

                    if not success:
                        all_ok = False
                        if self._abort_requested:
                            break

                # ===== P0-1: 分类异常处理 =====
                except ValueError as e:
                    error_msg = f"[参数错误] {ink_code}: {str(e)}"
                    logger.error(error_msg)
                    self.error_occurred.emit(error_msg)
                    all_ok = False
                    break
                    
                except TimeoutError as e:
                    error_msg = f"[超时错误] {ink_code}: 硬件响应超时 - {str(e)}"
                    logger.error(error_msg)
                    self.error_occurred.emit(error_msg)
                    all_ok = False
                    break
                    
                except Exception as e:
                    # 硬件通信错误 / 其他未分类错误
                    error_msg = f"[硬件异常] {ink_code}: {type(e).__name__}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    self.error_occurred.emit(error_msg)
                    all_ok = False
                    break

            self.all_finished.emit(all_ok)
            
        except Exception as e:
            # 最外层兜底：捕获循环层面的异常
            error_msg = f"[关键错误] 后台滴定线程发生意外异常: {type(e).__name__}: {str(e)}"
            logger.critical(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)
            self.all_finished.emit(False)


class ScaleTickWorker(QThread):
    """
    仿真专用：独立心跳线程，以10Hz频率驱动 SimulatedScale 内部重量演化（_tick）。

    真实硬件天平不需要此线程（天平内部自行更新重量，只需轮询读取），
    此线程仅用于让 SimulatedScale 的"人工加料模拟"在没有真实泵驱动时也能演化。
    """

    def __init__(self, scale, parent=None):
        super().__init__(parent)
        self._scale = scale
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        dt = 1.0 / POLL_INTERVAL_HZ
        while self._running:
            self._scale._tick(dt)
            self.msleep(int(dt * 1000))
