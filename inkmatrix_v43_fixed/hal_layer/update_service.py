# -*- coding: utf-8 -*-
"""
update_service.py  (HAL层 - 云端更新检查)
================================================
解决你问的问题：**上云服务器之后，客户端怎么知道有新版本、怎么更新。**

── 现在的处境 ──────────────────────────────────────────────────
之前系统压根没有版本概念，也没有任何"跟服务器对话"的接口。客户装了软件就
是一座孤岛：你在服务器上修好了 bug、加了功能，客户那边毫不知情，只能你打
电话让他重新下载覆盖——一个客户还行，几十个客户就是灾难。

── 这个模块提供什么 ────────────────────────────────────────────
一套【最小可用】的更新检查接口。它只做一件事：问服务器"有没有比我新的版本"，
把答案告诉用户，并给出下载地址。它【不】自动下载安装——桌面软件的自动覆盖
安装涉及权限、杀毒、正在运行的进程占用等一堆坑，那是另一个大工程。这一版先
把"能感知到有更新"这个 0→1 的能力建起来。

设计成这样，是因为它符合你的实际情况：
  · 服务器端只需要放一个静态的 version.json（甚至挂在对象存储/CDN 上即可），
    不需要写后端服务，成本最低
  · 客户端定期拉一次，比对版本号，有新版就弹个提示 + 一个"前往下载"的链接
  · 将来要做成自动更新，也是在这个接口之上扩展，不用推倒重来

── 服务器端 version.json 的格式 ────────────────────────────────
    {
      "latest_version": "39",           # 最新版本号
      "min_supported_version": "33",    # 低于这个版本【必须】更新（比如有数据兼容性问题）
      "download_url": "https://你的服务器/InkMatrix_v39.zip",
      "release_notes": "修复了并发丢数据的问题，新增标准专色库…",
      "released_at": "2026-07-15"
    }
"""
import json
import datetime
from typing import Dict, Optional


# 当前这个客户端的版本号。每次发版都要改这里。
APP_VERSION = "41"

# 数据格式版本（跟 data_manager.DATA_SCHEMA_VERSION 对应）。放这里方便更新页一起显示。
try:
    from dal_layer.data_manager import DATA_SCHEMA_VERSION
except ImportError:
    DATA_SCHEMA_VERSION = 1


def _version_tuple(v: str):
    """
    把版本号字符串变成可比较的元组。

    支持 "39"、"1.2.3"、"v39" 这些写法，容错处理——因为版本号是人填的，
    格式难免不统一，不能因为多个 v 前缀就比错。
    """
    v = str(v).strip().lstrip("vV")
    parts = []
    for chunk in v.replace("-", ".").split("."):
        # 只取数字部分，"39beta" → 39
        num = "".join(c for c in chunk if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def compare_versions(a: str, b: str) -> int:
    """a<b 返回-1，a==b 返回0，a>b 返回1。"""
    ta, tb = _version_tuple(a), _version_tuple(b)
    # 补齐长度再比，(39,) vs (39,0,1)
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def check_for_update(version_url: str, timeout: float = 5.0,
                     current_version: str = None) -> Dict:
    """
    去服务器拉 version.json，判断有没有新版本。

    这是【纯函数式】的检查——只读取信息、只做判断，不下载、不安装、不改本地
    任何东西。所以调用它是安全的，随时可以调。

    返回一份结构化结果，UI 拿去显示：
        {
          "ok": bool,                 # 检查本身成功了吗（网络/解析有没有出错）
          "error": str,               # ok=False 时的原因
          "update_available": bool,   # 有没有比我新的版本
          "force_update": bool,       # 我是不是低于最低支持版本（必须更新）
          "current": str,             # 我现在的版本
          "latest": str,              # 服务器上最新版本
          "download_url": str,
          "release_notes": str,
          "released_at": str,
          "checked_at": str,
        }

    网络请求用标准库 urllib，不引第三方依赖——客户机器上少装一个包就少一分
    出问题的可能。超时默认 5 秒，拉不到就当"检查失败"，绝不卡住软件启动。
    """
    current_version = current_version or APP_VERSION
    result = {
        "ok": False, "error": "", "update_available": False, "force_update": False,
        "current": current_version, "latest": None, "download_url": None,
        "release_notes": "", "released_at": "",
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        import urllib.request
        req = urllib.request.Request(
            version_url,
            headers={"User-Agent": f"InkMatrix/{current_version}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        info = json.loads(raw)
    except Exception as e:
        # 网络不通、超时、JSON 坏了……全都归到"检查失败"，不区分细节，
        # 因为对用户来说都是"这次没查到"，重点是别让它影响软件正常使用。
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    latest = str(info.get("latest_version", "")).strip()
    if not latest:
        result["error"] = "服务器返回的版本信息里没有 latest_version 字段"
        return result

    min_supported = str(info.get("min_supported_version", "0")).strip()

    result["ok"] = True
    result["latest"] = latest
    result["download_url"] = info.get("download_url", "")
    result["release_notes"] = info.get("release_notes", "")
    result["released_at"] = info.get("released_at", "")
    result["update_available"] = compare_versions(current_version, latest) < 0
    # 我的版本低于服务器要求的最低版本 → 强制更新（通常意味着有数据兼容性/安全问题）
    result["force_update"] = compare_versions(current_version, min_supported) < 0

    return result


def summarize(result: Dict) -> str:
    """把 check_for_update 的结果转成一句给用户看的话。"""
    if not result.get("ok"):
        return f"检查更新失败：{result.get('error', '未知原因')}。请稍后重试，或检查网络。"
    if result.get("force_update"):
        return (f"⚠️ 你的版本 v{result['current']} 过旧，必须更新到 v{result['latest']} "
                f"才能继续安全使用（可能涉及数据兼容或安全修复）。")
    if result.get("update_available"):
        return f"发现新版本 v{result['latest']}（你当前是 v{result['current']}）。"
    return f"已是最新版本 v{result['current']}。"
