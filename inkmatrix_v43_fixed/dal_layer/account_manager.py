# -*- coding: utf-8 -*-
"""
account_manager.py - 增强的账户和权限管理
==============================================
解决问题4：
- 多账户的油墨数量配置独立显示
- 非admin账户的油墨库权限管理
- 账户级别的功能权限控制
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib


@dataclass
class AccountPermissions:
    """账户权限定义"""
    # 油墨库相关权限
    can_edit_ink_library: bool = False  # 编辑油墨档案
    can_import_inks: bool = False       # 导入油墨
    can_load_standard_color: bool = False  # 载入标准专色库
    can_create_new_inks: bool = False      # 新增油墨档案
    can_delete_inks: bool = False          # 删除选中油墨
    
    # 报表权限
    can_view_reports: bool = False
    can_export_reports: bool = False
    
    # 系统管理权限
    is_admin: bool = False
    is_system_owner: bool = False  # 系统所有者（可管理所有账户和油墨库）
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @staticmethod
    def default_admin() -> 'AccountPermissions':
        """默认admin权限"""
        return AccountPermissions(
            can_edit_ink_library=True,
            can_import_inks=True,
            can_load_standard_color=True,
            can_create_new_inks=True,
            can_delete_inks=True,
            can_view_reports=True,
            can_export_reports=True,
            is_admin=True,
            is_system_owner=True
        )
    
    @staticmethod
    def default_user() -> 'AccountPermissions':
        """默认普通用户权限（只能查看和使用）"""
        return AccountPermissions(
            can_view_reports=True,
            can_export_reports=False,
            is_admin=False,
            is_system_owner=False
        )
    
    @staticmethod
    def seller_user() -> 'AccountPermissions':
        """卖家用户权限（可管理自己的油墨库）"""
        return AccountPermissions(
            can_edit_ink_library=True,
            can_import_inks=True,
            can_load_standard_color=True,
            can_create_new_inks=True,
            can_delete_inks=True,
            can_view_reports=True,
            can_export_reports=True,
            is_admin=False,
            is_system_owner=False
        )


@dataclass
class UserAccount:
    """用户账户"""
    username: str
    user_id: str  # 唯一标识
    password_hash: str
    display_name: str
    account_type: str  # 'admin' / 'seller' / 'user'
    permissions: AccountPermissions
    
    # 账户特有的配置
    ink_inventory_count: Dict[str, float] = None  # 该账户的油墨库存 {ink_code: quantity}
    default_print_job_template: Optional[Dict] = None  # 默认工单模板
    
    created_at: str = ""
    last_login: str = ""
    is_active: bool = True
    
    def __post_init__(self):
        if self.ink_inventory_count is None:
            self.ink_inventory_count = {}
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self, exclude_password: bool = True) -> Dict:
        """转换为字典"""
        data = {
            'username': self.username,
            'user_id': self.user_id,
            'display_name': self.display_name,
            'account_type': self.account_type,
            'permissions': self.permissions.to_dict(),
            'ink_inventory_count': self.ink_inventory_count,
            'created_at': self.created_at,
            'last_login': self.last_login,
            'is_active': self.is_active
        }
        if not exclude_password:
            data['password_hash'] = self.password_hash
        return data
    
    @staticmethod
    def from_dict(data: Dict) -> 'UserAccount':
        """从字典创建"""
        perms = AccountPermissions(**data.get('permissions', {}))
        return UserAccount(
            username=data['username'],
            user_id=data['user_id'],
            password_hash=data.get('password_hash', ''),
            display_name=data.get('display_name', data['username']),
            account_type=data.get('account_type', 'user'),
            permissions=perms,
            ink_inventory_count=data.get('ink_inventory_count', {}),
            created_at=data.get('created_at', ''),
            last_login=data.get('last_login', ''),
            is_active=data.get('is_active', True)
        )


class AccountManager:
    """账户管理器"""
    
    def __init__(self, accounts_file: str = "data/accounts.json"):
        self.accounts_file = Path(accounts_file)
        self.accounts: Dict[str, UserAccount] = {}
        self.current_user: Optional[UserAccount] = None
        self.load_accounts()
    
    def load_accounts(self):
        """从文件加载账户"""
        if self.accounts_file.exists():
            try:
                with open(self.accounts_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_data in data.get('accounts', []):
                        user = UserAccount.from_dict(user_data)
                        self.accounts[user.username] = user
            except Exception as e:
                print(f"加载账户失败: {e}")
    
    def save_accounts(self):
        """保存账户到文件"""
        self.accounts_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                'accounts': [user.to_dict(exclude_password=False) 
                           for user in self.accounts.values()]
            }
            with open(self.accounts_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存账户失败: {e}")
    
    @staticmethod
    def hash_password(password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def create_account(self, username: str, password: str, display_name: str,
                      account_type: str = 'user',
                      created_by: Optional[UserAccount] = None) -> bool:
        """
        创建新账户
        
        Args:
            username: 用户名
            password: 密码
            display_name: 显示名称
            account_type: 账户类型 ('admin' / 'seller' / 'user')
            created_by: 创建者（检查权限）
        """
        # 权限检查
        if created_by and not (created_by.permissions.is_admin or 
                              created_by.permissions.is_system_owner):
            print("权限不足，只有admin可以创建账户")
            return False
        
        if username in self.accounts:
            print(f"用户名 {username} 已存在")
            return False
        
        # 确定权限
        if account_type == 'admin':
            perms = AccountPermissions.default_admin()
        elif account_type == 'seller':
            perms = AccountPermissions.seller_user()
        else:
            perms = AccountPermissions.default_user()
        
        # 创建账户
        import uuid
        user = UserAccount(
            username=username,
            user_id=str(uuid.uuid4()),
            password_hash=self.hash_password(password),
            display_name=display_name,
            account_type=account_type,
            permissions=perms,
            ink_inventory_count={}
        )
        
        self.accounts[username] = user
        self.save_accounts()
        return True
    
    def delete_account(self, username: str, deleted_by: Optional[UserAccount] = None) -> bool:
        """删除账户"""
        if deleted_by and not deleted_by.permissions.is_system_owner:
            print("权限不足")
            return False
        
        if username == 'admin':
            print("不能删除admin账户")
            return False
        
        if username in self.accounts:
            del self.accounts[username]
            self.save_accounts()
            return True
        
        return False
    
    def login(self, username: str, password: str) -> Optional[UserAccount]:
        """登录"""
        if username not in self.accounts:
            print(f"用户 {username} 不存在")
            return None
        
        user = self.accounts[username]
        if not user.is_active:
            print("账户已被禁用")
            return None
        
        if user.password_hash != self.hash_password(password):
            print("密码错误")
            return None
        
        self.current_user = user
        user.last_login = datetime.now().isoformat()
        self.save_accounts()
        return user
    
    def logout(self):
        """登出"""
        self.current_user = None
    
    def update_ink_inventory(self, username: str, ink_code: str, quantity: float,
                           modified_by: Optional[UserAccount] = None) -> bool:
        """
        更新该账户的油墨库存
        
        关键改进：每个账户有自己的油墨库存，互不影响
        """
        if modified_by:
            # 只有admin或系统所有者可以修改他人的库存
            if modified_by.username != username and not modified_by.permissions.is_admin:
                print("权限不足")
                return False
        
        if username not in self.accounts:
            print(f"用户 {username} 不存在")
            return False
        
        user = self.accounts[username]
        user.ink_inventory_count[ink_code] = quantity
        self.save_accounts()
        return True
    
    def get_user_ink_inventory(self, username: str) -> Dict[str, float]:
        """获取用户的油墨库存"""
        if username not in self.accounts:
            return {}
        return self.accounts[username].ink_inventory_count.copy()
    
    def check_permission(self, user: Optional[UserAccount], permission: str) -> bool:
        """
        检查用户是否有某个权限
        
        permission: 权限名称（如 'can_edit_ink_library'）
        """
        if not user:
            return False
        
        if user.permissions.is_system_owner:
            return True  # 系统所有者拥有所有权限
        
        return getattr(user.permissions, permission, False)
    
    def list_accounts(self, list_by: Optional[UserAccount] = None) -> List[Dict]:
        """
        列出所有账户
        
        权限：只有admin可以查看所有账户
        """
        if list_by and not list_by.permissions.is_admin:
            # 普通用户只能看到自己
            return [self.accounts[list_by.username].to_dict()]
        
        return [user.to_dict() for user in self.accounts.values()]
    
    def update_password(self, username: str, old_password: str, new_password: str) -> bool:
        """用户修改自己的密码"""
        if username not in self.accounts:
            return False
        
        user = self.accounts[username]
        if user.password_hash != self.hash_password(old_password):
            print("旧密码错误")
            return False
        
        user.password_hash = self.hash_password(new_password)
        self.save_accounts()
        return True


class PermissionAwareSQLFilter:
    """权限感知的数据过滤器 - 根据用户权限过滤可见的油墨库"""
    
    @staticmethod
    def filter_inks(user: Optional[UserAccount], all_inks: List[Dict]) -> List[Dict]:
        """
        根据用户权限过滤油墨列表
        
        规则：
        - admin/系统所有者：看所有油墨
        - 卖家：看自己上传的油墨 + 系统标准油墨
        - 普通用户：只看已发布的油墨
        """
        if not user:
            return []
        
        if user.permissions.is_admin or user.permissions.is_system_owner:
            return all_inks
        
        # 卖家可以看标准油墨和自己上传的
        if user.permissions.can_edit_ink_library:
            return [ink for ink in all_inks 
                   if ink.get('is_standard', False) or ink.get('uploaded_by') == user.username]
        
        # 普通用户只看已发布的公开油墨
        return [ink for ink in all_inks if ink.get('is_public', False)]
