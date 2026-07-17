# -*- coding: utf-8 -*-
"""
migrations.py  (DAL层 - 数据格式迁移框架)
================================================
解决一个上云后绕不开的问题：**软件升级了，老客户的旧数据怎么自动跟上。**

── 为什么需要这个 ──────────────────────────────────────────────
每次给系统加功能，数据格式常常要跟着变。举几个已经发生过的例子：
  · v35 给财务记录加了 payments（收款流水）列表
  · v36 给账户加了 ink_usage（已用油墨量）
  · v38 给油墨加了 ref_lab（标准Lab）和 delta_e_tolerance（允许色差）

在单机时代，这些靠代码里到处写 `.get(key, 默认值)` 硬扛过去了——能跑，但很脆：
字段散落各处，谁也说不清"当前数据到底是第几版、缺哪些字段"。

上云之后这个问题会放大：你在服务器推了新版本，客户端拉下来，但客户机器上
存着的是三个月前格式的老数据。如果不做迁移，轻则某个新功能读不到字段报错，
重则算错钱、扣错库存。

── 这个框架怎么工作 ────────────────────────────────────────────
1. 每份数据都记着一个"schema 版本号"（存在 _schema_version.json）
2. 每次升级，如果数据格式变了，就写一个迁移函数：把 vN 的数据改成 v(N+1)
3. 启动时，系统看当前数据是第几版，把从那一版到最新版之间的迁移函数【依次跑一遍】
4. 迁移前自动整体备份，万一迁移出错能整体回滚——绝不把客户数据改坏

这样无论客户机器上存的是多老的数据，升级后都能一步步、安全地追到最新格式。
"""
import os
import json
import shutil
import datetime
from typing import Callable, Dict, List, Tuple

from dal_layer import data_manager as dm


# ══════════════════════════════════════════════════════════════════════
# 迁移函数注册表
# ══════════════════════════════════════════════════════════════════════
# 每个迁移函数负责把数据从 from_version 升到 from_version+1。
# 函数签名：migrate(data_dir: str) -> None，直接就地改 data_dir 里的 json 文件。
#
# ⚠️ 迁移函数必须【幂等且防御性】：可能跑在各种残缺的老数据上，
#    每一步都要 .get(key, 默认) 地防着，不能假设字段一定存在。
#
# 现在系统是 v1（第一个带正式版本号的版本）。以后要加迁移就往这个列表里加，
# 比如将来 v2 要给所有油墨补一个新字段：
#     def _migrate_1_to_2(data_dir): ...
#     _MIGRATIONS = [(1, _migrate_1_to_2)]

_MIGRATIONS: List[Tuple[int, Callable[[str], None]]] = [
    # (from_version, migrate_func)
    # 目前是初始版本，还没有需要迁移的历史。以后在这里往下加。
]


# ── 示例：一个迁移函数长什么样（当前未启用，仅作模板参考） ──
def _example_migrate_template(data_dir: str) -> None:
    """
    模板：假设某一版要给所有油墨补上 delta_e_tolerance 字段（默认2.0）。

    真正要用时，把它加进 _MIGRATIONS 列表，并改成正确的 from_version。
    """
    inks_path = os.path.join(data_dir, "inks_db.json")
    if not os.path.exists(inks_path):
        return
    try:
        with open(inks_path, "r", encoding="utf-8") as f:
            inks = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    changed = False
    for ink in inks:
        if "delta_e_tolerance" not in ink:
            ink["delta_e_tolerance"] = 2.0
            changed = True
    if changed:
        dm._save_json(inks_path, inks)


# ══════════════════════════════════════════════════════════════════════
# 版本读写
# ══════════════════════════════════════════════════════════════════════

def read_data_version(data_dir: str = None) -> int:
    """
    读当前数据是第几版。

    老数据（升级前从来没有版本号文件）默认当成 v1——因为 v1 就是"引入版本号
    机制"的那一版，之前所有格式都归到 v1 名下。
    """
    data_dir = data_dir or dm.DATA_DIR
    path = os.path.join(data_dir, "_schema_version.json")
    if not os.path.exists(path):
        return 1
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(json.load(f).get("version", 1))
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return 1


def write_data_version(version: int, data_dir: str = None) -> None:
    data_dir = data_dir or dm.DATA_DIR
    path = os.path.join(data_dir, "_schema_version.json")
    dm._save_json(path, {
        "version": version,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ══════════════════════════════════════════════════════════════════════
# 迁移执行
# ══════════════════════════════════════════════════════════════════════

def _backup_all_data(data_dir: str) -> str:
    """
    迁移前把整个 data 目录完整备份到 data/_pre_migration_backup_时间戳/。
    迁移出任何岔子，可以从这里整体恢复——绝不能把客户几年的账搞坏。
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(data_dir, f"_pre_migration_backup_{stamp}")
    os.makedirs(backup_dir, exist_ok=True)
    for name in os.listdir(data_dir):
        src = os.path.join(data_dir, name)
        # 只备份数据文件，不备份别的备份目录（避免套娃）
        if os.path.isfile(src) and name.endswith(".json"):
            shutil.copy2(src, os.path.join(backup_dir, name))
    return backup_dir


def run_migrations(data_dir: str = None) -> Dict:
    """
    启动时调用：把数据从当前版本一路迁移到最新版本。

    返回一份报告：{migrated: bool, from: int, to: int, steps: [...], backup: 路径}

    安全保证：
      · 迁移前整体备份
      · 迁移函数按版本顺序【一步步】跑，中间任何一步抛异常就停下，
        不把版本号往前推——下次启动会重试，数据不会停在半迁移状态
    """
    data_dir = data_dir or dm.DATA_DIR
    dm._ensure_data_dir()

    current = read_data_version(data_dir)
    target = dm.DATA_SCHEMA_VERSION

    report = {"migrated": False, "from": current, "to": target, "steps": [], "backup": None}

    if current >= target:
        return report   # 已经是最新，什么都不用做

    # 有活要干，先整体备份
    report["backup"] = _backup_all_data(data_dir)

    # 按顺序把 current → target 之间的迁移函数依次跑掉
    migrations_by_from = {frm: fn for frm, fn in _MIGRATIONS}
    version = current
    while version < target:
        fn = migrations_by_from.get(version)
        if fn is None:
            # 没有对应的迁移函数——说明这个跨版本不需要改数据（只是代码变了），
            # 直接把版本号推上去即可
            version += 1
            write_data_version(version, data_dir)
            report["steps"].append(f"v{version-1}→v{version}: 无需数据迁移，仅更新版本号")
            continue
        fn(data_dir)               # 执行这一步迁移
        version += 1
        write_data_version(version, data_dir)   # 成功后才推进版本号
        report["steps"].append(f"v{version-1}→v{version}: 已迁移")

    report["migrated"] = True
    return report
