"""
Workstation Layout - 为音效工作站设计的停靠式三栏布局
支持左侧资源、中央工作区、右侧属性控制面板的灵活伸缩
新增：侧边面板收起/展开功能
"""

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, 
    QFrame, QStackedWidget, QTabWidget, QSizePolicy
)
from qfluentwidgets import (
    TransparentToolButton, FluentIcon, 
    CaptionLabel
)
from PySide6.QtWidgets import QSizePolicy


class CollapsiblePanel(QFrame):
    """可折叠的侧边面板"""
    
    collapsed_changed = Signal(bool)
    
    def __init__(self, title: str, collapse_direction: str = "left", parent=None):
        """
        Args:
            title: 面板标题
            collapse_direction: 收起方向 "left" 或 "right"
        """
        super().__init__(parent)
        self.setObjectName("collapsiblePanel")
        self._collapsed = False
        self._collapse_direction = collapse_direction
        self._expanded_width = 300  # 记录展开时的宽度
        self._title = title
        
        self._init_ui()
    
    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 头部标题栏
        self.header = QFrame()
        self.header.setFixedHeight(32)
        self.header.setObjectName("panelHeader")
        self.header.setStyleSheet("""
            #panelHeader {
                background-color: #2b2b2b;
                border: none;
            }
        """)
        
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        header_layout.setSpacing(4)
        
        # 折叠按钮（左侧面板按钮在右边，右侧面板按钮在左边）
        self.collapse_btn = TransparentToolButton()
        self.collapse_btn.setFixedSize(24, 24)
        self._update_collapse_icon()
        self.collapse_btn.clicked.connect(self.toggle_collapsed)
        
        # 标题
        self.title_label = CaptionLabel(self._title.upper())
        self.title_label.setStyleSheet("font-weight: bold; color: #aaa; letter-spacing: 1px;")
        
        if self._collapse_direction == "left":
            header_layout.addWidget(self.title_label)
            header_layout.addStretch()
            header_layout.addWidget(self.collapse_btn)
        else:  # right
            header_layout.addWidget(self.collapse_btn)
            header_layout.addWidget(self.title_label)
            header_layout.addStretch()
        
        self.main_layout.addWidget(self.header)
        
        # 内容区域
        self.content = QStackedWidget()
        self.content.setStyleSheet("background-color: #252525;")
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_layout.addWidget(self.content, 1)
        
        # 设置样式
        self.setStyleSheet("""
            #collapsiblePanel {
                background-color: #252525;
                border: none;
            }
        """)
    
    def _update_collapse_icon(self):
        """更新折叠按钮图标"""
        if self._collapse_direction == "left":
            # 左侧面板：折叠时显示向右箭头，展开时显示向左箭头
            icon = FluentIcon.CHEVRON_RIGHT if self._collapsed else FluentIcon.CHEVRON_RIGHT
        else:
            # 右侧面板：折叠时显示向左箭头，展开时显示向右箭头
            icon = FluentIcon.CHEVRON_RIGHT if not self._collapsed else FluentIcon.CHEVRON_RIGHT
        self.collapse_btn.setIcon(icon)

    
    def toggle_collapsed(self):
        """切换折叠状态"""
        if self._collapsed:
            self.expand()
        else:
            self.collapse()
    
    def collapse(self):
        """折叠面板"""
        if self._collapsed:
            return
        
        self._expanded_width = self.width()
        self._collapsed = True
        self.content.hide()
        self.title_label.hide()
        self.setFixedWidth(32)
        self._update_collapse_icon()
        self.collapsed_changed.emit(True)
    
    def expand(self):
        """展开面板"""
        if not self._collapsed:
            return
        
        self._collapsed = False
        self.setMinimumWidth(200)
        self.setMaximumWidth(16777215)  # Qt default max
        self.content.show()
        self.title_label.show()
        self._update_collapse_icon()
        self.collapsed_changed.emit(False)
    
    @property
    def is_collapsed(self) -> bool:
        return self._collapsed


class WorkstationLayout(QWidget):
    """核心布局组件 - 支持可折叠侧边栏"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 主分隔条
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setStyleSheet("QSplitter::handle { background-color: #1a1a1a; }")
        
        # 1. 左侧资源面板（可折叠）
        # 1. 左侧资源面板（可折叠）
        self.left_panel = CollapsiblePanel("音效库", collapse_direction="left")
        self.left_panel.setMinimumWidth(250)
        
        # 2. 中央区域
        self.center_widget = QWidget()
        center_layout = QVBoxLayout(self.center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        
        # 中央标题
        center_header = QFrame()
        center_header.setFixedHeight(32)
        center_header.setStyleSheet("background-color: #2b2b2b; border: none;")
        center_header_layout = QHBoxLayout(center_header)
        center_header_layout.setContentsMargins(12, 0, 12, 0)
        center_title = CaptionLabel("工作台") # Localized
        center_title.setStyleSheet("font-weight: bold; color: #aaa; letter-spacing: 1px;")
        center_header_layout.addWidget(center_title)
        center_header_layout.addStretch()
        center_layout.addWidget(center_header)
        
        self.center_tabs = QTabWidget()
        self.center_tabs.setDocumentMode(True)
        self.center_tabs.tabBar().hide() # Hide the "Main" tab bar as requested
        self.center_tabs.setStyleSheet("""
            QTabBar::tab {
                background: #252525;
                color: #888;
                padding: 8px 16px;
                border-right: 1px solid #1a1a1a;
            }
            QTabBar::tab:selected {
                background: #2b2b2b;
                color: #ddd;
                border-bottom: 2px solid #3399ff;
            }
            QTabWidget::pane {
                border: none;
                background: #2b2b2b;
            }
        """)
        center_layout.addWidget(self.center_tabs)
        
        # 加入分隔条
        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.center_widget)
        # self.main_splitter.addWidget(self.right_panel) # 移除右侧面板
        
        # 设置默认比例 (Left:Center = 1:4)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        
        # 设置初始大小
        self.main_splitter.setSizes([280, 1000])
        
        main_layout.addWidget(self.main_splitter)

    def add_left_widget(self, widget: QWidget, name: str):
        self.left_panel.content.addWidget(widget)
        
    def add_center_tab(self, widget: QWidget, title: str):
        self.center_tabs.addTab(widget, title)
        
    # def add_right_widget(self, widget: QWidget, name: str):
    #     self.right_panel.content.addWidget(widget)
    
    def collapse_left(self):
        """收起左侧面板"""
        self.left_panel.collapse()
    
    def expand_left(self):
        """展开左侧面板"""
        self.left_panel.expand()
    
    # def collapse_right(self):
    #     """收起右侧面板"""
    #     self.right_panel.collapse()
    
    # def expand_right(self):
    #     """展开右侧面板"""
    #     self.right_panel.expand()
