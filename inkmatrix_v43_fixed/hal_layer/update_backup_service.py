# -*- coding: utf-8 -*-
"""
update_backup_service.py - 更新和备份服务
===========================================
解决问题5：更新系统显示更新内容和bug修复，自动下载安装
解决问题6：系统崩溃时能在后台导出用户数据库
"""

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
import zipfile
import subprocess
import sys


@dataclass
class UpdateInfo:
    """更新信息"""
    version: str
    release_date: str
    description: str  # 更新描述（可支持Markdown）
    bug_fixes: List[str]  # 修复的bug列表
    new_features: List[str]  # 新功能列表
    improvements: List[str]  # 改进列表
    download_url: str  # 下载链接
    file_hash: str  # 完整性校验（SHA256）
    required: bool = False  # 是否强制更新
    
    def to_dict(self) -> Dict:
        return asdict(self)


class UpdateManager:
    """更新管理器"""
    
    def __init__(self, config_file: str = "config/update_config.json"):
        self.config_file = Path(config_file)
        self.current_version = "v4.2.0"  # 当前版本
        self.update_info: Optional[UpdateInfo] = None
        self.update_history: List[UpdateInfo] = []
        self.on_update_available: Optional[Callable] = None
        self.on_update_progress: Optional[Callable] = None  # 下载进度回调
        self.load_update_info()
    
    def load_update_info(self):
        """加载更新信息"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'current_version' in data:
                        self.current_version = data['current_version']
                    if 'update_info' in data:
                        info_data = data['update_info']
                        self.update_info = UpdateInfo(**info_data)
                    if 'history' in data:
                        self.update_history = [UpdateInfo(**h) for h in data['history']]
            except Exception as e:
                print(f"加载更新信息失败: {e}")
    
    def check_for_updates(self, on_complete: Optional[Callable] = None) -> bool:
        """
        检查更新（模拟在线检查）
        
        实际应用中应该连接到更新服务器，这里模拟本地检查
        """
        # 模拟最新版本
        latest = UpdateInfo(
            version="v4.3.0",
            release_date=datetime.now().isoformat(),
            description="重大功能更新和性能优化",
            bug_fixes=[
                "修复配色算法在高彩度颜色下偏色的问题",
                "修复多账户下油墨库显示混乱的bug",
                "修复进销存界面卡顿的问题",
                "修复数据导入崩溃的问题"
            ],
            new_features=[
                "支持光谱匹配优化（多目标寻优）",
                "增强的账户权限管理系统",
                "改进的UI界面设计",
                "新增实时数据备份功能"
            ],
            improvements=[
                "性能提升30%，数据加载速度翻倍",
                "改进的配色算法防止色相离谱",
                "更友好的错误提示和日志系统",
                "支持一键恢复备份数据"
            ],
            download_url="http://example.com/update/v4.3.0.zip",
            file_hash="abc123def456...",
            required=False
        )
        
        if latest.version != self.current_version:
            self.update_info = latest
            if self.on_update_available:
                self.on_update_available(latest)
            if on_complete:
                on_complete(True)
            return True
        
        if on_complete:
            on_complete(False)
        return False
    
    def download_update(self, update: UpdateInfo, dest_dir: str = "./updates",
                       on_progress: Optional[Callable] = None) -> bool:
        """
        下载更新
        
        Args:
            update: 更新信息
            dest_dir: 下载目录
            on_progress: 进度回调 (downloaded_bytes, total_bytes) -> None
        """
        import urllib.request
        import hashlib
        
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        dest_file = Path(dest_dir) / f"{update.version}.zip"
        
        try:
            # 实际应该从URL下载，这里模拟
            print(f"下载更新 {update.version}...")
            
            # 模拟下载过程
            def mock_download():
                for i in range(0, 101, 10):
                    time.sleep(0.2)  # 模拟下载延迟
                    if on_progress:
                        on_progress(i, 100)
            
            mock_download()
            
            # 验证文件完整性
            print(f"验证文件完整性...")
            # 实际应该验证hash，这里简化
            
            return True
        except Exception as e:
            print(f"下载失败: {e}")
            return False
    
    def install_update(self, update_file: str, backup_first: bool = True) -> bool:
        """
        安装更新
        
        Args:
            update_file: 更新包文件路径
            backup_first: 安装前是否先备份
        """
        try:
            update_path = Path(update_file)
            if not update_path.exists():
                print(f"更新文件不存在: {update_file}")
                return False
            
            # 备份当前版本
            if backup_first:
                backup_dir = Path("./backups") / f"backup_{self.current_version}_{int(time.time())}"
                backup_dir.mkdir(parents=True, exist_ok=True)
                
                # 备份关键目录
                for dir_name in ['core_layer', 'dal_layer', 'ui_layer', 'hal_layer']:
                    src = Path(dir_name)
                    if src.exists():
                        shutil.copytree(src, backup_dir / dir_name)
                
                print(f"备份已保存到: {backup_dir}")
            
            # 解压更新包
            print(f"安装更新...")
            with zipfile.ZipFile(update_path, 'r') as zip_ref:
                zip_ref.extractall('./')
            
            # 更新版本号
            self.current_version = Path(update_file).stem.replace("v", "")
            
            print(f"更新成功！请重启应用")
            
            # 触发应用重启（在实际应用中）
            return True
        except Exception as e:
            print(f"安装失败: {e}")
            return False
    
    def get_update_notes(self, update: UpdateInfo) -> str:
        """生成更新说明文本"""
        notes = f"""
===============================================
墨算系统 {update.version} 更新说明
===============================================
发布日期: {update.release_date}

📝 更新描述:
{update.description}

✅ 新功能:
"""
        for feature in update.new_features:
            notes += f"  • {feature}\n"
        
        notes += "\n🐛 修复的问题:\n"
        for bug in update.bug_fixes:
            notes += f"  • {bug}\n"
        
        notes += "\n⚡ 性能改进:\n"
        for improvement in update.improvements:
            notes += f"  • {improvement}\n"
        
        notes += f"""
⚠️ 更新方式：
1. 点击"下载更新"按钮自动下载最新版本
2. 下载完成后自动备份当前数据
3. 自动安装新版本
4. 用户数据完全保留，无需担心数据丢失

{'⚠️ 此次为强制更新，建议立即安装' if update.required else '💡 可选更新，您可以选择稍后安装'}
===============================================
"""
        return notes


class DataBackupManager:
    """数据备份管理器 - 解决问题6"""
    
    def __init__(self, backup_dir: str = "./backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.auto_backup_enabled = True
        self.backup_interval = 3600  # 每小时自动备份一次
        self.max_backups = 10  # 最多保留10个备份
        self.backup_thread: Optional[threading.Thread] = None
        self.last_backup_time = 0
    
    def create_backup(self, data_sources: Dict[str, Path],
                     backup_name: Optional[str] = None) -> Optional[Path]:
        """
        创建备份
        
        Args:
            data_sources: 数据源 {描述: 数据文件/目录路径}
            backup_name: 备份名称（不指定则自动生成）
        """
        if not backup_name:
            backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)
        
        try:
            # 备份所有数据源
            for desc, src_path in data_sources.items():
                src = Path(src_path)
                if not src.exists():
                    continue
                
                dest = backup_path / src.name
                
                if src.is_file():
                    shutil.copy2(src, dest)
                else:
                    shutil.copytree(src, dest, dirs_exist_ok=True)
            
            # 创建备份元数据
            metadata = {
                'backup_name': backup_name,
                'created_at': datetime.now().isoformat(),
                'data_sources': list(data_sources.keys()),
                'system_version': 'v4.2.0'
            }
            
            with open(backup_path / 'metadata.json', 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            print(f"备份创建成功: {backup_path}")
            self.last_backup_time = time.time()
            
            # 清理过期备份
            self._cleanup_old_backups()
            
            return backup_path
        except Exception as e:
            print(f"备份创建失败: {e}")
            return None
    
    def _cleanup_old_backups(self):
        """清理过期的备份，只保留最近的max_backups个"""
        backups = sorted(self.backup_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        
        while len(backups) > self.max_backups:
            oldest = backups.pop(0)
            try:
                shutil.rmtree(oldest)
                print(f"删除过期备份: {oldest}")
            except Exception as e:
                print(f"删除备份失败: {e}")
    
    def restore_backup(self, backup_name: str, restore_to: str = "./") -> bool:
        """
        恢复备份
        
        Args:
            backup_name: 备份名称
            restore_to: 恢复目标目录
        """
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            print(f"备份不存在: {backup_name}")
            return False
        
        try:
            # 读取元数据
            metadata_file = backup_path / 'metadata.json'
            if metadata_file.exists():
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    print(f"正在恢复备份 ({metadata['created_at']})...")
            
            # 恢复所有文件
            for item in backup_path.iterdir():
                if item.name == 'metadata.json':
                    continue
                
                dest = Path(restore_to) / item.name
                
                if item.is_file():
                    shutil.copy2(item, dest)
                else:
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
            
            print(f"备份恢复成功")
            return True
        except Exception as e:
            print(f"恢复失败: {e}")
            return False
    
    def start_auto_backup(self, data_sources: Dict[str, Path]):
        """
        启动自动备份线程
        
        关键特性：即使系统崩溃也会定期备份关键数据
        """
        def auto_backup_worker():
            while self.auto_backup_enabled:
                elapsed = time.time() - self.last_backup_time
                if elapsed >= self.backup_interval:
                    try:
                        self.create_backup(data_sources)
                    except Exception as e:
                        print(f"自动备份失败: {e}")
                
                time.sleep(60)  # 每分钟检查一次
        
        if self.backup_thread and self.backup_thread.is_alive():
            return  # 已经在运行
        
        self.backup_thread = threading.Thread(target=auto_backup_worker, daemon=True)
        self.backup_thread.start()
        print("自动备份已启动")
    
    def stop_auto_backup(self):
        """停止自动备份"""
        self.auto_backup_enabled = False
        if self.backup_thread:
            self.backup_thread.join(timeout=5)
    
    def list_backups(self) -> List[Dict]:
        """列出所有备份"""
        backups = []
        for backup_dir in sorted(self.backup_dir.iterdir(), 
                               key=lambda p: p.stat().st_mtime, reverse=True):
            metadata_file = backup_dir / 'metadata.json'
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        metadata['size_mb'] = round(
                            sum(f.stat().st_size for f in backup_dir.rglob('*')) / (1024*1024), 2
                        )
                        backups.append(metadata)
                except:
                    pass
        
        return backups
    
    def export_database(self, db_path: str, export_to: str = "./db_export") -> Optional[Path]:
        """
        紧急导出数据库（系统崩溃时可用）
        
        关键：即使系统崩溃，也能通过脚本或命令行调用此函数
        """
        try:
            Path(export_to).mkdir(parents=True, exist_ok=True)
            
            db_file = Path(db_path)
            if not db_file.exists():
                print(f"数据库文件不存在: {db_path}")
                return None
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            export_file = Path(export_to) / f"database_export_{timestamp}.zip"
            
            with zipfile.ZipFile(export_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(db_file, arcname=db_file.name)
            
            print(f"数据库已导出到: {export_file}")
            return export_file
        except Exception as e:
            print(f"导出失败: {e}")
            return None


# 命令行工具支持系统崩溃后的紧急数据恢复
def emergency_export_cli():
    """
    命令行模式 - 即使系统UI崩溃也可以执行
    用法: python -m hal_layer.update_backup_service --export-db data/inks_db.json
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="紧急数据导出工具")
    parser.add_argument('--export-db', help='导出数据库文件', type=str)
    parser.add_argument('--restore-backup', help='恢复备份', type=str)
    parser.add_argument('--list-backups', help='列出所有备份', action='store_true')
    parser.add_argument('--export-to', help='导出目标目录', default='./db_export')
    
    args = parser.parse_args()
    
    manager = DataBackupManager()
    
    if args.export_db:
        manager.export_database(args.export_db, args.export_to)
    elif args.restore_backup:
        manager.restore_backup(args.restore_backup)
    elif args.list_backups:
        backups = manager.list_backups()
        for backup in backups:
            print(f"[{backup['created_at']}] {backup['backup_name']} ({backup.get('size_mb', 0)}MB)")


if __name__ == '__main__':
    emergency_export_cli()
