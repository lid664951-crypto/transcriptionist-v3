"""
ResourcePanel - 整合音效库、项目管理与在线资源
位于工作站左侧，采用简洁的顶部标签页设计
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from qfluentwidgets import FluentIcon


class ResourcePanel(QWidget):
    """资源面板 - 使用顶部标签页"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 使用标准 QTabWidget，顶部标签
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)  # 更现代的外观
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: #1e1e1e;
            }
            QTabBar {
                qproperty-drawBase: 0;
            }
            QTabBar::tab {
                background: #2b2b2b;
                color: #888;
                padding: 8px 16px;
                margin-right: 2px;
                border: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #1e1e1e;
                color: #3399ff;
            }
            QTabBar::tab:hover:!selected {
                background: #333;
                color: #ccc;
            }
        """)
        
        layout.addWidget(self.tabs, 1)
    
    def add_resource_tab(self, widget: QWidget, icon_path: str, tooltip: str):
        """添加资源标签页"""
        # 直接使用 tooltip 作为标签文字
        self.tabs.addTab(widget, tooltip)
    
    def set_active_tab(self, index: int):
        """设置活动标签页"""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
