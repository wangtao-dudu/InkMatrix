# -*- coding: utf-8 -*-
"""
theme.py  (UI层 - 视觉设计系统)
=================================
统一管理整套软件的配色 Token 与 QSS 样式表，参考同行业（工业调色/
色彩管理软件如 X-Rite Color iMatch、GMG ColorServer）常见的
"深色侧边导航 + 浅灰内容区 + 白色卡片 + 强调色按钮" 视觉语言，
替代 PyQt 默认控件的简陋外观。

调用方式：
    from ui_layer.theme import apply_theme
    apply_theme(app)   # 在 QApplication 创建后调用一次
"""

# ------------------------- 设计 Token（颜色/字号） -------------------------

COLOR_SIDEBAR_BG = "#1e2530"
COLOR_SIDEBAR_BG_HOVER = "#2a3341"
COLOR_SIDEBAR_ACCENT = "#14b8a6"
COLOR_SIDEBAR_TEXT = "#cbd5e1"
COLOR_SIDEBAR_TEXT_ACTIVE = "#ffffff"

COLOR_APP_BG = "#eef1f6"
COLOR_CARD_BG = "#ffffff"
COLOR_CARD_BORDER = "#e2e8f0"
COLOR_TEXT_PRIMARY = "#1e293b"
COLOR_TEXT_SECONDARY = "#64748b"

COLOR_PRIMARY = "#0d9488"
COLOR_PRIMARY_HOVER = "#0f766e"
COLOR_SUCCESS = "#16a34a"
COLOR_SUCCESS_HOVER = "#15803d"
COLOR_DANGER = "#dc2626"
COLOR_DANGER_HOVER = "#b91c1c"
COLOR_WARNING_BG = "#fef2f2"
COLOR_WARNING_TEXT = "#b91c1c"
COLOR_NORMAL_BG = "#f0fdf4"
COLOR_NORMAL_TEXT = "#15803d"

FONT_FAMILY = "'Microsoft YaHei UI', 'Segoe UI', 'PingFang SC', sans-serif"

QSS_TEMPLATE = """
* {{
    font-family: {font};
    outline: none;
}}

QMainWindow, QWidget#RootBackground {{
    background-color: {app_bg};
}}

QWidget {{
    color: {text_primary};
    font-size: 13px;
}}

/* ---------------- 侧边导航 ---------------- */
QWidget#Sidebar {{
    background-color: {sidebar_bg};
}}

QLabel#SidebarLogo {{
    color: {sidebar_text_active};
    font-size: 17px;
    font-weight: 700;
    padding: 22px 16px 6px 16px;
}}

QLabel#SidebarSubtitle {{
    color: {sidebar_text};
    font-size: 11px;
    padding: 0px 16px 18px 16px;
}}

QPushButton#SidebarButton {{
    background-color: transparent;
    color: {sidebar_text};
    text-align: left;
    padding: 10px 18px;
    border: none;
    border-left: 3px solid transparent;
    font-size: 14px;
    border-radius: 0px;
}}

QPushButton#SidebarButton:hover {{
    background-color: {sidebar_bg_hover};
    color: {sidebar_text_active};
}}

QPushButton#SidebarButton:checked {{
    background-color: {sidebar_bg_hover};
    color: {sidebar_text_active};
    border-left: 3px solid {sidebar_accent};
    font-weight: 600;
}}

QLabel#SidebarVersion {{
    color: #4b5563;
    font-size: 10px;
    padding: 12px;
}}

/* ---------------- 卡片 ---------------- */
QFrame#Card {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 12px;
}}

QLabel#CardTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {text_primary};
    padding-bottom: 4px;
    border-bottom: 1px solid {card_border};
    margin-bottom: 6px;
}}

QLabel#PageTitle {{
    font-size: 20px;
    font-weight: 700;
    color: {text_primary};
}}

QLabel#PageSubtitle {{
    font-size: 12px;
    color: {text_secondary};
    padding-bottom: 4px;
}}

/* ---------------- 按钮 ---------------- */
QPushButton#PrimaryButton {{
    background-color: {primary};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton#PrimaryButton:hover {{ background-color: {primary_hover}; }}
QPushButton#PrimaryButton:disabled {{ background-color: #a9b6c4; }}

QPushButton#SuccessButton {{
    background-color: {success};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 700;
    font-size: 14px;
}}
QPushButton#SuccessButton:hover {{ background-color: {success_hover}; }}
QPushButton#SuccessButton:disabled {{ background-color: #a9b6c4; }}

QPushButton#DangerButton {{
    background-color: {danger};
    color: white;
    border: none;
    border-radius: 10px;
    font-weight: 800;
    font-size: 16px;
    letter-spacing: 1px;
}}
QPushButton#DangerButton:hover {{ background-color: {danger_hover}; }}

QPushButton#GhostButton {{
    background-color: transparent;
    color: {text_secondary};
    border: 1px solid {card_border};
    border-radius: 7px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton#GhostButton:hover {{
    background-color: #f1f5f9;
    color: {text_primary};
}}

QPushButton {{
    background-color: #f8fafc;
    border: 1px solid {card_border};
    border-radius: 7px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background-color: #eef2f6; }}

/* ---------------- 状态徽标 ---------------- */
QLabel#StatusBadgeNormal {{
    background-color: {normal_bg};
    color: {normal_text};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 700;
    font-size: 13px;
}}
QLabel#StatusBadgeDanger {{
    background-color: {warning_bg};
    color: {warning_text};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 700;
    font-size: 13px;
}}

/* ---------------- 输入控件 ---------------- */
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
    background-color: #ffffff;
    border: 1px solid {card_border};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
    selection-background-color: {primary};
}}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{
    border: 1.5px solid {primary};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {card_border};
    selection-background-color: {primary};
    selection-color: white;
    background-color: white;
}}

/* ---------------- 列表 / 表格 ---------------- */
QListWidget {{
    background-color: white;
    border: 1px solid {card_border};
    border-radius: 8px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 7px 6px;
    border-radius: 5px;
}}
QListWidget::item:hover {{ background-color: #f1f5f9; }}
QListWidget::item:selected {{ background-color: #ccfbf1; color: {text_primary}; }}

QTableWidget {{
    background-color: white;
    border: 1px solid {card_border};
    border-radius: 8px;
    gridline-color: #eef1f6;
    selection-background-color: #ccfbf1;
    selection-color: {text_primary};
}}
QHeaderView::section {{
    background-color: #f8fafc;
    color: {text_secondary};
    padding: 8px;
    border: none;
    border-bottom: 2px solid {card_border};
    font-weight: 700;
}}
QTableWidget::item {{ padding: 4px; }}

QGroupBox {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 12px;
    margin-top: 10px;
    font-weight: 700;
    padding: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}

QStatusBar {{
    background-color: {card_bg};
    border-top: 1px solid {card_border};
    color: {text_secondary};
}}
"""


def build_qss() -> str:
    return QSS_TEMPLATE.format(
        font=FONT_FAMILY,
        app_bg=COLOR_APP_BG,
        text_primary=COLOR_TEXT_PRIMARY,
        text_secondary=COLOR_TEXT_SECONDARY,
        sidebar_bg=COLOR_SIDEBAR_BG,
        sidebar_bg_hover=COLOR_SIDEBAR_BG_HOVER,
        sidebar_accent=COLOR_SIDEBAR_ACCENT,
        sidebar_text=COLOR_SIDEBAR_TEXT,
        sidebar_text_active=COLOR_SIDEBAR_TEXT_ACTIVE,
        card_bg=COLOR_CARD_BG,
        card_border=COLOR_CARD_BORDER,
        primary=COLOR_PRIMARY,
        primary_hover=COLOR_PRIMARY_HOVER,
        success=COLOR_SUCCESS,
        success_hover=COLOR_SUCCESS_HOVER,
        danger=COLOR_DANGER,
        danger_hover=COLOR_DANGER_HOVER,
        warning_bg=COLOR_WARNING_BG,
        warning_text=COLOR_WARNING_TEXT,
        normal_bg=COLOR_NORMAL_BG,
        normal_text=COLOR_NORMAL_TEXT,
    )


def apply_theme(app) -> None:
    """在 QApplication 创建后调用一次，为全局应用统一视觉主题。"""
    app.setStyleSheet(build_qss())
