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
    QStackedWidget, QTabWidget, QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QFont, QColor, QIcon

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
from .panels.audio_files_panel import AudioFilesPanel
from .widgets.qt_waveform_preview import WaveformPreviewWidget

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
        self.setWindowTitle("音译家 AI 音效管理工具 v1.1.1")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 750)
        
        # 设置窗口图标（Windows 优先用 .ico，任务栏/Alt+Tab 显示更稳定）
        # 注意：run_app() 中已经设置了 app.setWindowIcon，这里再次设置确保窗口也使用
        from PySide6.QtGui import QIcon
        from .utils.resources import get_app_icon_path
        icon_path = get_app_icon_path()
        if icon_path.exists():
            try:
                _icon = QIcon(str(icon_path))
                # 设置窗口图标
                self.setWindowIcon(_icon)
                # 再次设置应用程序图标（Windows 11 可能需要）
                QApplication.instance().setWindowIcon(_icon)
                logger.debug(f"Window icon set from: {icon_path}")
            except Exception as e:
                logger.error(f"Failed to set window icon: {e}")
        else:
            logger.warning(f"Application icon not found at {icon_path}")
        
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
        
        # 6. 系统托盘（Windows/Linux 支持）
        self._setup_system_tray()
        
        # 7. 周期性刷新窗口图标（防止 Windows 释放图标句柄导致任务栏图标消失）
        self._setup_icon_refresh_timer()
        
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
        self.titleLabel = QLabel("音译家 AI 音效管理工具 v1.1.1", self)
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
        
        # 波形预览（工作区与播放器之间的一条波形条）
        self.waveformPreview = WaveformPreviewWidget(self)
        mainLayout.addWidget(self.waveformPreview)
        
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
        
        # 新增：音效文件面板（放在AI翻译左侧）
        self.audioFilesPanel = AudioFilesPanel(self)
        self.audioFilesPanel.setStyleSheet("#audioFilesPanel { background-color: #1e1e1e; }")
        self.batch_center.add_batch_tab(self.audioFilesPanel, "音效列表")
        # 将库页面作为音效列表的数据提供者（懒加载使用全局索引 -> 文件信息）
        self.audioFilesPanel.set_data_provider(self.libraryInterface.get_file_info_by_index)
        
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
        
        self.workstation.add_center_tab(self.batch_center, "Main")
        
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
        self.batch_center.tabs.setCurrentIndex(0) # 默认显示音效文件面板
        
        # --- 信号连接还原 ---
        self.libraryInterface.play_file.connect(self._on_play_file)
        # v2: 注入库 provider，并使用轻量 selection_changed（避免几万文件路径列表导致卡顿）
        self.aiTranslateInterface.set_library_provider(self.libraryInterface)
        self.aiSearchInterface.set_library_provider(self.libraryInterface)
        self.libraryInterface.selection_changed.connect(self.aiTranslateInterface.set_selection)
        self.libraryInterface.selection_changed.connect(self.aiSearchInterface.set_selection)
        # v1: 兼容旧通道（仅在小选择/单文件勾选时仍会发送）
        self.libraryInterface.files_checked.connect(self.aiTranslateInterface.set_selected_files)
        self.libraryInterface.files_checked.connect(self.aiSearchInterface.update_selection) # Connect Library -> AI Search
        self.libraryInterface.request_ai_translate.connect(lambda: self.batch_center.tabs.setCurrentIndex(1))  # Tab 1 = AI翻译
        self.libraryInterface.request_ai_search.connect(lambda: self.batch_center.tabs.setCurrentIndex(2)) # Tab 2 = AI检索
        
        # 新增：库板块文件夹点击 -> 音效文件面板
        self.libraryInterface.folder_clicked.connect(self._on_folder_clicked)
        # 标签板块选中标签 -> 音效列表（与库板块逻辑一致）
        self.tagsInterface.tags_selection_changed.connect(self._on_tags_selection_changed)
        
        # 音效文件面板信号
        self.audioFilesPanel.files_selected.connect(self.aiTranslateInterface.set_selected_files)
        self.audioFilesPanel.files_selected.connect(self.aiSearchInterface.update_selection)
        self.audioFilesPanel.request_play.connect(self._on_play_file)
        
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
        
        # AI 打标完成后自动刷新库和标签视图（标签页/库页从 DB 重载；并刷新音效列表以显示已写入内存的标签）
        self.aiSearchInterface.tagging_finished.connect(self.libraryInterface.refresh)
        self.aiSearchInterface.tagging_finished.connect(self.tagsInterface.refresh)
        self.aiSearchInterface.tagging_finished.connect(self._on_tagging_finished_refresh_list)
        
        # AI 打标批量更新信号连接
        # AI 打标批量更新信号连接
        self.aiSearchInterface.tags_batch_updated.connect(self.libraryInterface._on_tags_batch_updated)
        self.aiSearchInterface.tags_batch_updated.connect(self._on_tags_updated_refresh_tags_page)

        # Library Clear Synchronization
        self.libraryInterface.library_cleared.connect(self.aiSearchInterface.on_library_cleared)
        self.libraryInterface.library_cleared.connect(self.aiTranslateInterface.on_library_cleared)
        # 清空音效库时，同步停止播放并清空波形/播放器显示
        self.libraryInterface.library_cleared.connect(self._on_library_cleared)

    def _on_tagging_finished_refresh_list(self):
        """打标任务结束时刷新音效列表，确保最后一批标签也能显示。"""
        try:
            self.libraryInterface._refresh_audio_files_panel_after_tags_update()
        except Exception as e:
            logger.debug(f"Refresh audio list after tagging: {e}")

    def _on_tags_updated_refresh_tags_page(self, batch_updates: list):
        """打标批量更新时不再每批全量刷新标签页，避免 6k+ 条时多次全库查询导致卡死/OOM。"""
        # 标签页全量刷新仅在 tagging_finished 时执行一次（见 tagging_finished.connect(tagsInterface.refresh)）
        try:
            logger.debug(f"Tags batch update received ({len(batch_updates)} files), skipping full refresh until tagging finished")
        except Exception as e:
            logger.error(f"Failed to handle tags batch update: {e}")

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
            # 同步加载波形预览（简化同步实现，仅针对当前文件）
            try:
                self.waveformPreview.load_file(file_path)
            except Exception as e:
                logger.warning(f"Waveform preview failed for {file_path}: {e}")
    
    def _on_folder_clicked(self, folder_path: str, indices: list):
        """库板块文件夹被点击，加载音效文件列表（懒加载：只传全局索引列表）"""
        logger.info(f"Folder clicked in Library: {folder_path}, {len(indices)} files")
        self.audioFilesPanel.set_folder_indices(folder_path, indices)
        # 自动切换到音效文件面板
        self.batch_center.tabs.setCurrentIndex(0)

    def _on_tags_selection_changed(self, display_name: str, paths: list):
        """标签板块选中标签变化，将选中标签下的音效填入音效列表（与库板块一致）"""
        indices = self.libraryInterface.get_indices_by_paths(paths) if paths else []
        self.audioFilesPanel.set_folder_indices(display_name, indices)
        if display_name and indices:
            self.batch_center.tabs.setCurrentIndex(0)

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
            from pathlib import Path
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
                    
                    # 二维码 / 联系方式图片（圆角处理）
                    # 优先使用项目资源目录中的 wx-CJ7L738a.jpg，找不到时回退到内置 wechat_qr.png
                    qr_path = get_image_path("wx-CJ7L738a.jpg")
                    if not qr_path.exists():
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
        # 将播放器的进度同步到波形预览
        self._audio_player.position_changed.connect(self.waveformPreview.set_position)
        self._audio_player.duration_changed.connect(self.playerBar.set_duration)
        self._audio_player.duration_changed.connect(self.waveformPreview.set_duration)
        self._audio_player.media_ended.connect(self._on_media_ended)

    def _on_media_ended(self):
        self.playerBar.set_playing(False)
        self.playerBar.set_position(0)
        self.waveformPreview.set_position(0)

    def _on_library_cleared(self):
        """
        当库被清空时：
        - 停止当前播放
        - 释放当前媒体占用
        - 重置底部播放器显示
        - 清空波形预览
        """
        try:
            self._audio_player.unload()
        except Exception:
            # 即使卸载失败，也尽量重置 UI，避免残留状态误导用户
            self._audio_player.stop()

        # 重置播放器 UI
        self.playerBar.set_playing(False)
        self.playerBar.set_position(0)
        self.playerBar.set_track_info("未播放", "选择音效文件开始播放")

        # 清空波形预览
        self.waveformPreview.clear()

    def _connect_player_bar(self):
        self.playerBar.play_clicked.connect(self._audio_player.play)
        self.playerBar.pause_clicked.connect(self._audio_player.pause)
        self.playerBar.stop_clicked.connect(self._audio_player.stop)
        self.playerBar.prev_clicked.connect(lambda: self._audio_player.skip(-5000))
        self.playerBar.next_clicked.connect(lambda: self._audio_player.skip(5000))
        self.playerBar.position_changed.connect(self._audio_player.seek)
        self.playerBar.volume_changed.connect(lambda v: setattr(self._audio_player, 'volume', v / 100.0))
        
        # 允许通过波形点击跳转播放位置
        self.waveformPreview.set_seek_callback(self._audio_player.seek)

    def _center_window(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
    
    def _setup_system_tray(self):
        """配置系统托盘图标"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.debug("System tray not available, skipping")
            return
        
        from .utils.resources import get_app_icon_path
        icon_path = get_app_icon_path()
        if not icon_path.exists():
            logger.warning("App icon not found, cannot create system tray")
            return
        
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(QIcon(str(icon_path)))
        self._tray_icon.setToolTip("音译家 AI 音效管理工具")
        
        # 右键菜单
        tray_menu = QMenu()
        show_action = tray_menu.addAction("显示主窗口")
        show_action.triggered.connect(self._on_tray_show)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._on_tray_quit)
        
        self._tray_icon.setContextMenu(tray_menu)
        
        # 双击托盘图标显示窗口
        self._tray_icon.activated.connect(self._on_tray_activated)
        
        self._tray_icon.show()
        logger.info("System tray icon created")
    
    def _setup_icon_refresh_timer(self):
        """设置周期性图标刷新定时器，防止 Windows 释放图标句柄"""
        from .utils.resources import get_app_icon_path
        
        self._icon_path = get_app_icon_path()
        if not self._icon_path.exists():
            return
        
        # 每30秒刷新一次图标
        self._icon_refresh_timer = QTimer(self)
        self._icon_refresh_timer.timeout.connect(self._refresh_window_icon)
        self._icon_refresh_timer.start(30000)  # 30秒
        logger.debug("Icon refresh timer started (30s interval)")
    
    def _refresh_window_icon(self):
        """刷新窗口图标"""
        try:
            if hasattr(self, '_icon_path') and self._icon_path.exists():
                _icon = QIcon(str(self._icon_path))
                if not _icon.isNull():
                    self.setWindowIcon(_icon)
                    QApplication.instance().setWindowIcon(_icon)
        except Exception as e:
            logger.debug(f"Icon refresh failed: {e}")
    
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """托盘图标被点击"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_tray_show()
    
    def _on_tray_show(self):
        """从托盘恢复显示主窗口"""
        self.show()
        self.raise_()
        self.activateWindow()
    
    def _on_tray_quit(self):
        """从托盘退出应用"""
        self._tray_icon.hide()
        QApplication.instance().quit()
    
    def closeEvent(self, event):
        """关闭窗口时最小化到托盘（若托盘可用），否则正常退出"""
        tray = getattr(self, '_tray_icon', None)
        if tray is not None and tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

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
    
    # 尽早设置应用程序图标（任务栏/Alt+Tab 用；Windows 优先 .ico）
    # Windows 11 需要更早设置，且需要同时设置 app 和窗口的图标
    from PySide6.QtGui import QIcon
    from .utils.resources import get_app_icon_path
    icon_path = get_app_icon_path()
    if icon_path.exists():
        try:
            _icon = QIcon(str(icon_path))
            # 设置应用程序图标（影响任务栏）
            app.setWindowIcon(_icon)
            # Windows 11 可能需要额外设置
            if sys.platform == 'win32':
                # 确保图标被正确加载（包含所有尺寸）
                if not _icon.isNull():
                    logger.info(f"Application icon loaded from: {icon_path}")
                else:
                    logger.warning(f"Icon file exists but failed to load: {icon_path}")
        except Exception as e:
            logger.error(f"Failed to set application icon: {e}")
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
