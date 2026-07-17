# -*- coding: utf-8 -*-
"""
main.py
========
墨算 (InkMatrix) 智能调色系统 —— 程序入口。

启动方式：
    python main.py

架构总览：
    dal_layer  数据访问层  —— data/inks_db.json, data/bottles_db.json 的CRUD
    core_layer 核心算法层  —— 非线性 Kubelka-Munk (K-M) 配色引擎
    hal_layer  硬件抽象层  —— AbstractScale / AbstractDispenser 标准硬件接口
    ui_layer   表现/业务层 —— PyQt6 三区工业界面 + QThread 闭环控制
"""

from ui_layer.main_window import run_app

if __name__ == "__main__":
    run_app()
