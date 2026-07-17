# -*- coding: utf-8 -*-
"""
performance_optimizer.py - 性能优化模块
==========================================
解决问题1：系统反应迟钝、关键数据加载很卡

优化策略：
1. 数据缓存和预加载
2. 异步加载关键数据
3. 数据库查询优化
4. UI线程解耦（重计算单独线程）
5. 增量更新而非全量刷新
"""

import threading
import time
from typing import Dict, List, Callable, Any, Optional
from functools import lru_cache
import json
from pathlib import Path


class PerformanceCache:
    """多层缓存系统"""
    
    def __init__(self, cache_dir: str = "./cache"):
        self.memory_cache: Dict[str, Any] = {}
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.lock = threading.RLock()
    
    def get(self, key: str, default=None) -> Any:
        """从缓存获取(先查内存，再查磁盘)"""
        with self.lock:
            # 1. 内存缓存
            if key in self.memory_cache:
                return self.memory_cache[key]
            
            # 2. 磁盘缓存
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.memory_cache[key] = data  # 读入内存
                        return data
                except:
                    pass
        
        return default
    
    def set(self, key: str, value: Any, persist_to_disk: bool = False):
        """设置缓存"""
        with self.lock:
            self.memory_cache[key] = value
            if persist_to_disk:
                try:
                    cache_file = self.cache_dir / f"{key}.json"
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(value, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"缓存写入失败: {e}")
    
    def clear(self, key: Optional[str] = None):
        """清除缓存"""
        with self.lock:
            if key:
                self.memory_cache.pop(key, None)
            else:
                self.memory_cache.clear()


class AsyncDataLoader:
    """异步数据加载器 - 后台加载，不阻塞UI"""
    
    def __init__(self):
        self.queue: Dict[str, threading.Thread] = {}
        self.callbacks: Dict[str, List[Callable]] = {}
        self.results: Dict[str, Any] = {}
    
    def load_async(self, task_id: str, loader_func: Callable,
                  on_complete: Optional[Callable] = None):
        """
        异步加载数据
        
        Args:
            task_id: 任务标识
            loader_func: 加载函数 () -> data
            on_complete: 完成回调 (data) -> None
        """
        if task_id in self.queue and self.queue[task_id].is_alive():
            return  # 避免重复加载
        
        if on_complete:
            if task_id not in self.callbacks:
                self.callbacks[task_id] = []
            self.callbacks[task_id].append(on_complete)
        
        def worker():
            try:
                result = loader_func()
                self.results[task_id] = result
                
                # 触发所有回调
                if task_id in self.callbacks:
                    for callback in self.callbacks[task_id]:
                        try:
                            callback(result)
                        except Exception as e:
                            print(f"回调执行失败: {e}")
                    del self.callbacks[task_id]
            except Exception as e:
                print(f"加载任务 {task_id} 失败: {e}")
                self.results[task_id] = None
        
        thread = threading.Thread(target=worker, daemon=True)
        self.queue[task_id] = thread
        thread.start()
    
    def wait_for(self, task_id: str, timeout: float = 30.0) -> Any:
        """阻塞等待某个任务完成"""
        if task_id in self.queue:
            self.queue[task_id].join(timeout)
        return self.results.get(task_id)
    
    def is_ready(self, task_id: str) -> bool:
        """检查是否已完成"""
        return task_id not in self.queue or not self.queue[task_id].is_alive()


class QueryOptimizer:
    """数据库查询优化 - 减少冗余查询"""
    
    def __init__(self):
        self.query_cache: Dict[str, Tuple[Any, float]] = {}
        self.cache_ttl = 60.0  # 缓存60秒
    
    def cached_query(self, query_key: str, query_func: Callable) -> Any:
        """
        带超时的缓存查询
        """
        now = time.time()
        
        if query_key in self.query_cache:
            result, timestamp = self.query_cache[query_key]
            if now - timestamp < self.cache_ttl:
                return result
        
        # 缓存未命中或已过期
        result = query_func()
        self.query_cache[query_key] = (result, now)
        return result
    
    def invalidate(self, pattern: Optional[str] = None):
        """使缓存失效"""
        if pattern is None:
            self.query_cache.clear()
        else:
            # 删除匹配pattern的缓存项
            keys_to_delete = [k for k in self.query_cache if pattern in k]
            for k in keys_to_delete:
                del self.query_cache[k]


class BatchProcessor:
    """批量处理器 - 合并小任务减少总次数"""
    
    def __init__(self, batch_size: int = 100, flush_interval: float = 0.5):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: List[Callable] = []
        self.timer: Optional[threading.Timer] = None
        self.lock = threading.RLock()
    
    def add_task(self, task: Callable):
        """添加任务"""
        with self.lock:
            self.queue.append(task)
            
            if len(self.queue) >= self.batch_size:
                self._flush()
            elif self.timer is None:
                # 启动定时器：若干秒后自动flush
                self.timer = threading.Timer(self.flush_interval, self._flush)
                self.timer.daemon = True
                self.timer.start()
    
    def _flush(self):
        """执行所有待处理任务"""
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            
            for task in self.queue:
                try:
                    task()
                except Exception as e:
                    print(f"批处理任务执行失败: {e}")
            
            self.queue.clear()


class UIUpdateOptimizer:
    """UI更新优化 - 合并多个小更新为一个大更新"""
    
    def __init__(self, debounce_time: float = 0.2):
        self.debounce_time = debounce_time
        self.pending_updates: Dict[str, Any] = {}
        self.timer: Optional[threading.Timer] = None
        self.lock = threading.RLock()
        self.on_batch_update: Optional[Callable] = None
    
    def schedule_update(self, component_id: str, update_data: Any):
        """
        计划一个UI更新(不立即执行，等待合并)
        """
        with self.lock:
            self.pending_updates[component_id] = update_data
            
            # 取消之前的定时器
            if self.timer:
                self.timer.cancel()
            
            # 启动新定时器：debounce_time后执行所有待处理更新
            self.timer = threading.Timer(self.debounce_time, self._flush)
            self.timer.daemon = True
            self.timer.start()
    
    def _flush(self):
        """执行所有待处理的UI更新"""
        with self.lock:
            if self.on_batch_update and self.pending_updates:
                self.on_batch_update(self.pending_updates.copy())
            self.pending_updates.clear()


class PerformanceMonitor:
    """性能监控 - 识别瓶颈"""
    
    def __init__(self):
        self.timings: Dict[str, List[float]] = {}
    
    def record(self, operation_name: str, elapsed_time: float):
        """记录操作耗时"""
        if operation_name not in self.timings:
            self.timings[operation_name] = []
        self.timings[operation_name].append(elapsed_time)
        
        # 只保留最近100次记录
        if len(self.timings[operation_name]) > 100:
            self.timings[operation_name] = self.timings[operation_name][-100:]
    
    def get_stats(self, operation_name: str) -> Dict[str, float]:
        """获取某个操作的统计信息"""
        if operation_name not in self.timings or not self.timings[operation_name]:
            return {}
        
        times = self.timings[operation_name]
        return {
            "count": len(times),
            "avg": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
            "last": times[-1]
        }
    
    def report(self) -> str:
        """生成性能报告"""
        report = "=== 性能监控报告 ===\n"
        for op_name in sorted(self.timings.keys()):
            stats = self.get_stats(op_name)
            if stats:
                report += (f"{op_name}: "
                          f"平均{stats['avg']:.3f}s, "
                          f"最后{stats['last']:.3f}s, "
                          f"最大{stats['max']:.3f}s\n")
        return report


# 全局实例
_cache = PerformanceCache()
_async_loader = AsyncDataLoader()
_query_optimizer = QueryOptimizer()
_batch_processor = BatchProcessor()
_ui_updater = UIUpdateOptimizer()
_monitor = PerformanceMonitor()


def get_cache() -> PerformanceCache:
    """获取全局缓存"""
    return _cache


def get_async_loader() -> AsyncDataLoader:
    """获取异步加载器"""
    return _async_loader


def get_query_optimizer() -> QueryOptimizer:
    """获取查询优化器"""
    return _query_optimizer


def get_batch_processor() -> BatchProcessor:
    """获取批处理器"""
    return _batch_processor


def get_ui_updater() -> UIUpdateOptimizer:
    """获取UI更新优化器"""
    return _ui_updater


def get_monitor() -> PerformanceMonitor:
    """获取性能监控"""
    return _monitor
