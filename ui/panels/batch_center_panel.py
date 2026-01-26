"""
BatchCenterPanel - 批处理展示中心
整合 AI 翻译结果表格和工具箱进度
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QFrame
from qfluentwidgets import SubtitleLabel

class BatchCenterPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 内部 Tab 切换
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                background: #2b2b2b;
                color: #888;
                padding: 6px 12px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                color: #3399ff;
                border-bottom: 2px solid #3399ff;
            }
            QTabWidget::pane { border: none; }
            QTabBar {
                qproperty-drawBase: 0;
            }
        """)
        
        self.layout.addWidget(self.tabs)
        
    def add_batch_tab(self, widget: QWidget, title: str):
        self.tabs.addTab(widget, title)
