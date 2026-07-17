# -*- coding: utf-8 -*-
"""
design_system.py - 改进的UI设计系统
====================================
解决问题3：进销存管理界面太难操作，设计不美观

设计原则：
1. 高对比度 - 选中状态要清晰可见（不是灰色）
2. 充分的视觉反馈 - 用户操作要有明确的视觉响应
3. 合理的空间和排版 - 不拥挤
4. 一致的交互模式 - 减少学习成本
5. 性能优先 - 快速响应
"""

from enum import Enum
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass


class ColorScheme(Enum):
    """颜色方案"""
    # 主要颜色
    PRIMARY = "#2563EB"         # 主蓝色
    PRIMARY_HOVER = "#1D4ED8"   # 深蓝
    PRIMARY_ACTIVE = "#1E40AF"  # 更深蓝
    
    # 成功状态
    SUCCESS = "#10B981"         # 绿色
    SUCCESS_LIGHT = "#D1FAE5"   # 浅绿
    
    # 错误状态
    ERROR = "#EF4444"           # 红色
    ERROR_LIGHT = "#FEE2E2"     # 浅红
    
    # 警告状态
    WARNING = "#F59E0B"         # 橙色
    WARNING_LIGHT = "#FEF3C7"   # 浅橙
    
    # 选中状态（改进：不是灰色，而是鲜艳的蓝色）
    SELECTION = "#3B82F6"       # 明亮蓝色
    SELECTION_LIGHT = "#EFF6FF" # 超浅蓝背景
    
    # 背景和边框
    BACKGROUND = "#FFFFFF"
    BACKGROUND_SECONDARY = "#F9FAFB"  # 略深的背景
    BORDER = "#E5E7EB"          # 边框灰色
    
    # 文本颜色
    TEXT_PRIMARY = "#111827"    # 深黑
    TEXT_SECONDARY = "#6B7280"  # 灰色
    TEXT_DISABLED = "#9CA3AF"   # 淡灰
    
    # 阴影（用于层次感）
    SHADOW_SM = "0 1px 2px rgba(0,0,0,0.05)"
    SHADOW_MD = "0 4px 6px rgba(0,0,0,0.1)"
    SHADOW_LG = "0 10px 15px rgba(0,0,0,0.1)"


class Typography(Enum):
    """排版规范"""
    # 标题
    H1 = ("32px", "bold", "1.2")   # (size, weight, line_height)
    H2 = ("24px", "bold", "1.3")
    H3 = ("20px", "bold", "1.4")
    
    # 正文
    BODY_LARGE = ("16px", "normal", "1.6")
    BODY = ("14px", "normal", "1.6")
    BODY_SMALL = ("12px", "normal", "1.5")
    
    # 标签和链接
    LABEL = ("12px", "600", "1.4")
    CAPTION = ("11px", "normal", "1.4")


class Spacing(Enum):
    """间距规范 (px)"""
    XS = 2
    SM = 4
    MD = 8
    LG = 16
    XL = 24
    XXL = 32


@dataclass
class ComponentStyle:
    """组件样式定义"""
    name: str
    background: str
    border_color: str
    text_color: str
    padding: str
    border_radius: str
    min_height: str
    font_size: str
    font_weight: str
    cursor: str = "pointer"
    transition: str = "all 0.2s ease"


class DesignSystem:
    """统一的设计系统"""
    
    # 按钮样式
    @staticmethod
    def button_primary() -> ComponentStyle:
        """主要按钮（重要操作）"""
        return ComponentStyle(
            name="button_primary",
            background=ColorScheme.PRIMARY.value,
            border_color=ColorScheme.PRIMARY.value,
            text_color="#FFFFFF",
            padding="10px 20px",
            border_radius="6px",
            min_height="40px",
            font_size="14px",
            font_weight="600"
        )
    
    @staticmethod
    def button_secondary() -> ComponentStyle:
        """次要按钮"""
        return ComponentStyle(
            name="button_secondary",
            background=ColorScheme.BACKGROUND_SECONDARY.value,
            border_color=ColorScheme.BORDER.value,
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="10px 20px",
            border_radius="6px",
            min_height="40px",
            font_size="14px",
            font_weight="600"
        )
    
    @staticmethod
    def button_danger() -> ComponentStyle:
        """危险按钮（删除等）"""
        return ComponentStyle(
            name="button_danger",
            background=ColorScheme.ERROR.value,
            border_color=ColorScheme.ERROR.value,
            text_color="#FFFFFF",
            padding="10px 20px",
            border_radius="6px",
            min_height="40px",
            font_size="14px",
            font_weight="600"
        )
    
    # 表格行样式
    @staticmethod
    def table_row_normal() -> ComponentStyle:
        """正常行"""
        return ComponentStyle(
            name="table_row_normal",
            background=ColorScheme.BACKGROUND.value,
            border_color=ColorScheme.BORDER.value,
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="12px 16px",
            border_radius="0px",
            min_height="44px",
            font_size="14px",
            font_weight="normal"
        )
    
    @staticmethod
    def table_row_selected() -> ComponentStyle:
        """
        选中行（改进：不是灰色，而是鲜艳的蓝色）
        这解决了问题3："点击选择的时候是灰色，这样根本看不清楚我选择了这个"
        """
        return ComponentStyle(
            name="table_row_selected",
            background=ColorScheme.SELECTION_LIGHT.value,  # 超浅蓝背景
            border_color=ColorScheme.SELECTION.value,  # 蓝色边框
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="12px 16px",
            border_radius="0px",
            min_height="44px",
            font_size="14px",
            font_weight="600",  # 加粗显示
            cursor="pointer"
        )
    
    @staticmethod
    def table_row_hover() -> ComponentStyle:
        """鼠标悬停行"""
        return ComponentStyle(
            name="table_row_hover",
            background=ColorScheme.SELECTION_LIGHT.value,
            border_color=ColorScheme.SELECTION.value,
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="12px 16px",
            border_radius="0px",
            min_height="44px",
            font_size="14px",
            font_weight="normal"
        )
    
    # 输入框样式
    @staticmethod
    def input_field() -> ComponentStyle:
        """输入框"""
        return ComponentStyle(
            name="input_field",
            background=ColorScheme.BACKGROUND.value,
            border_color=ColorScheme.BORDER.value,
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="10px 12px",
            border_radius="6px",
            min_height="36px",
            font_size="14px",
            font_weight="normal"
        )
    
    @staticmethod
    def input_field_focused() -> ComponentStyle:
        """获焦输入框"""
        return ComponentStyle(
            name="input_field_focused",
            background=ColorScheme.BACKGROUND.value,
            border_color=ColorScheme.PRIMARY.value,  # 蓝色边框表示获焦
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="10px 12px",
            border_radius="6px",
            min_height="36px",
            font_size="14px",
            font_weight="normal"
        )
    
    # 卡片样式
    @staticmethod
    def card() -> ComponentStyle:
        """卡片容器"""
        return ComponentStyle(
            name="card",
            background=ColorScheme.BACKGROUND.value,
            border_color=ColorScheme.BORDER.value,
            text_color=ColorScheme.TEXT_PRIMARY.value,
            padding="16px",
            border_radius="8px",
            min_height="auto",
            font_size="14px",
            font_weight="normal"
        )
    
    # 警告和提示样式
    @staticmethod
    def alert_success() -> ComponentStyle:
        """成功提示"""
        return ComponentStyle(
            name="alert_success",
            background=ColorScheme.SUCCESS_LIGHT.value,
            border_color=ColorScheme.SUCCESS.value,
            text_color=ColorScheme.SUCCESS.value,
            padding="12px 16px",
            border_radius="6px",
            min_height="44px",
            font_size="14px",
            font_weight="normal"
        )
    
    @staticmethod
    def alert_error() -> ComponentStyle:
        """错误提示"""
        return ComponentStyle(
            name="alert_error",
            background=ColorScheme.ERROR_LIGHT.value,
            border_color=ColorScheme.ERROR.value,
            text_color=ColorScheme.ERROR.value,
            padding="12px 16px",
            border_radius="6px",
            min_height="44px",
            font_size="14px",
            font_weight="normal"
        )
    
    @staticmethod
    def alert_warning() -> ComponentStyle:
        """警告提示"""
        return ComponentStyle(
            name="alert_warning",
            background=ColorScheme.WARNING_LIGHT.value,
            border_color=ColorScheme.WARNING.value,
            text_color=ColorScheme.WARNING.value,
            padding="12px 16px",
            border_radius="6px",
            min_height="44px",
            font_size="14px",
            font_weight="normal"
        )


class InventoryUIGuidelines:
    """进销存界面设计指南"""
    
    @staticmethod
    def get_layout_guidelines() -> Dict[str, str]:
        """
        布局指南 - 解决"界面太难操作，一点都不美观"的问题
        """
        return {
            "page_max_width": "1400px",  # 最大宽度，防止过宽
            "content_padding": "24px",
            "section_gap": "24px",
            "column_gap": "16px",
            "row_gap": "8px",
            
            # 工具栏
            "toolbar_height": "52px",
            "toolbar_padding": "12px 16px",
            
            # 搜索和过滤
            "filter_height": "44px",
            "filter_gap": "12px",
            
            # 表格
            "table_header_height": "44px",
            "table_row_height": "44px",
            "table_column_min_width": "80px",
            "table_padding": "0px",  # 表格本身无内边距
            
            # 列表项
            "list_item_height": "56px",
            "list_item_padding": "12px 16px",
        }
    
    @staticmethod
    def get_interaction_guidelines() -> Dict[str, str]:
        """
        交互指南 - 改进用户体验
        """
        return {
            # 响应时间
            "instant_feedback_delay": "0ms",
            "hover_state_delay": "0ms",
            "click_feedback_delay": "100ms",
            
            # 动画
            "transition_duration": "200ms",
            "transition_timing": "ease-out",
            
            # 文本选择
            "selected_text_style": "bold+blue_background",
            "hover_text_style": "light_blue_background",
            
            # 指针样式
            "clickable_cursor": "pointer",
            "disabled_cursor": "not-allowed",
            "text_cursor": "text",
            
            # 反馈
            "click_feedback": "scale_down_slightly_then_up",  # 按压感
            "success_toast_duration": "3s",
            "error_toast_duration": "5s",
        }
    
    @staticmethod
    def get_inventory_table_columns() -> List[Dict]:
        """
        进销存表格列定义 - 优化显示
        """
        return [
            {
                "field": "checkbox",
                "label": "",
                "width": "44px",
                "fixed": "left",
                "align": "center",
                "selectable": True,
                "description": "多选框"
            },
            {
                "field": "product_name",
                "label": "产品名称",
                "width": "200px",
                "sortable": True,
                "searchable": True,
                "description": "支持搜索"
            },
            {
                "field": "sku",
                "label": "SKU",
                "width": "120px",
                "sortable": True,
                "searchable": True,
                "description": "产品代码"
            },
            {
                "field": "quantity_on_hand",
                "label": "库存数",
                "width": "100px",
                "align": "right",
                "sortable": True,
                "formatter": "number",
                "description": "当前库存"
            },
            {
                "field": "reorder_level",
                "label": "预警值",
                "width": "100px",
                "align": "right",
                "editable": True,
                "description": "库存低于此值时预警"
            },
            {
                "field": "unit_price",
                "label": "单价",
                "width": "100px",
                "align": "right",
                "formatter": "currency",
                "description": "成本或售价"
            },
            {
                "field": "total_value",
                "label": "总值",
                "width": "100px",
                "align": "right",
                "formatter": "currency",
                "computed": "quantity_on_hand * unit_price",
                "description": "库存总价值"
            },
            {
                "field": "status",
                "label": "状态",
                "width": "100px",
                "align": "center",
                "formatter": "status_badge",
                "description": "库存充足/预警/缺货"
            },
            {
                "field": "last_updated",
                "label": "最后更新",
                "width": "140px",
                "sortable": True,
                "formatter": "date_time",
                "description": "上次更新时间"
            },
            {
                "field": "actions",
                "label": "操作",
                "width": "120px",
                "fixed": "right",
                "align": "center",
                "description": "编辑、删除等操作"
            }
        ]
    
    @staticmethod
    def get_action_buttons() -> List[Dict]:
        """
        标准操作按钮配置
        """
        return [
            {
                "id": "add_item",
                "label": "+ 新增",
                "icon": "plus",
                "style": "primary",
                "shortcut": "Ctrl+N",
                "tooltip": "添加新的库存项目"
            },
            {
                "id": "edit_selected",
                "label": "编辑",
                "icon": "edit",
                "style": "secondary",
                "disabled_if": "no_selection",
                "tooltip": "编辑选中的项目"
            },
            {
                "id": "delete_selected",
                "label": "删除",
                "icon": "trash",
                "style": "danger",
                "disabled_if": "no_selection",
                "confirm": "确认删除选中的 {count} 个项目吗？",
                "tooltip": "删除选中的项目"
            },
            {
                "id": "import",
                "label": "导入",
                "icon": "download",
                "style": "secondary",
                "tooltip": "从CSV或Excel导入库存数据"
            },
            {
                "id": "export",
                "label": "导出",
                "icon": "upload",
                "style": "secondary",
                "disabled_if": "empty_list",
                "tooltip": "导出为CSV或Excel"
            },
            {
                "id": "refresh",
                "label": "刷新",
                "icon": "refresh",
                "style": "secondary",
                "shortcut": "F5",
                "tooltip": "刷新数据"
            }
        ]
    
    @staticmethod
    def get_status_indicators() -> Dict[str, Dict]:
        """
        状态指示器定义
        """
        return {
            "in_stock": {
                "color": ColorScheme.SUCCESS.value,
                "icon": "check-circle",
                "label": "库存充足"
            },
            "low_stock": {
                "color": ColorScheme.WARNING.value,
                "icon": "alert-circle",
                "label": "库存预警"
            },
            "out_of_stock": {
                "color": ColorScheme.ERROR.value,
                "icon": "x-circle",
                "label": "缺货"
            },
            "discontinued": {
                "color": ColorScheme.TEXT_DISABLED.value,
                "icon": "archive",
                "label": "已停产"
            }
        }
