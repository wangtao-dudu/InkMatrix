# -*- coding: utf-8 -*-
"""
main_window.py  (UI层 - 主窗口，重构版)
==========================================
墨算 (InkMatrix) 智能调色系统 —— 主窗口。

视觉与交互重新设计（对标同行业色彩管理/工业调色软件）：
    左侧：深色侧边导航栏 —— 配色工作台 / 油墨库管理 / 瓶身识别
    中间：QStackedWidget 承载三大业务页面（各自独立文件，高内聚低耦合）
    底部：全局常驻状态徽标 + 大红色急停按钮（任何页面下都可见、可用）

硬件与算法实例（engine / scale / dispenser）由本窗口统一持有并注入各页面，
各页面完全不关心当前是仿真硬件还是未来接入的真实硬件。
"""

import sys
import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QStackedWidget, QButtonGroup, QMessageBox
)

from dal_layer.data_manager import (
    FinanceRepository,
    InkRepository, BottleRepository, CompanyInfoRepository, ProductRepository,
    ProductionRepository, MachineRepository, InventoryRepository, InkStockRepository,
    UserRepository, ROLE_PERMISSIONS,
)
from core_layer.color_engine import KubelkaMunkEngine, InkSpectralData
from hal_layer.interfaces import SimulatedScale, SimulatedDispenser
from ui_layer.worker import ScaleTickWorker
from ui_layer.theme import apply_theme
from ui_layer.widgets import SidebarButton, DangerButton, StatusBadge, GhostButton
from ui_layer.login_dialog import LoginDialog
from ui_layer.pages.workbench_page import WorkbenchPage
from ui_layer.pages.ink_library_page import InkLibraryPage
from ui_layer.pages.bottle_recognition_page import BottleRecognitionPage
from ui_layer.pages.print_job_page import PrintJobPage
from ui_layer.pages.product_page import ProductPage
from ui_layer.pages.company_info_page import CompanyInfoPage
from ui_layer.pages.production_page import ProductionPage
from ui_layer.pages.inventory_page import InventoryPage
from ui_layer.pages.finance_page import FinancePage
from ui_layer.pages.user_management_page import UserManagementPage
from ui_layer.pages.ink_stock_page import InkStockPage


class MainWindow(QMainWindow):

    logout_requested = pyqtSignal()

    def __init__(self, current_user: dict):
        super().__init__()
        self.current_user = current_user
        self.current_role = current_user.get("role", "管理员")
        self.setWindowTitle(f"墨算 InkMatrix 智能调色系统 v2.0 —— 当前登录：{current_user.get('display_name','')}（{self.current_role}）")
        self._apply_adaptive_default_size()

        # ---- DAL 数据仓储 ----
        self.ink_repo = InkRepository()
        self.bottle_repo = BottleRepository()
        self.company_repo = CompanyInfoRepository()
        self.product_repo = ProductRepository()
        self.production_repo = ProductionRepository()
        self.machine_repo = MachineRepository()
        self.inventory_repo = InventoryRepository()
        self.ink_stock_repo = InkStockRepository()
        self.finance_repo = FinanceRepository()
        self.user_repo = UserRepository()

        # ---- HAL 硬件实例（当前为仿真实现，未来替换为真实驱动即可无缝升级） ----
        self.scale = SimulatedScale()
        self.scale.connect_scale({"port": "SIMULATED"})
        self.dispenser = SimulatedDispenser(self.scale)
        self._scale_tick_worker = ScaleTickWorker(self.scale)
        self._scale_tick_worker.start()

        # ---- CORE 算法引擎 ----
        self._engine = None
        self._rebuild_engine()

        self._build_ui()
        self._apply_anti_screenshot_best_effort()

    # ------------------------------------------------------------------
    # 引擎构建
    # ------------------------------------------------------------------

    def _rebuild_engine(self):
        raw_inks = self.ink_repo.load_all()
        lib = [
            InkSpectralData(
                code=r["code"], name=r["name"],
                K=np.array(r["K"], dtype=float), S=np.array(r["S"], dtype=float),
                category=r.get("category", "color"),
                dry_back_factor=r.get("dry_back_factor", 0.0),
                density=r.get("density", 1.0),
            )
            for r in raw_inks
        ]
        self._engine = KubelkaMunkEngine(lib)

    def get_engine(self):
        return self._engine

    def _get_allowed_ink_codes(self):
        """当前登录账户能用哪些油墨：管理员不受限(返回None)，子账户只能用被分配到的那些。"""
        allocations = self.user_repo.get_ink_allocations(self.current_user.get("username", ""))
        if allocations is None:
            return None
        return set(allocations.keys())

    def _is_main_account(self) -> bool:
        """
        是否主账户 —— 判断依据是【有没有"账户管理"这项权限】，不是看角色标签叫什么。

        为什么不看角色名：角色（"管理员"/"文员"/"仓管"）只是新建用户时用来
        快速勾选权限的模板，存下来的是勾选结果，不是角色本身。有人可能把
        角色改叫别的名字，或者给一个"文员"手动补上账户管理权限——所以任何
        安全判断都必须回到 effective_permissions 这个真值上去，绝不能拿角色
        的中文名当条件。（这一条之前踩过坑，油墨分配的过滤就是因为拿
        role == "管理员" 当判断，导致改了角色名之后整个分配机制失效。）
        """
        return "users" in UserRepository.effective_permissions(self.current_user)

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("RootBackground")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_pages(), 1)
        root.addLayout(body, 1)

        root.addWidget(self._build_bottom_bar())

    # ---- 侧边栏 ----

    # 页面key -> (图标+标题, 构造该页面widget的属性名)，顺序即侧边栏显示顺序
    _PAGE_ORDER = [
        ("workbench", "🎯  配色工作台"),
        ("print_job", "🖨️  多色印刷工单"),
        ("ink_library", "🧪  油墨库管理"),
        ("bottle", "📷  瓶身识别"),
        ("product", "📦  产品管理"),
        ("production", "🏭  生产追踪"),
        ("inventory", "🚚  进销存管理"),
        ("finance", "💰  财务管理"),
        ("ink_stock", "🛢️  油墨库存管理"),
        ("company", "🏢  公司信息"),
        ("users", "👤  账户管理"),
    ]

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        logo = QLabel("墨算 InkMatrix")
        logo.setObjectName("SidebarLogo")
        subtitle = QLabel("智能调色系统 v2.0")
        subtitle.setObjectName("SidebarSubtitle")
        lay.addWidget(logo)
        lay.addWidget(subtitle)

        user_label = QLabel(f"👤 {self.current_user.get('display_name','')}\n角色：{self.current_role}")
        user_label.setObjectName("SidebarSubtitle")
        user_label.setWordWrap(True)
        lay.addWidget(user_label)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_buttons = {}  # page_key -> SidebarButton

        allowed_keys = UserRepository.effective_permissions(self.current_user)
        visible_index = 0
        for key, label in self._PAGE_ORDER:
            if key not in allowed_keys:
                continue
            btn = SidebarButton(label)
            self.nav_group.addButton(btn, visible_index)
            self._nav_buttons[key] = btn
            lay.addWidget(btn)
            visible_index += 1

        if self._nav_buttons:
            first_btn = next(iter(self._nav_buttons.values()))
            first_btn.setChecked(True)
        self.nav_group.idClicked.connect(self._on_nav_clicked)

        lay.addStretch(1)
        version_label = QLabel("硬件模式：仿真 (SIMULATED)\n接入真实硬件请见 hal_layer")
        version_label.setObjectName("SidebarVersion")
        version_label.setWordWrap(True)
        lay.addWidget(version_label)

        logout_btn = GhostButton("🚪 退出登录")
        logout_btn.clicked.connect(self._on_logout)
        lay.addWidget(logout_btn)

        return sidebar

    def _apply_adaptive_default_size(self):
        """
        默认窗口大小改成"按屏幕实际可用空间的比例"来定，而不是写死1440x860——
        很多笔记本屏幕分辨率（比如常见的1366x768）比1440还窄，写死尺寸会导致
        软件一打开就已经比屏幕还大，被迫挤压出滚动条。取屏幕可用区域的90%，
        且设一个较小的下限，取不到屏幕信息时（极少见）才退回旧的固定值兜底。
        """
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(1000, int(available.width() * 0.9))
            height = max(650, int(available.height() * 0.9))
            self.resize(width, height)
            # 屏幕本来就比较宽裕时，居中显示，不要贴在角落
            self.move(
                available.x() + (available.width() - width) // 2,
                available.y() + (available.height() - height) // 2,
            )
        else:
            self.resize(1280, 800)

    def _apply_anti_screenshot_best_effort(self):
        """
        "禁止截图" —— 这里必须先说清楚现实：任何软件都没办法100%阻止截图，
        只要画面能显示在屏幕上，用手机对着屏幕拍一张，或者用某些专门绕过
        保护的第三方录屏工具，都还是能拍下来。这是所有软件（包括视频网站
        的会员内容、聊天软件的"防截图"）都躲不开的物理限制，不是我们技术
        不到位。

        能做到的是"尽力而为、抬高门槛"：在Windows 10(2004版本)及以上系统，
        调用系统API `SetWindowDisplayAffinity` 把本窗口标记为"排除在屏幕
        捕获之外"——效果是：Windows自带的截图工具（PrintScreen键、截图
        工具、大部分录屏软件）截出来的画面里，这个窗口会变成黑屏或者
        直接截不到，但依然挡不住手机拍屏幕、或者某些底层截屏工具。
        在非Windows系统（Linux/Mac）、或者较老版本Windows上，这段代码
        会自动跳过，不影响软件正常使用。
        """
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass  # 老版本Windows没有这个API或调用失败时，静默跳过，不影响正常使用

    def _on_logout(self):
        self.logout_requested.emit()
        self.close()

    def _on_nav_clicked(self, index: int):
        self.pages.setCurrentIndex(index)

    # ---- 页面容器 ----

    def _build_pages(self) -> QWidget:
        self.pages = QStackedWidget()

        self.workbench_page = WorkbenchPage(
            ink_repo=self.ink_repo,
            bottle_repo=self.bottle_repo,
            get_engine=self.get_engine,
            scale=self.scale,
            dispenser=self.dispenser,
            get_allowed_ink_codes=self._get_allowed_ink_codes,
            user_repo=self.user_repo,
            current_username=self.current_user.get("username", ""),
        )
        self.print_job_page = PrintJobPage(
            ink_repo=self.ink_repo,
            bottle_repo=self.bottle_repo,
            get_engine=self.get_engine,
            scale=self.scale,
            dispenser=self.dispenser,
            product_repo=self.product_repo,
            company_repo=self.company_repo,
            get_allowed_ink_codes=self._get_allowed_ink_codes,
            user_repo=self.user_repo,
            current_username=self.current_user.get("username", ""),
        )
        self.ink_library_page = InkLibraryPage(
            ink_repo=self.ink_repo,
            get_engine=self.get_engine,
            # ★【问题1修复】把权限回调传进去。以前漏了这两个参数，导致
            # 【油墨库管理】页不管谁登录都把整个油墨库倒出来，跟已经做了
            # 过滤的【多色印刷工单】行为不一致——分配油墨的设置在那一页
            # 形同虚设。现在两个页面用的是同一个回调、同一套判断。
            get_allowed_ink_codes=self._get_allowed_ink_codes,
            is_main_account=self._is_main_account,
            # 删除油墨要连带清理子账户分配、并提示库存/流水风险
            user_repo=self.user_repo,
            ink_stock_repo=self.ink_stock_repo,
        )
        self.bottle_page = BottleRecognitionPage(bottle_repo=self.bottle_repo)
        self.product_page = ProductPage(product_repo=self.product_repo, bottle_repo=self.bottle_repo)
        self.company_page = CompanyInfoPage(company_repo=self.company_repo)
        self.production_page = ProductionPage(production_repo=self.production_repo, machine_repo=self.machine_repo)
        self.inventory_page = InventoryPage(
            inventory_repo=self.inventory_repo,
            company_repo=self.company_repo,
            finance_repo=self.finance_repo,   # 删记录前要检查财务那边有没有挂着收款
        )
        self.finance_page = FinancePage(
            inventory_repo=self.inventory_repo,
            finance_repo=self.finance_repo,
            company_repo=self.company_repo,
        )
        self.user_management_page = UserManagementPage(
            user_repo=self.user_repo, current_username=self.current_user.get("username", ""),
            ink_repo=self.ink_repo, current_user=self.current_user,
        )
        self.ink_stock_page = InkStockPage(ink_repo=self.ink_repo, ink_stock_repo=self.ink_stock_repo)

        page_widgets = {
            "workbench": self.workbench_page,
            "print_job": self.print_job_page,
            "ink_library": self.ink_library_page,
            "bottle": self.bottle_page,
            "product": self.product_page,
            "production": self.production_page,
            "inventory": self.inventory_page,
            "finance": self.finance_page,
            "ink_stock": self.ink_stock_page,
            "company": self.company_page,
            "users": self.user_management_page,
        }

        # 只把当前角色有权限的页面加进堆栈，顺序要跟侧边栏按钮的顺序完全一致
        allowed_keys = UserRepository.effective_permissions(self.current_user)
        self._page_key_to_index = {}
        for key, _label in self._PAGE_ORDER:
            if key not in allowed_keys:
                continue
            self._page_key_to_index[key] = self.pages.count()
            self.pages.addWidget(page_widgets[key])

        # ---- 跨页面数据联动（信号连接不受权限过滤影响，即便某个页面当前
        # 用户看不到，后台联动逻辑照常挂着，无害，也避免以后切角色报错） ----
        self.workbench_page.status_normal.connect(self._on_status_normal)
        self.workbench_page.status_danger.connect(self._on_status_danger)
        self.print_job_page.status_normal.connect(self._on_status_normal)
        self.print_job_page.status_danger.connect(self._on_status_danger)

        self.ink_library_page.ink_db_changed.connect(self._on_ink_db_changed)
        self.ink_library_page.status_message.connect(self._on_status_normal)
        self.ink_stock_page.ink_db_changed.connect(self._on_ink_db_changed)
        # ★ 新增：配墨执行会扣库存，这两个页面扣完也要广播（之前漏了，导致
        # 在工作台/工单页配完墨，油墨库管理和库存总览显示的还是旧数字）
        self.workbench_page.ink_db_changed.connect(self._on_ink_db_changed)
        self.print_job_page.ink_db_changed.connect(self._on_ink_db_changed)
        self.bottle_page.bottle_db_changed.connect(self.workbench_page.refresh_bottle_combo)
        self.bottle_page.bottle_db_changed.connect(self.print_job_page.refresh_bottle_combo)
        self.product_page.load_requested.connect(self._on_product_load_requested)
        self.product_page.status_message.connect(self._on_status_normal)
        # 进销存改了数量/单价/或删了记录 → 财务的应收账款要跟着重算
        self.inventory_page.inventory_changed.connect(self.finance_page.refresh_all)
        self.inventory_page.status_message.connect(self._on_status_normal)
        self.finance_page.status_message.connect(self._on_status_normal)
        self.print_job_page.product_saved.connect(self.product_page.refresh_table)

        return self.pages

    def _on_product_load_requested(self, record: dict):
        self.print_job_page.load_product_template(record)
        target_index = self._page_key_to_index.get("print_job")
        if target_index is None:
            QMessageBox.information(
                self, "提示",
                "已保存产品数据，但当前账户没有【多色印刷工单】页面的权限，无法自动跳转查看。"
            )
            return
        self._nav_buttons["print_job"].setChecked(True)
        self.pages.setCurrentIndex(target_index)

    def _on_ink_db_changed(self):
        """
        油墨库或库存发生任何变动后的全系统同步刷新。

        防重入（_syncing 标志）：现在有四个页面会发这个信号（油墨库管理、
        油墨库存管理、工作台配墨扣库存、工单页配墨扣库存），而本方法内部
        又会去刷新这些页面。万一将来某个页面的 refresh 里不小心又碰了一下
        库存并再发信号，就会无限递归、界面直接卡死。加一道闸，正在同步的
        时候忽略新进来的同类信号——同步结束时数据本来就已经是最新的了，
        不会漏更新。
        """
        if getattr(self, "_syncing_ink_db", False):
            return
        self._syncing_ink_db = True
        try:
            self._rebuild_engine()
            self.workbench_page.refresh_ink_checklist()
            self.print_job_page.refresh_ink_checklist()
            self.print_job_page._refresh_station_table()  # 让"配方已过期"提示立刻生效，不用等用户手动切页
            self.ink_stock_page.refresh_all()
            self.ink_library_page.refresh_table()
            self.user_management_page._build_ink_allocations()
        finally:
            self._syncing_ink_db = False

    # ---- 底部：全局状态与急停区 ----

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("BottomBar")
        bar.setStyleSheet("#BottomBar { background-color: white; border-top: 1px solid #e2e8f0; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 10, 20, 10)
        lay.setSpacing(14)

        self.status_badge = StatusBadge()
        self.status_badge.set_normal("系统就绪。请设置目标色并点击【智能寻优配方】。")
        lay.addWidget(self.status_badge, 1)

        reset_btn = GhostButton("急停复位")
        reset_btn.clicked.connect(self._on_reset_safety)
        lay.addWidget(reset_btn)

        self.estop_btn = DangerButton("🛑  EMERGENCY STOP / 紧急停止")
        self.estop_btn.setMinimumWidth(280)
        self.estop_btn.clicked.connect(self._on_emergency_stop)
        lay.addWidget(self.estop_btn)

        return bar

    # ------------------------------------------------------------------
    # 状态徽标 / 急停
    # ------------------------------------------------------------------

    def _on_status_normal(self, text: str):
        self.status_badge.set_normal(text)

    def _on_status_danger(self, text: str):
        self.status_badge.set_danger(text)

    def _on_emergency_stop(self):
        self.workbench_page.trigger_emergency_stop()
        self.print_job_page.trigger_emergency_stop()
        self.status_badge.set_danger("已触发紧急停止！所有硬件寄存器已强制切断，请检查现场后点击【急停复位】。")

    def _on_reset_safety(self):
        self.workbench_page.reset_safety()
        self.print_job_page.reset_safety()
        self.status_badge.set_normal("安全联锁已复位，系统恢复就绪。")

    # ------------------------------------------------------------------
    # 窗口关闭清理
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._scale_tick_worker.stop()
        self._scale_tick_worker.wait(500)
        self.workbench_page.shutdown()
        self.print_job_page.shutdown()
        super().closeEvent(event)


def run_app():
    app = QApplication(sys.argv)
    apply_theme(app)

    # ── 启动即自动升级数据格式 ──────────────────────────────────────
    # 客户机器上存的可能是几个版本前格式的老数据。升级软件后第一次启动，
    # 把数据从它当前的版本一路迁移到最新格式。迁移前会自动整体备份，出任何
    # 岔子都能回滚，不会把客户几年的账搞坏。
    try:
        from dal_layer.migrations import run_migrations
        report = run_migrations()
        if report.get("migrated"):
            QMessageBox.information(
                None, "数据已升级",
                f"检测到旧版本数据，已自动升级到最新格式"
                f"（v{report['from']} → v{report['to']}）。\n\n"
                f"升级前的数据已备份到：\n{report.get('backup', '')}"
            )
    except Exception as e:
        # 迁移失败不能挡着用户登录——记下来，让用户知道，但程序继续走。
        # 数据没被推进版本号，下次启动会重试。
        QMessageBox.warning(
            None, "数据升级提示",
            f"数据格式自动升级时遇到问题：{e}\n\n"
            f"程序仍可正常使用。如果发现数据异常，请联系技术支持。"
        )

    user_repo = UserRepository()

    while True:
        login_dlg = LoginDialog(user_repo)
        if login_dlg.exec() != login_dlg.DialogCode.Accepted:
            sys.exit(0)

        window = MainWindow(current_user=login_dlg.authenticated_user)
        logout_flag = {"value": False}

        def _mark_logout():
            logout_flag["value"] = True
        window.logout_requested.connect(_mark_logout)

        window.show()
        app.exec()

        if not logout_flag["value"]:
            # 不是点"退出登录"关的窗口（比如直接点了右上角关闭按钮），
            # 就当作正常退出程序，不再弹回登录界面。
            sys.exit(0)
        # 否则循环回去重新显示登录框，让下一个人登录
