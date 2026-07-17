# -*- coding: utf-8 -*-
"""
data_manager.py  (DAL层 - 数据访问层)
======================================
负责本地 JSON 数据库文件的读写、维护与增删改查（CRUD）。

数据文件：
    data/inks_db.json     开放式油墨基因库（K/S光谱物理常数、密度、干燥系数等）
    data/bottles_db.json  承印物/瓶身底色库

设计原则：
    - DAL 层不感知任何色彩算法逻辑与UI逻辑，只做纯数据持久化，符合高内聚低耦合。
    - 对外暴露标准 CRUD 接口，供 UI 层随时录入工厂新采购的油墨/新承印物型号。
"""

import json
import os
import shutil
import datetime
import tempfile
import time
from typing import List, Dict, Optional

# 跨平台文件锁：Windows 用 msvcrt，Linux/Mac 用 fcntl。
# 上云服务器通常是 Linux，客户桌面通常是 Windows，两边都要能锁。
try:
    import fcntl  # Linux / macOS
    _LOCK_BACKEND = "fcntl"
except ImportError:
    try:
        import msvcrt  # Windows
        _LOCK_BACKEND = "msvcrt"
    except ImportError:
        _LOCK_BACKEND = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
INKS_DB_PATH = os.path.join(DATA_DIR, "inks_db.json")
BOTTLES_DB_PATH = os.path.join(DATA_DIR, "bottles_db.json")
COMPANY_INFO_PATH = os.path.join(DATA_DIR, "company_info.json")
PRODUCTS_DB_PATH = os.path.join(DATA_DIR, "products_db.json")
PRODUCTION_RECORDS_PATH = os.path.join(DATA_DIR, "production_records.json")
MACHINES_PATH = os.path.join(DATA_DIR, "machines.json")
INVENTORY_RECORDS_PATH = os.path.join(DATA_DIR, "inventory_records.json")
FINANCE_RECORDS_PATH = os.path.join(DATA_DIR, "finance_records.json")
INK_STOCK_RECORDS_PATH = os.path.join(DATA_DIR, "ink_stock_records.json")
USERS_PATH = os.path.join(DATA_DIR, "users.json")

# 数据格式版本号。以后字段结构变了，靠它判断老客户的数据要不要迁移。
DATA_SCHEMA_VERSION = 1
SCHEMA_VERSION_PATH = os.path.join(DATA_DIR, "_schema_version.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


class _FileLock:
    """
    跨平台文件锁上下文管理器。

    为什么需要：现在的存储是"读全部→改→写回全部"。两个账号（或上云后两个
    进程）如果同时做这件事，就会互相覆盖——实测 3 个账号各写 20 条，最后
    只剩 38 条，丢了 23 条。加一把锁，让同一时刻只有一个人能写，就不会丢。

    锁加在一个独立的 .lock 文件上（不是数据文件本身），这样锁的获取/释放
    不会干扰对数据文件的原子替换。
    """

    def __init__(self, target_path: str, timeout: float = 10.0):
        self.lock_path = target_path + ".lock"
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        if _LOCK_BACKEND is None:
            return self  # 平台不支持文件锁，降级为无锁（至少不崩）
        _ensure_data_dir()
        self._fh = open(self.lock_path, "w")
        deadline = time.time() + self.timeout
        while True:
            try:
                if _LOCK_BACKEND == "fcntl":
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:  # msvcrt
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except (OSError, IOError):
                if time.time() > deadline:
                    # 拿不到锁也别永久卡死——超时就放行，最坏退回到旧行为
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                if _LOCK_BACKEND == "fcntl":
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                else:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, IOError):
                pass
            self._fh.close()
            self._fh = None


def _load_json(path: str, default):
    """
    读 JSON。带【损坏自动恢复】：

    如果主文件读坏了（断电/崩溃留下半个文件），自动尝试从 .bak 备份恢复，
    而不是直接抛异常让整张表都读不出来。恢复不了才用默认值兜底，绝不让
    程序因为一个坏文件就起不来。
    """
    _ensure_data_dir()
    if not os.path.exists(path):
        _save_json(path, default)
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        # 主文件坏了。先把坏文件留个证据（改名 .corrupt），再试备份。
        try:
            shutil.copy2(path, path + ".corrupt")
        except OSError:
            pass
        bak = path + ".bak"
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 备份是好的，用它把主文件修回来
                _save_json(path, data)
                return data
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError):
                pass
        # 主文件和备份都救不回来，用默认值，至少让程序能启动
        return default


def _save_json(path: str, data):
    """
    写 JSON（整份覆盖）。三重保障，全部在存储层做掉，业务代码一行都不用改：

    1. 【原子写】：先写到同目录的临时文件，fsync 刷到磁盘，再用 os.replace
       原子地替换目标文件。os.replace 在同一文件系统上是原子操作——要么
       完全成功、要么完全没动，绝不会留下"写了一半"的残缺文件。

    2. 【自动备份】：替换之前，先把当前这份好数据复制成 .bak，供损坏时恢复。

    3. 【文件锁】：整个"备份→写临时→替换"串行化。

    ⚠️ 注意：这个函数只保证【单次写】是安全的。如果是"读全部→改→写回全部"
    这种复合操作（upsert/delete 都是），必须用 _update_json 把读改写整个锁起来，
    否则两个账号同时读到同一份、各自改、各自写回，还是会互相覆盖。
    """
    _ensure_data_dir()
    with _FileLock(path):
        _write_json_atomic(path, data)


def _write_json_atomic(path: str, data):
    """
    无锁的原子写内核（备份 + 临时文件 + fsync + 替换）。

    ⚠️ 它【不】自己加锁——调用方必须已经持有 _FileLock，否则并发不安全。
    这样拆开是为了让 _save_json（单次写）和 _update_json（读改写）复用同一段
    落盘逻辑，又各自控制锁的范围：_update_json 要把"读"也圈进锁里，不能在
    这里重复加锁（同一把 flock 重入没问题，但语义上让调用方掌管更清晰）。
    """
    # 备份当前的好版本（存在且能正常读才备份，别把坏文件存成备份）
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
            shutil.copy2(path, path + ".bak")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError):
            pass

    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _load_json_nolock(path: str, default):
    """无锁读（供 _update_json 在已持锁时读取，避免重复加锁）。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        bak = path + ".bak"
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError):
                pass
        return default


def _update_json(path: str, mutator, default):
    """
    ★ 原子的"读→改→写"：把整个复合操作用一把锁圈起来。

    这是并发安全的关键。upsert/delete 这类操作本质是：
        读全部 → 在内存里改 → 写回全部
    如果只锁"写"那一步，两个账号会同时读到【同一份】旧数据，各自改各自的，
    然后各自写回——后写的把先写的整片覆盖掉。实测 3 个账号并发各写 20 条，
    最后只剩 21 条，丢了 40 条。

    _update_json 把"读"也圈进同一把锁里：一个账号在读-改-写的整个过程中，
    别的账号必须等它写完才能开始读。这样每个人都是在【最新】的数据上改，
    谁的改动都不会丢。

    用法：
        def mut(records):
            records.append(new_row)
            return records          # 返回要写回的完整数据
        _update_json(path, mut, [])

    mutator 可以返回新数据；如果返回 None，表示"不需要写"（比如要删的记录
    根本不存在），这时跳过写入，省一次磁盘 IO。
    """
    _ensure_data_dir()
    with _FileLock(path):
        current = _load_json_nolock(path, default)
        result = mutator(current)
        if result is not None:
            _write_json_atomic(path, result)
        return result




class InkRepository:
    """油墨基因库 CRUD 仓储。"""

    def __init__(self, path: str = INKS_DB_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        return _load_json(self.path, [])

    def get_by_code(self, code: str) -> Optional[Dict]:
        for item in self.load_all():
            if item["code"] == code:
                return item
        return None

    def upsert(self, ink_record: Dict) -> None:
        """
        新增或更新一条油墨记录（工厂新购进油墨号可通过UI随时录入）。

        ink_record 需包含: code, name, category, K(31点数组), S(31点数组),
                          density, dry_back_factor
        """
        def _mut(records):
            for i, item in enumerate(records):
                if item["code"] == ink_record["code"]:
                    records[i] = ink_record
                    return records
            records.append(ink_record)
            return records
        _update_json(self.path, _mut, [])

    def upsert_meta(self, ink_record: Dict) -> None:
        """
        只更新油墨的"档案信息"（名称/类别/光谱/密度/干燥系数），
        绝不覆盖库存字段（stock_ml / low_stock_threshold_ml）。

        ⚠️ 这是【问题3：数据不同步】的核心修复。

        之前的bug是这样发生的：
            1. 【油墨库存管理】给 K-001 入库 500ml，stock_ml 变成 5500
            2. 用户去【油墨库管理】点【编辑】改了一下这支墨的名字
            3. 编辑对话框是在"打开的那一刻"读的旧库存（比如 5000），
               保存时 upsert() 把整条记录连库存一起写回去 —— 5500 被
               打回 5000，那 500ml 的入库记录就"凭空消失"了。

        修复思路：库存的唯一真值源是 inks_db.json 里的 stock_ml，而
        唯一有权改它的只有【油墨库存管理】页（走 adjust_stock）。
        【油墨库管理】页只负责档案信息，保存时用本方法，库存字段
        原封不动地从磁盘上的最新值里继承过来。
        """
        existing = self.get_by_code(ink_record["code"])
        merged = dict(ink_record)
        # 用户手动新建/编辑/Excel导入的墨，一律不带演示数据标记——一旦用户
        # 碰过它，它就是用户的墨，不该再被"一键清空演示数据"误删。
        merged.pop("is_demo_data", None)
        if existing is not None:
            # 库存类字段一律以磁盘上的最新值为准，不接受调用方传进来的值
            merged["stock_ml"] = existing.get("stock_ml", 0.0)
            merged["low_stock_threshold_ml"] = existing.get("low_stock_threshold_ml", 100.0)
        else:
            # 新建的油墨：库存从0开始，必须去【油墨库存管理】走采购入库
            merged.setdefault("stock_ml", 0.0)
            merged.setdefault("low_stock_threshold_ml", 100.0)
        self.upsert(merged)

    def delete(self, code: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["code"] != code]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]

    def list_by_category(self, category: str) -> List[Dict]:
        return [r for r in self.load_all() if r.get("category") == category]

    def adjust_stock(self, code: str, delta_ml: float) -> Optional[Dict]:
        """
        增减某支油墨的库存毫升数（正数=入库，负数=消耗/出库），
        返回更新后的完整记录；找不到该编号则返回 None。

        这是全系统【唯一】允许改动 stock_ml 的入口——【油墨库存管理】
        页的每一笔入库/出库都要走这里，改完立刻落盘，【油墨库管理】
        页刷新时读到的就是同一个数字，两边永远一致。
        """
        record = self.get_by_code(code)
        if record is None:
            return None
        record["stock_ml"] = round((record.get("stock_ml", 0.0) or 0.0) + delta_ml, 2)
        self.upsert(record)
        return record

    def set_low_stock_threshold(self, code: str, threshold_ml: float) -> Optional[Dict]:
        """单独设置低库存预警线（在【油墨库存管理】页改，不走档案编辑）。"""
        record = self.get_by_code(code)
        if record is None:
            return None
        record["low_stock_threshold_ml"] = round(threshold_ml, 2)
        self.upsert(record)
        return record

    @staticmethod
    def ml_to_grams(record: Dict, ml: float) -> float:
        """
        体积(ml) -> 重量(g)：克重 = 毫升 × 密度。

        【问题2：ml vs g 到底合不合理】的答案：合理，而且这是行业标准做法。
            - 油墨采购、桶装标称、库存盘点，全世界都是按【体积 ml/L】走的
              （你买的是"一桶5升黑墨"，不是"一桶5.25公斤黑墨"）
            - 而现场配墨必须按【重量 g】走，因为电子天平称的是重量，
              而且 K-M 配方算出来的比例本身就是质量比
        两者靠【密度 density (g/ml)】换算，这个字段每支墨的档案里都有。
        """
        density = record.get("density", 1.0) or 1.0
        return ml * density

    @staticmethod
    def grams_to_ml(record: Dict, grams: float) -> float:
        """重量(g) -> 体积(ml)：毫升 = 克重 / 密度。库存扣减时用这个。"""
        density = record.get("density", 1.0) or 1.0
        if density <= 0:
            density = 1.0
        return grams / density

    @staticmethod
    def stock_status(record: Dict) -> str:
        """返回 '正常' / '库存不足' / '缺货' 三种状态之一，供UI着色提醒使用。"""
        stock = record.get("stock_ml", 0.0) or 0.0
        threshold = record.get("low_stock_threshold_ml", 100.0) or 100.0
        if stock <= 0:
            return "缺货"
        if stock <= threshold:
            return "库存不足"
        return "正常"


# ==========================================================================
# 承印物材质库（问题6）
# ==========================================================================
#
# 背景：同一个配方，印在玻璃上和印在PP塑料上，效果完全不一样。差别来自
# 两个物理层面，缺一不可：
#
#   ① 表面能 / 附着力 —— PE、PP 这类聚烯烃表面能只有 30 mN/m 出头，
#      油墨根本"咬不住"，不做电晕/火焰处理，指甲一刮就掉。玻璃和金属
#      表面能高（>400 mN/m），油墨天然附着好。这决定了【能不能印】。
#
#   ② 墨膜厚度 / 油墨吸收 —— 光滑无孔的玻璃、金属，油墨全部留在表面，
#      墨膜厚、显色足；而纸质、粗糙塑料会吸掉一部分墨，同样的配方印上去
#      颜色会偏浅、偏灰。这决定了【印出来是什么颜色】，必须进配色算法。
#
# 下面这张表把这两件事都量化了：
#   - adhesion_factor: 附着力系数 (0~1)，越低越难粘，越需要前处理/底涂
#   - film_factor:     墨膜留存系数 (0~1)，1=油墨全留表面显色最足，
#                      越低表示越吸墨、显色越弱，配色时要相应补偿
#   - opacity_boost:   遮盖力修正，深色/金属底材需要更强的遮盖
#
# 数值参考行业通行经验值（丝印手册 + 主流油墨厂技术资料的典型区间），
# ⚠️ 这些是【经验起点值】不是实测值——正式投产前建议用你自己的油墨在
# 每种材质上打样标定一次，把数值改成你现场实测的，配色才会真正准。
# ==========================================================================

# ══════════════════════════════════════════════════════════════════════
# 标准专色库
# ══════════════════════════════════════════════════════════════════════
# 丝印行业常用的基础专色，带【标准 Lab 值】和【允许色差 ΔE*ab】。
#
# ── 这份数据是干什么用的 ──────────────────────────────────────────
# 两个用途，都很实在：
#
#   1. 【建库起步】：新客户装上软件，油墨库是空的（出厂那 24 支假墨该删掉）。
#      一键把这 13 支载进来，就有了一个基于【真实市面标准专色】的起步库，
#      比对着空表格一支一支敲强得多。
#
#   2. 【来料检验】：你是油墨供应商。供应商送来一桶"大红"，到底是不是真的
#      大红？用色差仪测一下实测 Lab，跟这里的标准 Lab 比，算出 ΔE——
#      超过允许色差就是不合格，可以直接退货。这是能立刻省钱的功能。
#
# ── ⚠️ 必须说清楚的限制 ────────────────────────────────────────────
# Lab 只能定义"这支墨看起来是什么颜色"，【推不出它混色时怎么表现】。
#
# 从 Lab 反推 K/S 光谱是个近似：同一个 Lab 可以对应无数条不同的反射曲线
# （这就是同色异谱）。所以载入之后：
#     ✅ 每支墨的单色显示是准的
#     ⚠️ 但混色配方的 ΔE 预测仍然是近似的，不能当验收依据
#
# 要让混色预测也准，只有一条路：用分光光度计实测每支墨的反射光谱。
# 这份标准库是个【好的起点】，不是【终点】。
STANDARD_SPOT_INKS = [
    # (编号, 名称, L*, a*, b*, 允许ΔE, 类别)
    ("STD-01", "CMYK-青 (Cyan)",                55.4, -37.2, -50.1, 1.5, "color"),
    ("STD-02", "CMYK-洋红 (Magenta)",           47.1,  74.3,  -4.2, 1.5, "color"),
    ("STD-03", "CMYK-黄 (Yellow)",              89.2,  -7.1,  92.5, 1.5, "color"),
    ("STD-04", "CMYK-黑 (Black)",               16.5,   0.4,  -0.6, 1.2, "color"),
    ("STD-05", "射光蓝 (Reflex Blue)",          19.0,  26.0, -68.0, 2.0, "color"),
    ("STD-06", "大红 (Pantone 185 C)",          49.0,  69.0,  44.0, 1.5, "color"),
    ("STD-07", "橙色 (Orange 021 C)",           60.8,  65.7,  85.1, 1.8, "color"),
    ("STD-08", "绿色 (Green C)",                57.7, -77.2,   0.2, 2.0, "color"),
    ("STD-09", "紫罗兰 (Violet C)",             18.8,  54.5, -69.5, 2.0, "color"),
    ("STD-10", "过程蓝 (Process Blue)",         52.0, -34.0, -55.0, 1.8, "color"),
    ("STD-11", "金红 (Warm Red C)",             51.0,  65.0,  56.0, 1.5, "color"),
    ("STD-12", "耐晒黑 (Resistant Black)",      17.2,   0.1,  -0.2, 1.0, "color"),
    # 白墨：丝印的命根子。深色底材上不打白底，什么颜色都会被吃掉。
    # 高遮盖白的 Lab 通常在 L*≈94-96、a*/b* 接近 0（略偏蓝以显得更"白"）。
    ("STD-13", "高遮盖白 (Opaque White)",       95.0,  -0.5,   1.5, 1.5, "white"),
]


def build_standard_ink_records() -> List[Dict]:
    """
    把标准专色库变成可以直接写进 inks_db.json 的完整油墨档案。

    K/S 光谱由 Lab 反推（近似）。这一点在每条记录里都用 `ks_from_lab=True`
    明确标记出来——UI 会据此提醒用户"这支墨的光谱是推算的，不是实测的"，
    避免用户误以为它和分光光度计测出来的数据是一个级别。
    """
    from core_layer.ink_synthesis import synthesize_ink_spectrum

    records = []
    for code, name, L, a, b, tol, category in STANDARD_SPOT_INKS:
        synth = synthesize_ink_spectrum((L, a, b))
        records.append({
            "code": code,
            "name": name,
            "category": category,
            "K": [float(v) for v in synth["K"]],
            "S": [float(v) for v in synth["S"]],
            # 标准 Lab：这支墨【应该】是什么颜色。来料检验时拿实测值跟它比。
            "ref_lab": [L, a, b],
            # 允许色差：实测 Lab 跟标准 Lab 的 ΔE 超过这个数，这批墨就不合格。
            "delta_e_tolerance": tol,
            # 标记：K/S 是从 Lab 推的，不是分光光度计实测的
            "ks_from_lab": True,
            "density": 1.05,
            "dry_back_factor": 0.25,
            "stock_ml": 0.0,          # 库存必须自己入库，不能凭空给
            "low_stock_threshold_ml": 200.0,
        })
    return records


def check_ink_batch(ink_record: Dict, measured_lab) -> Dict:
    """
    来料检验：供应商送来的这桶墨，颜色对不对？

    你是油墨供应商——供应商送来一桶标称"大红"的墨，用色差仪测一下实测 Lab，
    跟档案里的标准 Lab 一比，ΔE 超过允许色差就是不合格，可以直接退货。

    ⚠️ 注意这个功能【只需要色差仪，不需要分光光度计】——因为它只比"颜色像不像"，
    不涉及混色预测。这是色差仪唯一真正够用的场景。
    （混色预测需要 K/S 光谱，那才必须上分光光度计。两回事，别混淆。）

    返回：
        {"ok": bool, "delta_e": float, "tolerance": float, "verdict": str}
        没录标准 Lab 的话 ok=None，表示"没有标准值，无从判断"。
    """
    ref = ink_record.get("ref_lab")
    if not ref or len(ref) != 3:
        return {
            "ok": None, "delta_e": None,
            "tolerance": ink_record.get("delta_e_tolerance"),
            "verdict": "这支墨没有录【标准Lab值】，无法做来料检验。请先在油墨档案里填上。",
        }

    tol = ink_record.get("delta_e_tolerance") or 2.0
    dl = measured_lab[0] - ref[0]
    da = measured_lab[1] - ref[1]
    db = measured_lab[2] - ref[2]
    de = (dl * dl + da * da + db * db) ** 0.5

    ok = de <= tol
    if ok:
        verdict = f"✅ 合格。ΔE = {de:.2f}，在允许范围（≤{tol}）内。"
    else:
        # 说清楚偏在哪个方向，师傅才知道怎么调、你才知道怎么跟供应商说
        parts = []
        if abs(dl) > 0.5:
            parts.append("偏亮" if dl > 0 else "偏暗")
        if abs(da) > 0.5:
            parts.append("偏红" if da > 0 else "偏绿")
        if abs(db) > 0.5:
            parts.append("偏黄" if db > 0 else "偏蓝")
        direction = "、".join(parts) if parts else "整体偏移"
        verdict = (
            f"❌ 超差！ΔE = {de:.2f}，超出允许范围（≤{tol}）{de - tol:.2f}。\n\n"
            f"偏差方向：{direction}\n"
            f"ΔL* = {dl:+.1f}（明度）　Δa* = {da:+.1f}（红绿）　Δb* = {db:+.1f}（黄蓝）\n\n"
            f"这批墨颜色不符合标准，可以据此跟供应商交涉。"
        )

    return {"ok": ok, "delta_e": round(de, 2), "tolerance": tol, "verdict": verdict}


# ══════════════════════════════════════════════════════════════════════
# 承印物材质库
# ══════════════════════════════════════════════════════════════════════
# 每种材质除了配色用的三个系数（附着/墨膜/遮盖），还带一份完整的
# 【附着力方案】——这是丝印现场最容易翻车、也最容易被忽略的一环。
#
# 核心事实（2026年市面通行做法）：
#   · PP 表面能只有 29 达因、PE 只有 31 达因，必须处理到 ≥38 达因才印得牢。
#     不做前处理，用什么墨、加什么助剂都救不回来——这一步省不掉。
#   · 玻璃/金属/陶瓷/电镀：双组份油墨 + 10% 硬化剂，80℃烘10分钟，附着力提升明显。
#   · PVC/PET/ABS 表面能够高（39~42 达因），一般可直接印。
#   · 验收统一用 3M 百格测试（ASTM D3359）：百格刀划 10×10 个 1mm 小格，
#     贴 3M 600/610 胶带，90° 快速撕起，看脱落格数。100/100 不脱 = 5B。
MATERIAL_LIBRARY = {
    "glass_clear": {
        "label": "透明玻璃",
        "family": "玻璃",
        "adhesion_factor": 0.95,
        "film_factor": 1.00,
        "opacity_boost": 1.00,
        "pretreatment": "脱脂清洗（异丙醇/酒精擦拭）",
        "recommended_ink": "玻璃专用油墨 / UV油墨",
        "notes": "表面能高，附着好。但透明底材需注意：背面透光会影响观感，浅色图案建议先打一层白墨打底。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": None,
            "needs_treatment": False,
            "treatment": "脱脂清洗即可：异丙醇/酒精擦拭，去掉指纹和脱模剂残留。污染严重的上等离子清洗。",
            "hardener": "【强烈建议】加 10% 硬化剂（固化剂）。玻璃是无机表面，靠的是化学键合，加固化剂能显著提升附着力和墨膜硬度。也可用硅烷偶联剂做底涂。",
            "bake": "80℃ 烘 10 分钟（自干也行，但烘烤后附着力和耐磨性明显更好）",
            "target_grade": "5B / 100格全不脱落",
            "risk": "low",
        },
    },
    "glass_amber": {
        "label": "棕色玻璃（药用瓶）",
        "family": "玻璃",
        "adhesion_factor": 0.94,
        "film_factor": 1.00,
        "opacity_boost": 1.35,
        "pretreatment": "脱脂清洗",
        "recommended_ink": "玻璃专用油墨（高遮盖）",
        "notes": "底色深，浅色图案必须打白底，否则颜色被底色吃掉。遮盖力要求高。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": None,
            "needs_treatment": False,
            "treatment": "脱脂清洗（异丙醇/酒精）",
            "hardener": "【强烈建议】加 10% 硬化剂。同透明玻璃。",
            "bake": "80℃ 烘 10 分钟",
            "target_grade": "5B / 100格全不脱落",
            "risk": "low",
        },
    },
    "plastic_pe": {
        "label": "PE 聚乙烯（最难粘）",
        "family": "塑料",
        "adhesion_factor": 0.55,
        "film_factor": 0.92,
        "opacity_boost": 1.00,
        "pretreatment": "⚠️ 必须做电晕处理或火焰处理（达因值需≥38）",
        "recommended_ink": "PE专用油墨 + 附着力促进剂",
        "notes": "表面能极低（~31 mN/m），不做前处理必掉墨。印前务必用达因笔测一下，低于38就别开机。",
        "adhesion_plan": {
            "surface_energy_dyne": 31,
            "required_dyne": 38,
            "needs_treatment": True,
            "treatment": "🔴【必做】电晕处理 或 火焰处理，把表面能从 31 达因提到 ≥38 达因。水性油墨要求更高，需到 42 达因。\n印前用【达因笔】测一下，低于 38 就别开机——这一步省不掉，不做前处理，用什么墨、加什么助剂都救不回来。",
            "hardener": "用含 CPE/CPP 附着力促进剂的改性 PVC 溶剂型油墨，或双组份 PE 专用墨 + 固化剂。条件允许可先喷一层 PP 底涂水（汽车保险杠底涂那种）再印。",
            "bake": "双组份墨需加温固化；自干墨要等完全实干（24h）再测附着力",
            "target_grade": "≥4B（PE 能做到 5B 已经很好）",
            "risk": "high",
        },
    },
    "plastic_pp": {
        "label": "PP 聚丙烯",
        "family": "塑料",
        "adhesion_factor": 0.62,
        "film_factor": 0.93,
        "opacity_boost": 1.00,
        "pretreatment": "⚠️ 需要电晕/火焰处理（达因值需≥38）",
        "recommended_ink": "PP专用油墨 + 附着力促进剂",
        "notes": "跟PE同属聚烯烃，表面能低（~34 mN/m）。处理后的PP有时效性，处理完最好24小时内印完。",
        "adhesion_plan": {
            "surface_energy_dyne": 29,
            "required_dyne": 38,
            "needs_treatment": True,
            "treatment": "🔴【必做】电晕处理 或 火焰处理，表面能 29 达因 → ≥38 达因。\nPP 比 PE 更难粘（表面能更低）。印前必须用达因笔确认。\n市面上有标称'免处理 PP 油墨'的产品，但稳定性因批次而异，首次用一定要先打样做百格测试再上量。",
            "hardener": "PP 专用双组份油墨 + 固化剂，或含 CPP 促进剂的油墨。可先上 PP 底涂水。",
            "bake": "加温固化（60-80℃）能明显提升附着力",
            "target_grade": "≥4B",
            "risk": "high",
        },
    },
    "plastic_pet": {
        "label": "PET 聚酯（矿泉水瓶料）",
        "family": "塑料",
        "adhesion_factor": 0.85,
        "film_factor": 0.95,
        "opacity_boost": 1.00,
        "pretreatment": "清洗除尘即可（必要时轻度电晕）",
        "recommended_ink": "PET/塑料通用油墨",
        "notes": "塑料里最好印的一种，表面能中等（~44 mN/m）。日化、饮料瓶大量用这个。",
        "adhesion_plan": {
            "surface_energy_dyne": 41,
            "required_dyne": 38,
            "needs_treatment": False,
            "treatment": "表面能 ~41 达因，高于 38 的门槛，一般可直接印。\n但要注意：PET 表面可能有析出的添加剂或脱模剂，印前先擦拭清洁。高要求场合仍建议做一道电晕。",
            "hardener": "PET 专用油墨。加 5-10% 固化剂可提升耐磨和耐溶剂性。",
            "bake": "60-80℃ 烘烤可选",
            "target_grade": "5B",
            "risk": "low",
        },
    },
    "plastic_pvc": {
        "label": "PVC 聚氯乙烯",
        "family": "塑料",
        "adhesion_factor": 0.88,
        "film_factor": 0.94,
        "opacity_boost": 1.00,
        "pretreatment": "清洗除尘",
        "recommended_ink": "PVC油墨 / 溶剂型通用油墨",
        "notes": "附着性好，但耐溶剂性差，选墨时注意别把底材咬花。",
        "adhesion_plan": {
            "surface_energy_dyne": 39,
            "required_dyne": 38,
            "needs_treatment": False,
            "treatment": "表面能 ~39 达因，可直接印。PVC 是丝印里最好粘的塑料之一。\n注意：软质 PVC 含增塑剂，长期可能迁移导致墨层发粘，选墨时说明是软质还是硬质。",
            "hardener": "普通 PVC 油墨即可，一般不需要固化剂。",
            "bake": "自干即可",
            "target_grade": "5B",
            "risk": "low",
        },
    },
    "plastic_abs": {
        "label": "ABS 工程塑料",
        "family": "塑料",
        "adhesion_factor": 0.86,
        "film_factor": 0.94,
        "opacity_boost": 1.00,
        "pretreatment": "清洗除尘",
        "recommended_ink": "ABS/PS 油墨",
        "notes": "电子产品外壳常用，附着不错。表面若有脱模剂残留必须先洗掉。",
        "adhesion_plan": {
            "surface_energy_dyne": 42,
            "required_dyne": 38,
            "needs_treatment": False,
            "treatment": "表面能 ~42 达因，可直接印。清洁除静电即可。\n⚠️ 注意溶剂：ABS/PC 怕强溶剂，会应力开裂（银纹）。稀释剂别乱用，用配套的。",
            "hardener": "ABS/PS/PC/PMMA 专用溶剂型油墨（常见 SP 系列）。一般不需固化剂。",
            "bake": "自干",
            "target_grade": "5B",
            "risk": "low",
        },
    },
    "plastic_acrylic": {
        "label": "亚克力 / PMMA",
        "family": "塑料",
        "adhesion_factor": 0.90,
        "film_factor": 0.97,
        "opacity_boost": 1.00,
        "pretreatment": "静电除尘 + 酒精擦拭",
        "recommended_ink": "亚克力专用油墨（低溶解性）",
        "notes": "易被强溶剂咬伤发白，选墨要谨慎。表面光滑显色好。",
        "adhesion_plan": {
            "surface_energy_dyne": 38,
            "required_dyne": 38,
            "needs_treatment": False,
            "treatment": "表面能 ~38 达因，处在临界线上，一般可直印。清洁除静电。\n⚠️ 亚克力(PMMA)对溶剂敏感，强溶剂会导致龟裂，必须用配套稀释剂。",
            "hardener": "PMMA 专用油墨。可加少量固化剂提升耐磨。",
            "bake": "自干；低温烘烤需注意亚克力变形温度",
            "target_grade": "5B",
            "risk": "medium",
        },
    },
    "metal_aluminum": {
        "label": "铝 / 铝罐",
        "family": "金属",
        "adhesion_factor": 0.87,
        "film_factor": 1.00,
        "opacity_boost": 1.25,
        "pretreatment": "脱脂除油（碱洗/溶剂），必要时阳极氧化或涂底漆",
        "recommended_ink": "金属专用油墨（需高温固化）",
        "notes": "表面有金属光泽，会影响观感——同一配方在铝上看起来比在白塑料上更亮更冷。遮盖力要求高。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": None,
            "needs_treatment": False,
            "treatment": "脱脂除油（金属表面常有防锈油/拉伸油），用酒精或专用清洗剂。\n阳极氧化铝表面附着更好；抛光/镜面铝较难粘，可考虑打磨或底涂。",
            "hardener": "【建议】金属专用双组份油墨（常见 MPL 系列）+ 10% 硬化剂，显著提升附着力和墨膜硬度、耐酒精耐化学性。",
            "bake": "80℃ 烘 10 分钟（强烈建议，附着力提升明显）",
            "target_grade": "5B",
            "risk": "low",
        },
    },
    "metal_copper": {
        "label": "铜 / 黄铜",
        "family": "金属",
        "adhesion_factor": 0.80,
        "film_factor": 1.00,
        "opacity_boost": 1.40,
        "pretreatment": "⚠️ 除油 + 除氧化层（酸洗），印前必须立即处理",
        "recommended_ink": "金属专用油墨 + 环氧底涂",
        "notes": "极易氧化，处理完放几个小时表面就重新氧化了，附着力会大幅下降。底色偏黄红，遮盖要求最高。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": None,
            "needs_treatment": False,
            "treatment": "脱脂 + 除氧化层。铜易氧化，清洁后要尽快印，放久了表面又氧化就粘不牢。",
            "hardener": "【建议】金属专用油墨 + 10% 硬化剂。",
            "bake": "80℃ 烘 10 分钟",
            "target_grade": "5B",
            "risk": "medium",
        },
    },
    "metal_stainless": {
        "label": "不锈钢",
        "family": "金属",
        "adhesion_factor": 0.83,
        "film_factor": 1.00,
        "opacity_boost": 1.20,
        "pretreatment": "脱脂 + 轻度喷砂/拉丝增加粗糙度",
        "recommended_ink": "金属专用油墨（需烘烤固化）",
        "notes": "表面太光滑反而不好粘，适度增加粗糙度能显著提升附着。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": None,
            "needs_treatment": False,
            "treatment": "脱脂除油。不锈钢表面光滑致密，比铝更难粘。\n拉丝面比镜面好粘（机械咬合）。镜面不锈钢建议先做底涂。",
            "hardener": "【必须】金属专用双组份油墨 + 10% 硬化剂。不加固化剂在不锈钢上很容易被 3M 胶带撕掉。",
            "bake": "【必须】80℃ 烘 10 分钟以上",
            "target_grade": "≥4B",
            "risk": "medium",
        },
    },
    "paper_kraft": {
        "label": "牛皮纸 / 纸质",
        "family": "纸",
        "adhesion_factor": 0.98,
        "film_factor": 0.72,
        "opacity_boost": 1.15,
        "pretreatment": "无需处理",
        "recommended_ink": "水性油墨 / 纸张油墨",
        "notes": "⚠️ 纸会大量吸墨（film_factor只有0.72），同一配方印在纸上会明显偏浅偏灰，系统已自动补偿。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": None,
            "needs_treatment": False,
            "treatment": "纸张是多孔吸收性材料，油墨靠渗透锚固，附着不是问题。无需处理。",
            "hardener": "不需要。",
            "bake": "自干",
            "target_grade": "不适用（纸纤维会跟着墨一起被撕起来，百格测试对纸没有意义）",
            "risk": "none",
        },
    },
    "custom": {
        "label": "自定义 / 其他",
        "family": "其他",
        "adhesion_factor": 0.85,
        "film_factor": 1.00,
        "opacity_boost": 1.00,
        "pretreatment": "按实际材质判断",
        "recommended_ink": "通用油墨",
        "notes": "未指定材质，使用中性默认值。建议补充为具体材质以获得更准的配色。",
        "adhesion_plan": {
            "surface_energy_dyne": None,
            "required_dyne": 38,
            "needs_treatment": None,
            "treatment": "未知材质：先用【达因笔】测表面能。低于 38 达因就必须做电晕/火焰处理。",
            "hardener": "先小批量打样，加与不加固化剂各做一组，分别做 3M 百格测试对比。",
            "bake": "按油墨说明书",
            "target_grade": "≥4B",
            "risk": "unknown",
        },
    },
}

# 按材质大类分组，供UI做两级下拉（塑料 -> PP/PE/PET...）
MATERIAL_FAMILIES = {}
for _code, _meta in MATERIAL_LIBRARY.items():
    MATERIAL_FAMILIES.setdefault(_meta["family"], []).append(_code)


def get_material_props(substrate_type: str) -> Dict:
    """按材质代码取物理属性；未知代码回退到 custom 的中性默认值。"""
    return MATERIAL_LIBRARY.get(substrate_type, MATERIAL_LIBRARY["custom"])


def material_label(substrate_type: str) -> str:
    return get_material_props(substrate_type)["label"]


def adhesion_warning(substrate_type: str) -> Optional[str]:
    """
    附着力风险提示：系数低于0.7的材质，不做前处理基本必掉墨，
    这种事必须在开机前就告诉师傅，而不是等印完了刮一下才发现。
    """
    props = get_material_props(substrate_type)
    factor = props["adhesion_factor"]
    if factor >= 0.80:
        return None
    level = "极高" if factor < 0.60 else "较高"
    return (
        f"⚠️ 【{props['label']}】掉墨风险{level}（附着力系数仅 {factor:.2f}）。\n\n"
        f"前处理要求：{props['pretreatment']}\n"
        f"推荐用墨：{props['recommended_ink']}\n\n"
        f"{props['notes']}"
    )


class BottleRepository:
    """承印物/瓶身底色库 CRUD 仓储（含材质物理属性，见 MATERIAL_LIBRARY）。"""

    def __init__(self, path: str = BOTTLES_DB_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        return _load_json(self.path, [])

    def get_by_code(self, code: str) -> Optional[Dict]:
        for item in self.load_all():
            if item["code"] == code:
                return item
        return None

    def upsert(self, bottle_record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item["code"] == bottle_record["code"]:
                    records[i] = bottle_record
                    return records
            records.append(bottle_record)
            return records
        _update_json(self.path, _mut, [])

    def delete(self, code: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["code"] != code]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]


class CompanyInfoRepository:
    """
    公司信息仓储（单条配置，不是列表）。

    用于在【导出工单Word文档】时打印抬头信息（公司名称/联系方式/Logo），
    参考同行业软件常见做法：导出文档带正式抬头，而不是一张裸表格。
    """

    DEFAULT = {
        "company_name": "",
        "contact_phone": "",
        "address": "",
        "slogan": "",
        "logo_path": "",
    }

    def __init__(self, path: str = COMPANY_INFO_PATH):
        self.path = path

    def load(self) -> Dict:
        data = _load_json(self.path, dict(self.DEFAULT))
        merged = dict(self.DEFAULT)
        merged.update(data or {})
        return merged

    def save(self, info: Dict) -> None:
        merged = dict(self.DEFAULT)
        merged.update(info or {})
        _save_json(self.path, merged)


class ProductRepository:
    """
    产品模板仓储 —— 把一次配色工单（瓶身+各色位目标色+默认总重）存成可复用的
    "产品"模板，下次同款订单直接调出来，不用重新点色/建色位。
    """

    def __init__(self, path: str = PRODUCTS_DB_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        return _load_json(self.path, [])

    def get_by_code(self, code: str) -> Optional[Dict]:
        for item in self.load_all():
            if item["code"] == code:
                return item
        return None

    def upsert(self, product_record: Dict) -> None:
        """
        product_record 结构：
        {
            "code": "PROD-001",
            "name": "客户A 100ml白瓶套色",
            "customer": "客户A",
            "bottle_code": "BT-WHITEPE",
            "stations": [
                {"name": "文字", "target_lab": [20.0, 0.0, 0.0], "total_grams": 200.0},
                ...
            ],
            "notes": "",
            "updated_at": "2026-07-07 12:00"
        }
        """
        def _mut(records):
            for i, item in enumerate(records):
                if item["code"] == product_record["code"]:
                    records[i] = product_record
                    return records
            records.append(product_record)
            return records
        _update_json(self.path, _mut, [])

    def delete(self, code: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["code"] != code]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]


class MachineRepository:
    """丝印机台档案仓储（机台编号/名称列表，供生产记录关联选择）。"""

    def __init__(self, path: str = MACHINES_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        return _load_json(self.path, [])

    def upsert(self, machine_record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item["code"] == machine_record["code"]:
                    records[i] = machine_record
                    return records
            records.append(machine_record)
            return records
        _update_json(self.path, _mut, [])

    def delete(self, code: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["code"] != code]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]


class ProductionRepository:
    """
    打样/生产记录仓储 —— 车间日常管理：调机照片、预计完成时间、预计产量、
    机台运行状态，供【生产追踪】页面展示。

    production_record 结构：
    {
        "id": "PR-0001",
        "machine_code": "M-01",
        "machine_name": "1号丝印机",
        "product_name": "客户A 100ml白瓶套色",   # 选填，关联到哪个产品/工单
        "photo_path": "data/assets/xxx.jpg",       # 调机照片本地路径
        "status": "调机中",                          # 调机中/生产中/已完成/异常暂停
        "expected_completion": "2026-07-10 18:00",
        "expected_quantity": 5000,
        "notes": "",
        "created_at": "2026-07-08 09:00",
        "updated_at": "2026-07-08 09:00",
    }
    """

    def __init__(self, path: str = PRODUCTION_RECORDS_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        records = _load_json(self.path, [])
        # 最近更新的排在最前面，方便"老板看最新情况"这种典型用法
        records.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return records

    def get_by_id(self, record_id: str) -> Optional[Dict]:
        for item in self.load_all():
            if item["id"] == record_id:
                return item
        return None

    def upsert(self, record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item["id"] == record["id"]:
                    records[i] = record
                    return records
            records.append(record)
            return records
        _update_json(self.path, _mut, [])

    def delete(self, record_id: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["id"] != record_id]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]

    def latest_status_by_machine(self) -> Dict[str, Dict]:
        """每台机器最新的一条记录，供机台状态总览用。"""
        result: Dict[str, Dict] = {}
        for r in self.load_all():  # 已按updated_at降序
            code = r.get("machine_code", "")
            if code and code not in result:
                result[code] = r
        return result


class FinanceRepository:
    """
    财务：应收账款 / 收款记录。

    ── 数据从哪来 ──────────────────────────────────────────────
    财务不重新录一遍数据，而是【挂靠在进销存的进货记录上】：

        进销存记的是"事实"：客户A 在 7/14 送来 1000 个 100ml 白瓶要印
        财务算的是"钱"  ：这 1000 个按 2.5 元/个 = 2500，优惠 200，
                          实收应为 2300；客户先付了 1000，还欠 1300

    所以这张表的每一条，都用 `inventory_id` 指回进销存里的那一条进货记录。
    数量、产品名、客户、日期这些都不在这里存第二份——那样迟早会两边对不上。
    这里只存进销存管不了的三件事：

        unit_price   单价（进销存里那个单价是"参考价"，实际成交价可能谈过）
        discount     优惠金额
        payments     收款流水（一笔一笔记，支持分期付款）

    ── 为什么要有 payments 这个列表，而不是只存一个"已付金额" ──
    客户很少一次付清。今天付 1000，下个月付 800，再下个月付清。如果只存
    一个总数，就永远说不清"这 1800 是什么时候、以什么方式付的"。对不上账
    的时候没有任何凭据可查。所以按笔记，总额是算出来的。
    """

    def __init__(self, path: str = FINANCE_RECORDS_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        return _load_json(self.path, [])

    def get_by_inventory_id(self, inventory_id: str) -> Optional[Dict]:
        for r in self.load_all():
            if r.get("inventory_id") == inventory_id:
                return r
        return None

    def upsert(self, record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item.get("inventory_id") == record.get("inventory_id"):
                    records[i] = record
                    return records
            records.append(record)
            return records
        _update_json(self.path, _mut, [])

    def delete_by_inventory_id(self, inventory_id: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r.get("inventory_id") != inventory_id]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]

    def add_payment(self, inventory_id: str, amount: float, date: str, method: str = "", note: str = "") -> Dict:
        """记一笔收款。返回更新后的财务记录。"""
        rec = self.get_by_inventory_id(inventory_id)
        if rec is None:
            rec = {"inventory_id": inventory_id, "unit_price": 0.0, "discount": 0.0, "payments": []}
        rec.setdefault("payments", []).append({
            "amount": round(amount, 2),
            "date": date,
            "method": method,
            "note": note,
        })
        self.upsert(rec)
        return rec

    def find_orphans(self, inventory_repo) -> List[Dict]:
        """
        找出"孤儿"财务记录：它指向的那条进销存记录已经不存在了。

        怎么产生的：以前删除进销存记录时没有连带清理财务（v35已修）；或者用户
        直接去动了 json 文件。财务页是从进销存反查过来的，所以这些孤儿记录
        【在界面上根本看不见】——但它们一直躺在 finance_records.json 里，
        里面的收款金额永远查不到、也删不掉。

        ⚠️ 不能默默删：孤儿记录里可能挂着真实收过的钱。客户确实付过 3000 块，
        只是那条进货记录被误删了。这种情况必须让人看见、让人决定，而不是
        由程序悄悄抹掉一笔真金白银。
        """
        orphans = []
        for f in self.load_all():
            inv_id = f.get("inventory_id")
            if not inv_id or inventory_repo.get_by_id(inv_id) is None:
                orphans.append(f)
        return orphans

    def purge_orphans(self, inventory_repo) -> int:
        """清掉所有孤儿财务记录，返回清掉的条数。调用方必须先向用户确认。"""
        alive = [
            f for f in self.load_all()
            if f.get("inventory_id") and inventory_repo.get_by_id(f["inventory_id"]) is not None
        ]
        removed = len(self.load_all()) - len(alive)
        if removed:
            _save_json(self.path, alive)
        return removed

    # ---- 计算：这几个是财务的核心，全部由公式算出，不存冗余字段 ----

    @staticmethod
    def paid_total(finance_record: Optional[Dict]) -> float:
        """已付总额 = 所有收款流水之和。"""
        if not finance_record:
            return 0.0
        return round(sum(p.get("amount", 0.0) for p in finance_record.get("payments", [])), 2)

    @staticmethod
    def compute(inventory_record: Dict, finance_record: Optional[Dict]) -> Dict:
        """
        把一条进货记录 + 它的财务记录，算成一行完整的应收账款。

        单价的取值逻辑：财务这边填了就用财务的（实际成交价可能谈过），
        没填就回落到进销存里录的那个参考价。
        """
        qty = inventory_record.get("quantity", 0.0) or 0.0
        fin_price = (finance_record or {}).get("unit_price")
        unit_price = fin_price if (fin_price is not None and fin_price > 0) \
            else (inventory_record.get("unit_price", 0.0) or 0.0)

        gross = round(qty * unit_price, 2)                      # 合计 = 数量 × 单价
        discount = round((finance_record or {}).get("discount", 0.0) or 0.0, 2)
        receivable = round(gross - discount, 2)                 # 实际应收 = 合计 - 优惠
        paid = FinanceRepository.paid_total(finance_record)     # 已付
        balance = round(receivable - paid, 2)                   # 尚欠 = 应收 - 已付

        if receivable <= 0.001:
            status = "无金额"
        elif paid <= 0.001:
            status = "未付款"
        elif balance <= 0.001:
            status = "已结清"
        else:
            status = "部分已付"

        return {
            "quantity": qty,
            "unit_price": unit_price,
            "gross": gross,
            "discount": discount,
            "receivable": receivable,
            "paid": paid,
            "balance": balance,
            "status": status,
        }

    @staticmethod
    def aging_days(date_str: str, balance: float) -> Optional[int]:
        """
        账龄：从进货那天算到今天过了多少天。只有还欠着钱（balance>0）才有意义。
        欠得越久越该催——这是应收账款管理最基本的一件事。
        """
        if balance is None or balance <= 0.001 or not date_str:
            return None
        try:
            d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
        return max(0, (datetime.date.today() - d).days)


class InventoryRepository:
    """
    进销存记录仓储 —— 参照客户原有《XX月产量表》Excel模板的字段习惯
    （日期/客户/产品名称/印次/数量/单价/金额/包装/单号/刮数/备注），
    在此基础上增加"类型"(进货/出货)字段，用于自动计算库存结余。

    重要背景（来自客户澄清）：进出货是文员统计的，跟丝印师傅打样
    （生产追踪页）是两件不同的事、不同的人、不同的时间点，所以
    单独建这一个模块，不跟生产追踪混在一起。

    inventory_record 结构：
    {
        "id": "INV-20260709103000",
        "date": "2026-07-09",
        "customer": "客户A",
        "product_name": "100ml白瓶套色",
        "movement_type": "进货",   # 进货 或 出货
        "print_count": 3,           # 印次(选填)
        "quantity": 1000,
        "unit_price": 2.5,
        "amount": 2500.0,           # 数量*单价，保存时算好
        "packaging": "纸箱/50个",
        "order_no": "SO-0001",
        "scrape_count": 2,          # 刮数(选填)
        "receiving_unit": "客户A仓库",   # 收货单位(打印单据用)
        "handler": "张三",                # 经手人(打印单据用)
        "vehicle_plate": "粤B12345",      # 车牌号(打印单据用)
        "notes": "",
        "created_at": "2026-07-09 10:30",
    }
    """

    def __init__(self, path: str = INVENTORY_RECORDS_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        records = _load_json(self.path, [])
        records.sort(key=lambda r: (r.get("date", ""), r.get("created_at", "")), reverse=True)
        return records

    def get_by_id(self, record_id: str) -> Optional[Dict]:
        for item in self.load_all():
            if item["id"] == record_id:
                return item
        return None

    def upsert(self, record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item["id"] == record["id"]:
                    records[i] = record
                    return records
            records.append(record)
            return records
        _update_json(self.path, _mut, [])

    def delete(self, record_id: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["id"] != record_id]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]

    def stock_summary(self) -> List[Dict]:
        """
        按 (客户, 产品名称) 分组，汇总累计入库/累计出库/库存结余，
        供【库存结余总览】看板使用——这就是"一眼看出哪些客户的货
        已出/未出"的数据来源。
        """
        groups: Dict[tuple, Dict] = {}
        for r in _load_json(self.path, []):
            key = (r.get("customer", "") or "未指定客户", r.get("product_name", "") or "未命名产品")
            if key not in groups:
                groups[key] = {"customer": key[0], "product_name": key[1], "in_qty": 0.0, "out_qty": 0.0}
            qty = r.get("quantity", 0) or 0
            if r.get("movement_type") == "进货":
                groups[key]["in_qty"] += qty
            else:
                groups[key]["out_qty"] += qty
        result = list(groups.values())
        for g in result:
            g["balance"] = g["in_qty"] - g["out_qty"]
        result.sort(key=lambda g: (-g["balance"], g["customer"]))
        return result


class InkStockRepository:
    """
    油墨进出库记录仓储 —— 跟"进销存管理"（成品货物进出）是两码事，
    这个专门记录【油墨原料本身】的采购入库/生产消耗出库流水，
    包含价格、客户（消耗时对应哪个客户的订单）、数量、备注。

    ink_stock_record 结构：
    {
        "id": "IS-20260709103000",
        "date": "2026-07-09",
        "movement_type": "入库",         # 入库(采购) 或 出库(消耗/领用)
        "ink_code": "K-001",
        "ink_name": "黑色 Black (炭黑)",
        "quantity_ml": 5000,
        "price": 0.08,                    # 入库时是采购单价(元/ml)，出库时可留空或填成本价
        "amount": 400.0,                  # 数量*单价
        "supplier": "某某油墨贸易公司",    # 入库时：供应商
        "customer": "客户A",              # 出库时：对应哪个客户的订单领用
        "notes": "",
        "created_at": "2026-07-09 10:30",
    }
    """

    def __init__(self, path: str = INK_STOCK_RECORDS_PATH):
        self.path = path

    def load_all(self) -> List[Dict]:
        records = _load_json(self.path, [])
        records.sort(key=lambda r: (r.get("date", ""), r.get("created_at", "")), reverse=True)
        return records

    def get_by_id(self, record_id: str) -> Optional[Dict]:
        for item in self.load_all():
            if item["id"] == record_id:
                return item
        return None

    def upsert(self, record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item["id"] == record["id"]:
                    records[i] = record
                    return records
            records.append(record)
            return records
        _update_json(self.path, _mut, [])

    def delete(self, record_id: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["id"] != record_id]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]


    def count_for_ink(self, ink_code: str) -> int:
        """某支油墨有多少条进出库流水。删除油墨档案前用它来提醒用户。"""
        return sum(1 for r in _load_json(self.path, []) if r.get("ink_code") == ink_code)


# 角色权限表：每个角色能看到哪些页面（页面key对应main_window里的导航项）。
# 放在DAL层是因为这是"数据/配置"性质的常量，UI层和登录逻辑都要用到，
# 避免循环依赖或者在UI层散落多份定义。
PAGE_LABELS = {
    "workbench": "配色工作台",
    "print_job": "多色印刷工单",
    "ink_library": "油墨库管理",
    "bottle": "瓶身识别",
    "product": "产品管理",
    "production": "生产追踪",
    "inventory": "进销存管理",
    "finance": "财务管理",
    "ink_stock": "油墨库存管理",
    "company": "公司信息",
    "users": "账户管理",
}

ROLE_PERMISSIONS = {
    "管理员": {
        "workbench", "print_job", "ink_library", "bottle", "product",
        "production", "inventory", "finance", "ink_stock", "company", "users",
    },
    # 财务是敏感数据（客户报价、欠款）。文员管单据录入和对账，给财务权限；
    # 丝印师傅只管生产，不该看到钱的事；仓管管货不管账。
    "文员": {"product", "inventory", "finance", "company"},
    "丝印师傅": {"workbench", "print_job", "ink_library", "bottle", "production"},
    "仓管": {"ink_library", "inventory", "ink_stock"},
}

ROLE_LIST = list(ROLE_PERMISSIONS.keys())


def _hash_password(password: str, salt: str) -> str:
    """
    密码哈希：用 PBKDF2-HMAC-SHA256，迭代 200,000 次。

    为什么不直接用一次SHA256：普通SHA256算一次只要微秒级，别人拿到
    哈希值之后可以用普通显卡每秒试几十亿次密码，加盐也挡不住暴力破解。
    PBKDF2故意把每次验证的计算成本拉高（迭代20万次），让批量暴力破解
    的成本高到不现实，这是密码存储的标准做法（不需要装额外的库，
    Python标准库hashlib自带）。
    """
    import hashlib
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()


class UserRepository:
    """
    用户账户仓储 —— 本地单机多账户登录 + 角色权限用。

    ⚠️ 安全说明：这是"同一台电脑，不同岗位登录看到不同功能"这个场景
    下的轻量级账户体系，密码用加盐哈希存储，能防止别人打开数据文件
    直接看到明文密码，但这不是企业级的网络身份认证系统——不能替代
    真正的服务器端账户体系。如果以后要做"异地远程访问"，需要重新
    设计一套服务器端认证机制，这里的账户数据不能直接照搬过去用。

    user_record 结构：
    {
        "username": "boss",
        "display_name": "王老板",
        "password_hash": "...",
        "salt": "...",
        "role": "管理员",
        "created_at": "2026-07-11 10:00",
    }
    """

    def __init__(self, path: str = USERS_PATH):
        self.path = path
        self._ensure_default_admin()

    def load_all(self) -> List[Dict]:
        return _load_json(self.path, [])

    def get_by_username(self, username: str) -> Optional[Dict]:
        for u in self.load_all():
            if u["username"] == username:
                return u
        return None

    def _ensure_default_admin(self):
        """首次运行、账户表为空时，自动建一个默认主账户，避免把自己锁在门外。"""
        if self.load_all():
            return
        import os as _os, datetime as _dt
        salt = _os.urandom(8).hex()
        self.upsert({
            "username": "admin",
            "display_name": "系统管理员",
            "password_hash": _hash_password("admin123", salt),
            "salt": salt,
            "role": "管理员",
            "permissions": sorted(ROLE_PERMISSIONS["管理员"]),
            # ── 层级账户体系（v40 新增）──────────────────────────────
            # account_type 决定这个账户在体系里的位置和能做什么：
            #   super  主账户（admin）：最高权限，谁都动不了它。可以创建子管理员，
            #          并给每个子管理员分配"能建几个子账户"的配额。
            #   admin  子管理员：admin 创建的下级管理员。只能管【自己创建的】账户，
            #          看不到、也改不了别人（包括 admin 本身和其他子管理员）的账户。
            #          【不能再创建管理员】——防止管理员无限繁殖、权限失控。
            #   staff  普通员工账户：不能进账户管理页。
            "account_type": "super",
            "created_by": None,          # 主账户没有创建者
            "max_sub_accounts": None,    # 主账户不限量
            "failed_attempts": 0,
            "locked_until": None,
            "created_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    # ══════════════════════════════════════════════════════════════════
    # 层级账户体系：账户类型 / 归属 / 可管辖范围
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def account_type_of(user_record: Dict) -> str:
        """
        取账户类型。

        优先用明确的 account_type 字段，但有一个重要的一致性兜底：
        如果字段说是 staff、可这个账户实际上却有 users（账户管理）权限，
        那字段就是错的（多半是老数据，或调用方建账户时没传 account_type）。
        这种矛盾状态下【以权限为准】判成 super——否则会出现"能进账户管理页、
        却被当成员工而不能创建管理员"的自相矛盾。

        老数据（v40 之前建的，压根没有 account_type 字段）也走同一套推断：
        有 users 权限 → super，其余 → staff。
        """
        has_users = "users" in UserRepository.effective_permissions(user_record)
        t = user_record.get("account_type")
        if t in ("super", "admin", "staff"):
            # 字段说 staff 但实际有账户管理权 → 矛盾，以权限为准
            if t == "staff" and has_users:
                return "super"
            return t
        # 没有字段，按权限推断
        return "super" if has_users else "staff"

    @staticmethod
    def is_super(user_record: Dict) -> bool:
        return UserRepository.account_type_of(user_record) == "super"

    @staticmethod
    def can_manage_accounts(user_record: Dict) -> bool:
        """能不能进【账户管理】页：主账户和子管理员可以，普通员工不行。"""
        return UserRepository.account_type_of(user_record) in ("super", "admin")

    @staticmethod
    def can_create_admin(user_record: Dict) -> bool:
        """
        能不能创建【管理员】账户：只有主账户可以。

        这是问题1的核心修复：子管理员不能再创建管理员，否则会无限繁殖，
        而且一个子管理员建的管理员又能建管理员，整个权限体系就失控了。
        """
        return UserRepository.account_type_of(user_record) == "super"

    def visible_accounts_for(self, viewer: Dict) -> List[Dict]:
        """
        这个账户在【账户管理】页能看到哪些账户。这是问题1的另一半修复：
        子管理员只能看到【自己创建的】账户，看不到 admin、也看不到别的子管理员。

          · 主账户(super)：看到全部账户
          · 子管理员(admin)：只看到自己 + 自己创建的账户
          · 普通员工(staff)：进不了这个页面，返回空
        """
        vtype = self.account_type_of(viewer)
        vname = viewer.get("username")
        all_users = self.load_all()

        if vtype == "super":
            return all_users
        # viewer 自己没有 username（残缺记录）——无法安全判断归属，只返回它自己，
        # 避免 None == None 误匹配到一堆同样残缺的账户
        if vtype == "admin" and vname:
            return [
                u for u in all_users
                if u.get("username") == vname or u.get("created_by") == vname
            ]
        return []

    def count_sub_accounts(self, creator_username: str) -> int:
        """某个管理员已经创建了多少个子账户（用于配额检查）。"""
        return sum(1 for u in self.load_all() if u.get("created_by") == creator_username)

    def can_manage_target(self, viewer: Dict, target_username: str) -> bool:
        """
        viewer 有没有权限对 target 这个账户动手（编辑/删除/改权限/重置密码）。

        规则：
          · 主账户可以管任何人（除了下面的最后管理员保护另说）
          · 子管理员只能管自己创建的账户；碰 admin 或别的子管理员，一律拒绝
          · 谁都不能通过这个接口去动比自己层级高的账户
        """
        if viewer.get("username") == target_username:
            return True   # 管自己（改自己资料）总是允许，具体字段限制在别处控制
        vtype = self.account_type_of(viewer)
        if vtype == "super":
            return True
        if vtype == "admin":
            target = self.get_by_username(target_username)
            if target is None:
                return False
            vname = viewer.get("username")
            # viewer 没 username 时无法安全判断归属，直接拒绝（None==None 会误放行）
            if not vname:
                return False
            # 只能管自己创建的、且对方必须是 staff（不能管别的管理员）
            return (target.get("created_by") == vname
                    and self.account_type_of(target) == "staff")
        return False

    def upsert(self, user_record: Dict) -> None:
        def _mut(records):
            for i, item in enumerate(records):
                if item["username"] == user_record["username"]:
                    records[i] = user_record
                    return records
            records.append(user_record)
            return records
        _update_json(self.path, _mut, [])

    def purge_ink_allocations(self, ink_code: str) -> int:
        """
        某支油墨被从油墨库里删除后，把所有账户里对它的分配额度和用量记录一并清掉。

        不清会怎样：users.json 里留着一条指向已经不存在的油墨的分配记录（悬空引用）。
        表面上看不出问题，但会导致——
          · 【账户管理】的分配列表里那一行变成空白/报错
          · get_ink_allocations() 返回的集合里混着幽灵编号，权限过滤时
            多放行一个根本不存在的墨
          · 万一以后有人新建油墨时复用了同一个编号（比如 R-001 删了又建），
            旧的分配额度会莫名其妙地"复活"扣到新墨头上

        返回受影响的账户数。
        """
        users = self.load_all()
        affected = 0
        for u in users:
            touched = False
            allocations = u.get("ink_allocations")
            if isinstance(allocations, dict) and ink_code in allocations:
                del allocations[ink_code]
                touched = True
            usage = u.get("ink_usage")
            if isinstance(usage, dict) and ink_code in usage:
                del usage[ink_code]
                touched = True
            if touched:
                affected += 1
        if affected:
            _save_json(self.path, users)
        return affected

    def update_user(self, username: str, display_name: str = None, role: str = None,
                    permissions: List[str] = None, ink_allocations: Dict = None) -> bool:
        """
        修改一个已有账户的资料/权限/油墨额度。

        ⚠️ 这个方法存在的意义：以前【账户管理】页只有"新增/重置密码/删除"，
        没有任何编辑入口。老板想给某个师傅加一个页面权限，唯一的办法是把他
        删掉再建一个同名的——而这会把他的 `ink_usage`（已用油墨量）一起抹掉，
        额度被偷偷重置回满值。实测：师傅已用 250ml/300ml，删了重建之后
        剩余额度又变回 300ml，等于凭空多出 250ml 可以领。这是个会漏油墨的洞。

        所以改账户必须是"原地改"：
          · password_hash / salt 不动（不用重设密码）
          · ink_usage 不动（已经用掉的量必须留着）
          · failed_attempts / locked_until 不动（不能靠改资料来解锁）
        只有明确传进来的字段才会被覆盖，传 None 的一律保持原样。
        """
        found = [False]
        def _mut(users):
            for i, u in enumerate(users):
                if u["username"] != username:
                    continue
                if display_name is not None:
                    u["display_name"] = display_name
                if role is not None:
                    u["role"] = role
                if permissions is not None:
                    u["permissions"] = sorted(set(permissions))
                if ink_allocations is not None:
                    # ⚠️ 格式必须和 create_user / set_ink_allocations 完全一致：
                    # 扁平的 {油墨编号: 毫升数}，不是嵌套字典。
                    u["ink_allocations"] = {
                        code: float(limit)
                        for code, limit in ink_allocations.items()
                    }
                users[i] = u
                found[0] = True
                return users
            return None   # 没这个用户，不用写
        _update_json(self.path, _mut, [])
        return found[0]

    def count_admins(self) -> int:
        """
        有多少个账户还握着"账户管理"权限。

        判断依据是 effective_permissions 里有没有 "users"，不是看角色名叫不叫
        "管理员"——角色只是个填权限的模板，真值永远在权限位上。
        """
        return sum(
            1 for u in self.load_all()
            if "users" in UserRepository.effective_permissions(u)
        )

    def would_orphan_admin(self, username: str, new_permissions: List[str] = None) -> bool:
        """
        这个操作会不会把系统变成"没有任何人能管账户"的砖？

        两种情况会中招：
          · 删掉最后一个有 users 权限的账户
          · 把最后一个管理员的 users 权限取消掉（比删除更隐蔽，更容易手滑）

        一旦发生，谁也进不了【账户管理】页，就再也没法给任何人授权、
        也没法把权限改回来——只能去手动改 users.json，普通用户根本不会。
        所以这类操作必须在 UI 上直接拦住。

        new_permissions 传 None 表示"要删除这个账户"；传一个列表表示
        "要把这个账户的权限改成这样"。
        """
        target = self.get_by_username(username)
        if target is None:
            return False
        target_is_admin = "users" in UserRepository.effective_permissions(target)
        if not target_is_admin:
            return False   # 本来就不是管理员，怎么动都不影响

        # 改权限的场景：如果改完还留着 users 权限，那不会出事
        if new_permissions is not None and "users" in new_permissions:
            return False

        # 走到这里说明：这个账户是管理员，而操作之后它就不是了（被删或被降权）
        return self.count_admins() <= 1

    def delete(self, username: str) -> bool:
        deleted = [False]
        def _mut(records):
            new_records = [r for r in records if r["username"] != username]
            if len(new_records) == len(records):
                return None
            deleted[0] = True
            return new_records
        _update_json(self.path, _mut, [])
        return deleted[0]

    def set_password(self, username: str, new_password: str) -> bool:
        import os as _os
        record = self.get_by_username(username)
        if record is None:
            return False
        salt = _os.urandom(8).hex()
        record["salt"] = salt
        record["password_hash"] = _hash_password(new_password, salt)
        self.upsert(record)
        return True

    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15

    def is_locked(self, username: str) -> Optional[str]:
        """账户是否处于锁定状态；是则返回解锁时间文字，否则返回None。"""
        import datetime
        record = self.get_by_username(username)
        if record is None:
            return None
        locked_until = record.get("locked_until")
        if not locked_until:
            return None
        if datetime.datetime.now() < datetime.datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S"):
            return locked_until
        # 锁定时间已过，自动解锁
        record["locked_until"] = None
        record["failed_attempts"] = 0
        self.upsert(record)
        return None

    def verify_password(self, username: str, password: str) -> bool:
        import datetime
        record = self.get_by_username(username)
        if record is None:
            return False

        if self.is_locked(username):
            return False

        ok = _hash_password(password, record.get("salt", "")) == record.get("password_hash", "")
        if ok:
            record["failed_attempts"] = 0
            record["locked_until"] = None
            self.upsert(record)
            return True

        # 密码错误：累计失败次数，达到阈值就锁定一段时间，防止暴力破解密码
        record["failed_attempts"] = record.get("failed_attempts", 0) + 1
        if record["failed_attempts"] >= self.MAX_FAILED_ATTEMPTS:
            unlock_time = datetime.datetime.now() + datetime.timedelta(minutes=self.LOCKOUT_MINUTES)
            record["locked_until"] = unlock_time.strftime("%Y-%m-%d %H:%M:%S")
        self.upsert(record)
        return False

    # ⚠️ 这个列表必须和 PAGE_LABELS 保持完全一致，否则加了新页面却忘了加到这里，
    # 那个页面的权限就永远勾不上——【财务管理】刚上线时就踩过这个坑：PAGE_LABELS
    # 和 ROLE_PERMISSIONS 都加了 finance，唯独漏了这里，结果财务权限根本没法授给
    # 任何子账户，界面上连那个勾选框都不会出现。
    # 所以直接从 PAGE_LABELS 派生，让它没有再漏一次的机会。
    ALL_PAGE_KEYS = list(PAGE_LABELS.keys())

    def get_ink_allocations(self, username: str) -> Optional[Dict[str, float]]:
        """
        取某账户被分配到的油墨及数量上限：{ink_code: 分配毫升数}。
        管理员账户返回None，表示不受分配限制（能用全部在库油墨，不封顶）。
        """
        record = self.get_by_username(username)
        if record is None:
            return None
        if record.get("role") == "管理员":
            return None
        return record.get("ink_allocations", {}) or {}

    def set_ink_allocations(self, username: str, allocations: Dict[str, float]) -> bool:
        """只有调用方（应该是管理员界面）负责校验权限，这里只管存数据。"""
        record = self.get_by_username(username)
        if record is None:
            return False
        record["ink_allocations"] = allocations
        self.upsert(record)
        return True

    def get_remaining_allocation(self, username: str, ink_code: str) -> Optional[float]:
        """
        某账户对某支墨还剩多少可用额度。
        返回None表示不受限制（管理员，或者这支墨压根没被分配给这个账户——
        没分配到的墨在UI层面本来就选不了，这里只是兜底）。
        """
        allocations = self.get_ink_allocations(username)
        if allocations is None:
            return None
        if ink_code not in allocations:
            return 0.0
        record = self.get_by_username(username)
        used = (record.get("ink_usage", {}) or {}).get(ink_code, 0.0) if record else 0.0
        return max(0.0, allocations[ink_code] - used)

    def record_ink_usage(self, username: str, ink_code: str, used_ml: float) -> None:
        record = self.get_by_username(username)
        if record is None:
            return
        usage = record.get("ink_usage", {}) or {}
        usage[ink_code] = usage.get(ink_code, 0.0) + used_ml
        record["ink_usage"] = usage
        self.upsert(record)

    def create_user(self, username: str, display_name: str, password: str, role: str,
                     permissions: Optional[List[str]] = None,
                     ink_allocations: Optional[Dict[str, float]] = None,
                     account_type: str = "staff", created_by: Optional[str] = None,
                     max_sub_accounts: Optional[int] = None) -> bool:
        """
        创建账户。v40 起带层级信息：

          account_type      "super"/"admin"/"staff"，决定这个账户的层级和能力
          created_by        谁创建的（子管理员只能管自己创建的账户，靠这个字段判断）
          max_sub_accounts  如果是子管理员，主账户给它分配的"能建几个子账户"的配额；
                            None 表示不限（只有主账户是 None）
        """
        import os as _os, datetime as _dt
        if self.get_by_username(username):
            return False
        salt = _os.urandom(8).hex()
        self.upsert({
            "username": username,
            "display_name": display_name,
            "password_hash": _hash_password(password, salt),
            "salt": salt,
            "role": role,
            "permissions": permissions if permissions is not None else sorted(ROLE_PERMISSIONS.get(role, set())),
            "ink_allocations": ink_allocations if ink_allocations is not None else {},
            "ink_usage": {},
            "account_type": account_type,
            "created_by": created_by,
            "max_sub_accounts": max_sub_accounts,
            "failed_attempts": 0,
            "locked_until": None,
            "created_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        return True

    def update_permissions(self, username: str, permissions: List[str]) -> bool:
        record = self.get_by_username(username)
        if record is None:
            return False
        record["permissions"] = permissions
        self.upsert(record)
        return True

    @staticmethod
    def effective_permissions(user_record: Dict) -> set:
        """
        取一个账户实际生效的页面权限集合：优先用账户自己的 permissions 字段
        （逐页面精确勾选出来的），没有这个字段的老账户就退回到角色默认权限表，
        保证之前建的账户不会因为升级软件版本突然全部看不到任何页面。
        """
        if "permissions" in user_record and user_record["permissions"] is not None:
            return set(user_record["permissions"])
        return set(ROLE_PERMISSIONS.get(user_record.get("role", ""), set()))
