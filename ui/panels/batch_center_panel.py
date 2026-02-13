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
        self.setObjectName("batchCenterPanel")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 内部 Tab 切换
        self.tabs = QTabWidget()
        self.tabs.setObjectName("batchCenterTabs")
        self.tabs.setDocumentMode(True)
        
        self.layout.addWidget(self.tabs)
        
    def add_batch_tab(self, widget: QWidget, title: str):
        self.tabs.addTab(widget, title)
