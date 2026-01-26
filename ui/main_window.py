"""
音译家 Transcriptionist v3 - 主窗口 (Adobe 工作站版本)
采用三栏停靠式布局，提供专业级音频工作流体验
"""

import sys
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QStackedWidget, QTabWidget
)
from PySide6.QtGui import QFont, QColor

from qfluentwidgets import (
    setTheme, Theme, setThemeColor, isDarkTheme,
    qconfig, FluentIcon, TransparentToolButton
)
from qframelesswindow import FramelessWindow, StandardTitleBar

# 导入自定义组件
from .layouts.workstation_layout import WorkstationLayout
from .panels.resource_panel import ResourcePanel
from .panels.batch_center_panel import BatchCenterPanel
from .panels.ai_inspector_panel import AIInspectorPanel
from .panels.timeline_panel import TimelinePanel

# 导入核心页面
from .pages.library_page_qt import LibraryPage
from .pages.ai_translate_page_qt import AITranslatePage
from .pages.ai_search_page_qt import AISearchPage
from .pages.naming_rules_page_qt import NamingRulesPage
from .pages.online_resources_page_qt import OnlineResourcesPage
from .pages.ai_generation_page_qt import AIGenerationPage
from .pages.projects_page_qt import ProjectsPage
from .pages.tags_page_qt import TagsPage
from .pages.toolbox_page_qt import ToolboxPage
from .pages.settings_page_qt import SettingsPage
# from .pages.audio_editor_page_qt import AudioEditorPage  # TODO: 需要 encodec_encode 模型支持

from .components.player_bar import PlayerBar
from ..application.playback_manager.qt_player import QtAudioPlayer
from ..core.fonts import apply_app_font, get_font_family

logger = logging.getLogger(__name__)

class TranscriptionistWindow(FramelessWindow):
    """音译家主窗口 - 工作站版"""
    
    def __init__(self):
        super().__init__()
        
        # 1. 窗口基础设置
        self.setWindowTitle("音译家 AI 音效管理工具 v1.0.0")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 750)
        
        # 设置窗口图标
        from PySide6.QtGui import QIcon
        from .utils.resources import get_icon_path
        icon_path = get_icon_path("app_icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
            # 同时设置应用程序图标（用于任务栏）
            QApplication.setWindowIcon(QIcon(str(icon_path)))
        
        # 2. 主题与特效
        setThemeColor("#3399ff")
        setTheme(Theme.DARK)
        
        # 禁用 Mica 特效以保证 Win10/Win11 跨平台颜色一致性
        # Mica 特效会让 Win11 窗口背景继承系统主题色，导致深色主题显示异常
        # if sys.platform == 'win32':
        #     try:
        #         if sys.getwindowsversion().build >= 22000:
        #             self.windowEffect.setMicaEffect(self.winId(), isDarkMode=True)
        #     except Exception as e:
        #         logger.warning(f"Mica effect error: {e}")
        
        self._setup_title_bar()
        
        # 3. 核心管理对象
        self._audio_player = QtAudioPlayer(self)
        
        # 4. 初始化 UI 与页面
        self._setup_ui()
        self._init_pages()
        self._setup_player_connections()
        self._connect_player_bar()
        
        # 5. 样式应用
        self._apply_theme_style()
        self._center_window()
        
        logger.info("MainWindow Workstation implementation ready")

    def _setup_title_bar(self):
        """配置自定义标题栏"""
        self._customTitleBar = StandardTitleBar(self)
        self.setTitleBar(self._customTitleBar)
        self._customTitleBar.raise_()
        
        # 设置标题栏文本颜色和字体
        from PySide6.QtGui import QPalette
        palette = self._customTitleBar.palette()
        palette.setColor(QPalette.WindowText, QColor(200, 200, 200))
        self._customTitleBar.setPalette(palette)
        
        # 强制设置按钮颜色 (解决QSS不生效问题)
        # 灰色字体，更美观
        gray_color = QColor(160, 160, 160)
        hover_color = QColor(220, 220, 220)
        
        # Min
        self._customTitleBar.minBtn.setNormalColor(gray_color)
        self._customTitleBar.minBtn.setHoverColor(hover_color)
        self._customTitleBar.minBtn.setPressedColor(QColor(200, 200, 200))
        
        # Max
        self._customTitleBar.maxBtn.setNormalColor(gray_color)
        self._customTitleBar.maxBtn.setHoverColor(hover_color)
        self._customTitleBar.maxBtn.setPressedColor(QColor(200, 200, 200))
        
        # Close (Standard Red Hover)
        self._customTitleBar.closeBtn.setNormalColor(gray_color)
        self._customTitleBar.closeBtn.setHoverColor(Qt.GlobalColor.white)
        self._customTitleBar.closeBtn.setHoverBackgroundColor(QColor(232, 17, 35))
        
        # 添加标题文本标签
        from PySide6.QtWidgets import QLabel
        self.titleLabel = QLabel("音译家 AI 音效管理工具 v1.0.0", self)
        self.titleLabel.setStyleSheet("""
            QLabel {
                color: rgb(200, 200, 200);
                font-size: 12px;
                padding-left: 10px;
                background: transparent;
            }
        """)
        
        # Add Help Button with Dropdown Menu
        from qfluentwidgets import RoundMenu, Action
        self.helpBtn = TransparentToolButton(FluentIcon.HELP, self)
        self.helpBtn.setFixedSize(46, 32)
        self.helpBtn.clicked.connect(self._show_help_menu)
        
        # Create Help Menu (空壳，暂不实现功能)
        self.helpMenu = RoundMenu(parent=self)
        self.helpMenu.addAction(Action(FluentIcon.BOOK_SHELF, "更新建议", triggered=self._on_online_manual))
        self.helpMenu.addAction(Action(FluentIcon.UPDATE, "检查更新", triggered=self._on_check_update))
        self.helpMenu.addSeparator()
        self.helpMenu.addAction(Action(FluentIcon.CHAT, "联系我", triggered=self._on_contact))
        
        # Add Settings Button
        self.settingsBtn = TransparentToolButton(FluentIcon.SETTING, self)
        self.settingsBtn.setFixedSize(46, 32)
        self.settingsBtn.clicked.connect(self._toggle_settings)
        
        # 将控件插入到标题栏布局中
        # StandardTitleBar 的布局结构: [IconLabel][Spacer][MinBtn][MaxBtn][CloseBtn]
        # 目标布局: [IconLabel][TitleLabel][Spacer][HelpBtn][SettingsBtn][MinBtn][MaxBtn][CloseBtn]
        
        layout = self._customTitleBar.hBoxLayout
        if layout:
            # 标题栏图标通常在索引0，后面是一个弹性空间（spacer）
            # 我们在索引1插入标题标签（图标之后）
            layout.insertWidget(1, self.titleLabel)
            
            # 窗口控制按钮（min/max/close）在最后，我们要在它们之前插入帮助和设置按钮
            # 由于刚才插入了titleLabel，现在count增加了1
            # 最后3个是窗口控制按钮，所以在 count-3 位置插入
            count = layout.count()
            layout.insertWidget(count - 3, self.helpBtn)
            layout.insertWidget(count - 2, self.settingsBtn)  # 注意：插入helpBtn后count又增加了1

    def _setup_ui(self):
        """构建三栏式工作站布局"""
        self.mainWidget = QWidget(self)
        mainLayout = QVBoxLayout(self.mainWidget)
        mainLayout.setContentsMargins(0, 0, 0, 0)
        mainLayout.setSpacing(0)
        
        # 顶部标题栏
        mainLayout.addWidget(self._customTitleBar)
        
        # 中央堆叠部件 (用于切换工作台和设置页)
        self.centralStack = QStackedWidget()
        
        # 工作站核心 (Left-Center-Right)
        self.workstation = WorkstationLayout()
        self.centralStack.addWidget(self.workstation) # Index 0
        
        mainLayout.addWidget(self.centralStack, 1)
        
        # 底部全局播放器
        self.playerBar = PlayerBar(self)
        mainLayout.addWidget(self.playerBar)
        
        # 窗口根布局
        windowLayout = QVBoxLayout(self)
        windowLayout.setContentsMargins(0, 0, 0, 0)
        windowLayout.setSpacing(0)
        windowLayout.addWidget(self.mainWidget)

    def _init_pages(self):
        """实例化所有功能模块并集成到面板"""
        
        # --- A. 左侧资源栏 (Resources) ---
        self.resource_panel = ResourcePanel()
        self.workstation.add_left_widget(self.resource_panel, "RESOURCES")
        
        self.libraryInterface = LibraryPage(self)
        self.libraryInterface.setStyleSheet("#libraryPage { background-color: #1e1e1e; }")
        self.projectsInterface = ProjectsPage(self)
        self.projectsInterface.setStyleSheet("#projectsPage { background-color: #1e1e1e; }")
        self.onlineResourcesInterface = OnlineResourcesPage(self)
        self.onlineResourcesInterface.setStyleSheet("#onlineResourcesPage { background-color: #1e1e1e; }")
        
        self.tagsInterface = TagsPage(self)
        self.tagsInterface.setStyleSheet("#tagsPage { background-color: #1e1e1e; }")
        
        self.resource_panel.add_resource_tab(self.libraryInterface, "", "库")
        self.resource_panel.add_resource_tab(self.tagsInterface, "", "标签") # Added Tags tab
        self.resource_panel.add_resource_tab(self.projectsInterface, "", "项目")
        self.resource_panel.add_resource_tab(self.onlineResourcesInterface, "", "在线")
        
        # --- B. 中央展示区 (Processing Center) ---
        self.batch_center = BatchCenterPanel()
        self.workstation.add_center_tab(self.batch_center, "Main")
        
        # TODO: Audio Editor - 需要 encodec_encode 模型支持音频续写
        # self.audioEditorInterface = AudioEditorPage(self)
        # self.audioEditorInterface.setStyleSheet("#audioEditorPage { background-color: #1e1e1e; }")
        
        self.aiTranslateInterface = AITranslatePage(self)
        self.aiTranslateInterface.setStyleSheet("#aiTranslatePage { background-color: #1e1e1e; }")
        # Connect translation applied signal to library page
        self.aiTranslateInterface.translation_applied.connect(self.libraryInterface.on_translation_applied)
        # self.toolboxInterface = ToolboxPage(self) # 移除
        
        self.aiSearchInterface = AISearchPage(self)
        self.aiSearchInterface.setStyleSheet("#aiSearchPage { background-color: #1e1e1e; }")
        
        self.aiGenerationInterface = AIGenerationPage(self)
        self.aiGenerationInterface.setStyleSheet("#aiGenerationPage { background-color: #1e1e1e; }")
        
        # self.batch_center.add_batch_tab(self.audioEditorInterface, "AI 音频编辑")  # TODO: 暂时禁用
        self.batch_center.add_batch_tab(self.aiTranslateInterface, "AI 批量翻译")
        self.batch_center.add_batch_tab(self.aiSearchInterface, "AI 智能检索")
        self.batch_center.add_batch_tab(self.aiGenerationInterface, "AI 音乐工坊 实验室功能")
        
        # --- C. 其他功能整合进中央面板 (原右侧面板内容) ---
        # self.namingRulesInterface = NamingRulesPage(self) # 用户要求移除，因为已在AI翻译中集成
        self.settingsInterface = SettingsPage(self)
        self.settingsInterface.setStyleSheet("#settingsPage { background-color: #1e1e1e; }")
        self.centralStack.addWidget(self.settingsInterface) # Index 1
        
        # self.batch_center.add_batch_tab(self.namingRulesInterface, "命名规则")
        # self.batch_center.add_batch_tab(self.settingsInterface, "全局设置") # 移至独立页面
        
        # 移除右侧智控栏
        # self.ai_inspector = AIInspectorPanel()
        # self.workstation.add_right_widget(self.ai_inspector, "INSPECTOR")
        
        # 默认选中第一个
        self.resource_panel.set_active_tab(0)
        self.batch_center.tabs.setCurrentIndex(1) # 翻译是核心
        
        # --- 信号连接还原 ---
        self.libraryInterface.play_file.connect(self._on_play_file)
        self.libraryInterface.files_checked.connect(self.aiTranslateInterface.set_selected_files)
        self.libraryInterface.files_checked.connect(self.aiSearchInterface.update_selection) # Connect Library -> AI Search
        self.libraryInterface.request_ai_translate.connect(lambda: self.batch_center.tabs.setCurrentIndex(1))
        self.libraryInterface.request_ai_search.connect(lambda: self.batch_center.tabs.setCurrentIndex(2)) # Fixed navigation
        
        self.tagsInterface.play_file.connect(self._on_play_file) # Connect Tags -> Player
        
        self.aiTranslateInterface.request_play.connect(self._on_play_file)
        self.aiTranslateInterface.translation_applied.connect(self.libraryInterface.on_file_renamed)
        self.aiTranslateInterface.request_stop_player.connect(self._audio_player.unload)
        
        self.onlineResourcesInterface.play_clicked.connect(self._on_play_file)
        self.settingsInterface.theme_changed.connect(lambda _: self._apply_theme_style())
        
        
        # Freesound Send to AI
        self.onlineResourcesInterface.send_to_translate.connect(
            lambda path: [
                self.aiTranslateInterface.set_selected_files([path]),
                self.batch_center.tabs.setCurrentIndex(1)  # Jump to Translate Tab
            ]
        )
        
        # AI Generation playback
        self.aiGenerationInterface.request_play.connect(self._on_play_file)
        
        # AI 打标完成后自动刷新库和标签视图
        self.aiSearchInterface.tagging_finished.connect(self.libraryInterface.refresh)
        self.aiSearchInterface.tagging_finished.connect(self.tagsInterface.refresh)
        
        # AI 打标批量更新信号连接
        # AI 打标批量更新信号连接
        self.aiSearchInterface.tags_batch_updated.connect(self.libraryInterface._on_tags_batch_updated)
        self.aiSearchInterface.tags_batch_updated.connect(self._on_tags_updated_refresh_tags_page)

        # Library Clear Synchronization
        self.libraryInterface.library_cleared.connect(self.aiSearchInterface.on_library_cleared)
        self.libraryInterface.library_cleared.connect(self.aiTranslateInterface.on_library_cleared)

    def _on_tags_updated_refresh_tags_page(self, batch_updates: list):
        """标签更新后刷新标签页面"""
        try:
            # 刷新标签页面
            self.tagsInterface.refresh()
            logger.info(f"Tags page refreshed after batch update of {len(batch_updates)} files")
        except Exception as e:
            logger.error(f"Failed to refresh tags page: {e}")

    def _apply_theme_style(self):
        """应用专业深色主题样式"""
        # 加载 QSS 文件
        from .utils.resources import get_style_path
        qss_path = get_style_path("workstation_dark.qss")
        if qss_path.exists():
            with open(qss_path, 'r', encoding='utf-8') as f:
                self.setStyleSheet(f.read())
                logger.info("Loaded workstation_dark.qss theme")
        else:
            # Fallback 内联样式
            bg_color = "#1a1a1a"
            self.setStyleSheet(f"TranscriptionistWindow {{ background-color: {bg_color}; color: #eee; }}")
        
        # 标题栏特殊处理
        self._customTitleBar.setStyleSheet("StandardTitleBar { background-color: #1a1a1a; border: none; }")

        
    def _on_play_file(self, file_path: str):
        path = Path(file_path)
        self.playerBar.set_track_info(path.name, str(path.parent))
        if self._audio_player.load(file_path):
            self._audio_player.play()
            self.playerBar.set_playing(True)

    def _toggle_settings(self):
        """切换设置页面显示"""
        if self.centralStack.currentIndex() == 0:
            # Switch to Settings
            self.centralStack.setCurrentIndex(1)
            # Update icon to 'Return' or keep as Settings but indicate active state?
            # Let's change icon to Return to make it clear
            self.settingsBtn.setIcon(FluentIcon.RETURN)
        else:
            # Switch back to Workstation
            self.centralStack.setCurrentIndex(0)
            self.settingsBtn.setIcon(FluentIcon.SETTING)
    
    def _show_help_menu(self):
        """显示帮助下拉菜单"""
        # 在帮助按钮下方显示菜单
        self.helpMenu.exec(self.helpBtn.mapToGlobal(self.helpBtn.rect().bottomLeft()))
    
    def _on_online_manual(self):
        """打开在线手册"""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://ucn9qdtv44yb.feishu.cn/wiki/GLx9w62tKiy6sRkgScNc3hObnIh?from=from_copylink"))
    
    def _on_check_update(self):
        """检查更新（空壳）"""
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.info(
            "功能开发中",
            "检查更新功能即将上线",
            duration=2000,
            parent=self
        )
    
    def _on_contact(self):
        """显示联系方式对话框"""
        try:
            from PySide6.QtWidgets import QVBoxLayout, QLabel, QWidget
            from PySide6.QtGui import QPixmap, QPainter, QPainterPath
            from PySide6.QtCore import Qt, QRectF
            from qfluentwidgets import PushButton, MessageBoxBase
            from .utils.resources import get_image_path
            import logging
            
            logger = logging.getLogger(__name__)
            logger.info("Opening contact dialog...")
            
            class ContactDialog(MessageBoxBase):
                def __init__(self, parent=None):
                    super().__init__(parent)
                    
                    # 隐藏默认按钮区域（减少高度）
                    self.buttonGroup.hide()
                    
                    # 添加标题标签
                    titleLabel = QLabel("联系我")
                    titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    titleLabel.setStyleSheet("font-size: 18px; font-weight: bold; background: transparent; margin-bottom: 10px;")
                    self.viewLayout.addWidget(titleLabel)
                    
                    # 二维码（圆角处理）
                    qr_path = get_image_path("wechat_qr.png")
                    if qr_path.exists():
                        # 创建圆角二维码
                        class RoundedQRLabel(QLabel):
                            def __init__(self, pixmap, parent=None):
                                super().__init__(parent)
                                self.original_pixmap = pixmap
                                self.setFixedSize(280, 280)  # 缩小尺寸
                                
                            def paintEvent(self, event):
                                painter = QPainter(self)
                                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                                
                                # 创建圆角路径
                                path = QPainterPath()
                                path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 12, 12)
                                painter.setClipPath(path)
                                
                                # 绘制白色背景
                                painter.fillRect(self.rect(), Qt.GlobalColor.white)
                                
                                # 绘制二维码（居中，留边距）
                                margin = 10
                                qr_rect = self.rect().adjusted(margin, margin, -margin, -margin)
                                scaled_pixmap = self.original_pixmap.scaled(
                                    qr_rect.size(),
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation
                                )
                                x = (self.width() - scaled_pixmap.width()) // 2
                                y = (self.height() - scaled_pixmap.height()) // 2
                                painter.drawPixmap(x, y, scaled_pixmap)
                        
                        pixmap = QPixmap(str(qr_path))
                        qr_label = RoundedQRLabel(pixmap)
                        
                        # 居中容器
                        qr_container = QWidget()
                        qr_container.setStyleSheet("background: transparent;")
                        qr_layout = QVBoxLayout(qr_container)
                        qr_layout.setContentsMargins(0, 5, 0, 5)
                        qr_layout.addWidget(qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
                        self.viewLayout.addWidget(qr_container)
                    else:
                        error_label = QLabel("二维码加载失败")
                        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        error_label.setStyleSheet("color: #ff6b6b; background: transparent;")
                        self.viewLayout.addWidget(error_label)
                    
                    # 说明文字
                    desc1 = QLabel("欢迎交流音效管理与 AI 应用")
                    desc1.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    desc1.setStyleSheet("font-size: 13px; color: #cccccc; background: transparent; margin-top: 8px;")
                    self.viewLayout.addWidget(desc1)
                    
                    desc2 = QLabel("使用中遇到问题可随时联系")
                    desc2.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    desc2.setStyleSheet("font-size: 12px; color: #999999; background: transparent; margin-bottom: 5px;")
                    self.viewLayout.addWidget(desc2)
                    
                    # 自定义关闭按钮
                    close_btn = PushButton("关闭")
                    close_btn.clicked.connect(self.reject)
                    close_btn.setFixedWidth(120)
                    close_btn.setFixedHeight(32)
                    btn_layout = QVBoxLayout()
                    btn_layout.setContentsMargins(0, 10, 0, 15)
                    btn_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
                    self.viewLayout.addLayout(btn_layout)
                    
                    # 调整对话框尺寸
                    self.widget.setMinimumWidth(400)
                    self.widget.setMaximumWidth(400)
            
            logger.info("Creating contact dialog...")
            dialog = ContactDialog(self)
            logger.info("Showing contact dialog...")
            dialog.exec()
            logger.info("Contact dialog closed")
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to show contact dialog: {e}", exc_info=True)
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error(
                title="无法打开联系方式",
                content=f"发生错误: {str(e)}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000
            )


    def _setup_player_connections(self):
        self._audio_player.state_changed.connect(lambda s: self.playerBar.set_playing(s == "playing"))
        self._audio_player.position_changed.connect(self.playerBar.set_position)
        self._audio_player.duration_changed.connect(self.playerBar.set_duration)
        self._audio_player.media_ended.connect(self._on_media_ended)

    def _on_media_ended(self):
        self.playerBar.set_playing(False)
        self.playerBar.set_position(0)

    def _connect_player_bar(self):
        self.playerBar.play_clicked.connect(self._audio_player.play)
        self.playerBar.pause_clicked.connect(self._audio_player.pause)
        self.playerBar.stop_clicked.connect(self._audio_player.stop)
        self.playerBar.prev_clicked.connect(lambda: self._audio_player.skip(-5000))
        self.playerBar.next_clicked.connect(lambda: self._audio_player.skip(5000))
        self.playerBar.position_changed.connect(self._audio_player.seek)
        self.playerBar.volume_changed.connect(lambda v: setattr(self._audio_player, 'volume', v / 100.0))

    def _center_window(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

def run_app():
    # 启用高 DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    
    # === 提前初始化数据库（避免首次启动竞争条件）===
    try:
        from transcriptionist_v3.infrastructure.database.connection import get_db_manager
        db_manager = get_db_manager()
        logger.info("Database pre-initialized successfully")
    except Exception as e:
        logger.error(f"Failed to pre-initialize database: {e}")
        # 继续启动，让各组件自己处理错误
    
    # --- 应用程序名称和图标配置 ---
    app.setApplicationName("音译家")
    app.setApplicationDisplayName("音译家")
    app.setOrganizationName("音译家团队")
    app.setOrganizationDomain("transcriptionist.app")
    
    # 设置应用程序图标
    from PySide6.QtGui import QIcon
    from .utils.resources import get_icon_path
    icon_path = get_icon_path("app_icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        logger.warning(f"Application icon not found at {icon_path}")
    
    # --- 国际化 (i18n) 加载 ---
    from PySide6.QtCore import QTranslator, QLibraryInfo, QLocale
    
    # 1. 加载 Qt 标准翻译 (用于对话框按钮: Open, Cancel, Yes, No 等)
    qt_translator = QTranslator(app)
    qt_base_translator = QTranslator(app)
    
    # 尝试从系统路径加载
    trans_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    
    if qt_translator.load("qt_zh_CN", trans_path):
        app.installTranslator(qt_translator)
    else:
        logger.warning(f"Failed to load qt_zh_CN from {trans_path}")
        
    if qt_base_translator.load("qtbase_zh_CN", trans_path):
        app.installTranslator(qt_base_translator)
        
    # 2. 加载应用自身翻译 (如果有)
    # app_translator = QTranslator(app)
    # ...
    
    apply_app_font(app, size=11)
    
    window = TranscriptionistWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(run_app())
