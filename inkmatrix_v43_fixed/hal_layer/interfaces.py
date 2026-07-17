# -*- coding: utf-8 -*-
"""
interfaces.py  (HAL层 - 硬件抽象层)
====================================
墨算 (InkMatrix) 智能调色系统 —— 硬件抽象层。

本层是"软硬件解耦"的核心：上层（UI/BLL）只依赖 AbstractScale 与
AbstractDispenser 两个抽象基类编程，不关心底层到底是仿真器、串口天平，
还是 PLC 控制的伺服泵组。未来只需新增一个真实驱动的子类实现，
即可无缝切换到全自动产线，UI层与核心算法层代码无需任何改动。

标准工业驱动接入方式（未来接入真实硬件时）：
    - 电子天平：多为 RS232/RS485 串口通信，常见协议如 "1S\\r\\n" 请求稳定重量，
      "T\\r\\n" 去皮指令，需在 SerialScale 子类中实现。
    - 泵组执行器：多通过 PLC (如西门子S7-1200/汇川/信捷) 经 Modbus-TCP
      写入保持寄存器(Holding Register)来控制变频器转速/电磁阀开关。
"""

import time
import random
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Callable


# ============================================================
# 一、电子天平抽象基类
# ============================================================

class AbstractScale(ABC):
    """
    电子天平驱动抽象基类。

    所有具体天平实现（串口天平 / 网络天平 / 仿真天平）必须继承此类，
    并实现下列三个标准接口，保证上层调用方式完全一致。
    """

    @abstractmethod
    def connect_scale(self, port_params: dict) -> bool:
        """
        建立与天平的通信连接（串口或网络）。

        Args:
            port_params: 连接参数字典，例如
                {"port": "COM3", "baudrate": 9600, "parity": "N", "timeout": 1}
                或网络天平的 {"ip": "192.168.1.50", "tcp_port": 502}

        Returns:
            bool: 连接是否成功
        """
        raise NotImplementedError

    @abstractmethod
    def get_stable_weight(self) -> float:
        """
        获取天平当前稳定重量读数（克）。

        工业现场天平信号常有抖动，实现类内部应包含滤波/稳定性判定算法
        （例如连续N次采样方差小于阈值才视为"稳定"），避免误读波动数据。

        Returns:
            float: 稳定重量读数（单位：克）
        """
        raise NotImplementedError

    @abstractmethod
    def tare(self) -> None:
        """发送天平去皮（清零）指令。"""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """断开天平连接，释放串口/网络资源。"""
        raise NotImplementedError


class SimulatedScale(AbstractScale):
    """
    仿真电子天平实现。

    用于在没有真实硬件的开发/演示阶段，模拟"人工/自动加料时重量
    随时间递增"的动态过程，供上层闭环轮询逻辑联调测试。
    """

    def __init__(self):
        self._connected = False
        self._current_weight = 0.0
        self._target_weight = 0.0
        self._fill_rate = 0.0  # 克/秒，由外部（Dispenser仿真）动态设置
        self._lock = threading.Lock()
        self._noise_amplitude = 0.02  # 模拟天平读数抖动

    def connect_scale(self, port_params: dict) -> bool:
        # ====== 工业校对点：未来在此处写入真实 RS232 串口天平通信命令 (例如 self.ser.write(b'1S\r\n')) ======
        # 真实实现应在此处打开串口 (pyserial: serial.Serial(port, baudrate, ...))
        # 并校验天平返回的握手信号，确认通信正常后再返回 True。
        time.sleep(0.05)  # 模拟连接握手耗时
        self._connected = True
        return True

    def get_stable_weight(self) -> float:
        # ====== 工业校对点：未来在此处写入真实 RS232 串口天平通信命令 (例如 self.ser.write(b'1S\r\n')) ======
        # 真实实现应发送取重指令并解析返回帧（如 "ST,+00123.45g\r\n"），
        # 并对连续多帧读数做稳定性判定（标准差 < 阈值 视为稳定），
        # 只有判定"稳定"后才返回读数，避免动态抖动导致的误判。
        with self._lock:
            noise = random.uniform(-self._noise_amplitude, self._noise_amplitude)
            return round(self._current_weight + noise, 3)

    def tare(self) -> None:
        # ====== 工业校对点：未来在此处写入真实 RS232 串口天平通信命令 (例如 self.ser.write(b'1S\r\n')) ======
        with self._lock:
            self._current_weight = 0.0

    def disconnect(self) -> None:
        self._connected = False

    # ---- 以下为仿真专用内部方法，非抽象接口的一部分 ----

    def _set_fill_rate(self, grams_per_second: float) -> None:
        """由 SimulatedDispenser 调用，模拟当前流速对重量的影响。"""
        with self._lock:
            self._fill_rate = grams_per_second

    def _tick(self, dt: float) -> None:
        """由后台线程周期性调用，推进仿真重量增长。"""
        with self._lock:
            self._current_weight += self._fill_rate * dt
            if self._current_weight < 0:
                self._current_weight = 0.0


# ============================================================
# 二、多通道注墨执行器抽象基类
# ============================================================

class DispenseStage(Enum):
    """三段式滴定状态机的三个阶段。"""
    IDLE = "空闲"
    FAST_FILL = "高流速快冲"
    PWM_SLOW = "临界点PWM降速"
    CLOSED_COMPENSATE = "提前闭阀补偿"
    DONE = "完成"
    ABORTED = "急停中止"




# 状态机转移表：定义合法的状态转移（工业级安全）
_VALID_STATE_TRANSITIONS = {
    DispenseStage.IDLE: [DispenseStage.FAST_FILL],
    DispenseStage.FAST_FILL: [DispenseStage.PWM_SLOW, DispenseStage.ABORTED],
    DispenseStage.PWM_SLOW: [DispenseStage.CLOSED_COMPENSATE, DispenseStage.ABORTED],
    DispenseStage.CLOSED_COMPENSATE: [DispenseStage.DONE, DispenseStage.ABORTED],
    DispenseStage.DONE: [DispenseStage.IDLE],
    DispenseStage.ABORTED: [DispenseStage.IDLE],
}

def validate_state_transition(from_state: DispenseStage, to_state: DispenseStage) -> bool:
    """
    P0-3: 状态转移安全检查。
    
    只允许预定义的合法转移，防止无效的状态跳转（工业软件必须项）。
    """
    allowed_next = _VALID_STATE_TRANSITIONS.get(from_state, [])
    return to_state in allowed_next


class AbstractDispenser(ABC):
    """
    多通道注墨执行器抽象基类。

    定义工业级"三段式滴定"注墨控制逻辑接口：
        1. 高流速快冲：远离目标值时，泵以最大流速供墨，提升效率。
        2. 临界点PWM降速：接近目标值时，通过PWM占空比调节阀门/泵速，
           防止冲量过大导致超重。
        3. 提前闭阀切断：由于阀门关闭到实际停止出墨之间存在"空中余墨
           下落"的滞后量，需提前一定量关闭阀门，以实际落地重量命中目标。
    """

    @abstractmethod
    def check_safety_gate(self) -> bool:
        """
        工业防呆安全检查。

        典型检查项：
            - 天平托盘上是否检测到调墨桶（防止对空桶注墨/墨液溅出）
            - PLC 急停按钮是否处于"已复位"（未被按下）状态
            - 各阀门/泵的通信心跳是否正常

        Returns:
            bool: True 表示所有安全条件满足，可以执行注墨。
        """
        raise NotImplementedError

    @abstractmethod
    def dispense_pipeline(
        self,
        ink_code: str,
        target_grams: float,
        weight_reader: Callable[[], float],
        stage_callback: Optional[Callable[[DispenseStage, float], None]] = None,
        abort_flag: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        执行单个油墨通道的三段式滴定注墨流程。

        Args:
            ink_code: 油墨代码，用于选择对应的电磁阀/泵通道。
            target_grams: 该油墨的目标称重克数。
            weight_reader: 一个可调用对象，调用后返回当前天平实时重量
                           （闭环反馈用，通常由 AbstractScale.get_stable_weight 提供）。
            stage_callback: 阶段变化回调，用于UI显示当前处于哪个滴定阶段。
            abort_flag: 可调用对象，返回True时应立即中止（用于急停联动）。

        Returns:
            bool: 是否成功命中目标重量（在容差范围内）。
        """
        raise NotImplementedError

    @abstractmethod
    def emergency_stop(self) -> None:
        """
        紧急停止：强制切断所有硬件寄存器（关闭所有阀门/泵输出），
        无论当前处于哪个阶段，必须立即响应。
        """
        raise NotImplementedError


class SimulatedDispenser(AbstractDispenser):
    """
    仿真多通道注墨执行器。

    通过控制台打印 + 回调函数，模拟真实PLC泵组的三段式滴定过程，
    并驱动 SimulatedScale 的重量增长，形成完整的闭环仿真链路。
    """

    # 三段式滴定关键参数（工业现场常见经验值，可按实际泵组标定调整）
    FAST_FILL_RATE = 15.0        # 快冲阶段流速 g/s
    PWM_SLOW_RATE = 2.0          # PWM降速阶段流速 g/s
    SLOWDOWN_THRESHOLD_RATIO = 0.85   # 达到目标重量的85%时进入PWM降速
    AIR_DROP_COMPENSATION_GRAMS = 0.3  # 提前闭阀补偿量：预估空中余墨下落重量
    TOLERANCE_GRAMS = 0.05       # 允许的最终误差

    def __init__(self, scale: SimulatedScale):
        self._scale = scale
        self._safety_ok = True
        self._aborted = False
        self._current_stage = DispenseStage.IDLE

    def check_safety_gate(self) -> bool:
        # ====== 工业校对点：未来在此处写入真实 PLC Modbus-TCP 写入寄存器控制泵速的代码 ======
        # 真实实现应通过 Modbus-TCP 读取PLC输入寄存器状态：
        #   - 桶位检测传感器 (Discrete Input)
        #   - 急停按钮复位状态 (Discrete Input)
        # 例如使用 pymodbus: client.read_discrete_inputs(address, count)
        return self._safety_ok

    def dispense_pipeline(
        self,
        ink_code: str,
        target_grams: float,
        weight_reader: Callable[[], float],
        stage_callback: Optional[Callable[[DispenseStage, float], None]] = None,
        abort_flag: Optional[Callable[[], bool]] = None,
    ) -> bool:
        self._aborted = False

        if not self.check_safety_gate():
            self._current_stage = DispenseStage.ABORTED
            if stage_callback:
                stage_callback(DispenseStage.ABORTED, weight_reader())
            return False

        # ---------- 阶段一：高流速快冲 ----------
        self._current_stage = DispenseStage.FAST_FILL
        self._scale._set_fill_rate(self.FAST_FILL_RATE)
        # ====== 工业校对点：未来在此处写入真实 PLC Modbus-TCP 写入寄存器控制泵速的代码 ======
        # 例如: modbus_client.write_register(PUMP_SPEED_REGISTER[ink_code], FAST_FILL_SPEED_VALUE)
        if stage_callback:
            stage_callback(DispenseStage.FAST_FILL, weight_reader())

        slowdown_point = target_grams * self.SLOWDOWN_THRESHOLD_RATIO
        cutoff_point = target_grams - self.AIR_DROP_COMPENSATION_GRAMS

        while True:
            if abort_flag and abort_flag():
                self.emergency_stop()
                self._current_stage = DispenseStage.ABORTED
                if stage_callback:
                    stage_callback(DispenseStage.ABORTED, weight_reader())
                return False

            current_w = weight_reader()

            # ---------- 阶段二：临界点PWM降速 ----------
            if current_w >= slowdown_point and self._current_stage == DispenseStage.FAST_FILL:
                self._current_stage = DispenseStage.PWM_SLOW
                self._scale._set_fill_rate(self.PWM_SLOW_RATE)
                # ====== 工业校对点：未来在此处写入真实 PLC Modbus-TCP 写入寄存器控制泵速的代码 ======
                # 例如: modbus_client.write_register(PUMP_SPEED_REGISTER[ink_code], PWM_SLOW_SPEED_VALUE)
                if stage_callback:
                    stage_callback(DispenseStage.PWM_SLOW, current_w)

            # ---------- 阶段三：提前闭阀切断（补偿空中余墨下落量） ----------
            if current_w >= cutoff_point:
                self._scale._set_fill_rate(0.0)
                # ====== 工业校对点：未来在此处写入真实 PLC Modbus-TCP 写入寄存器控制泵速的代码 ======
                # 例如: modbus_client.write_register(VALVE_CONTROL_REGISTER[ink_code], VALVE_CLOSE)
                self._current_stage = DispenseStage.CLOSED_COMPENSATE
                if stage_callback:
                    stage_callback(DispenseStage.CLOSED_COMPENSATE, current_w)
                break

            time.sleep(0.1)  # 与UI 10Hz轮询节奏保持一致

        # 等待空中余墨完全落下并稳定（仿真：短暂延时后读数视为最终值）
        time.sleep(0.3)
        final_weight = weight_reader()
        self._current_stage = DispenseStage.DONE
        if stage_callback:
            stage_callback(DispenseStage.DONE, final_weight)

        return abs(final_weight - target_grams) <= self.TOLERANCE_GRAMS + 0.5

    def emergency_stop(self) -> None:
        # ====== 工业校对点：未来在此处写入真实 PLC Modbus-TCP 写入寄存器控制泵速的代码 ======
        # 真实实现必须以最高优先级立即写入所有泵/阀门的停止寄存器：
        #   for reg in ALL_PUMP_REGISTERS: modbus_client.write_register(reg, 0)
        self._scale._set_fill_rate(0.0)
        self._aborted = True
        self._safety_ok = False
        self._current_stage = DispenseStage.ABORTED

    def reset_safety(self) -> None:
        """急停复位后，人工确认现场安全，重新允许注墨。"""
        self._safety_ok = True
        self._aborted = False
        self._current_stage = DispenseStage.IDLE
