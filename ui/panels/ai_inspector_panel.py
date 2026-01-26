"""
AIInspectorPanel - AI 智控与属性面板
位于工作站右侧，动态显示当前工具的配置项
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QScrollArea
from qfluentwidgets import SubtitleLabel, CaptionLabel, CardWidget

class AIInspectorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(8)
        
        # 顶部始终显示的概览信息
        self.header_card = CardWidget()
        header_layout = QVBoxLayout(self.header_card)
        self.title = SubtitleLabel("AI 控制中心")
        self.desc = CaptionLabel("配置 AI 模型与处理参数")
        header_layout.addWidget(self.title)
        header_layout.addWidget(self.desc)
        self.layout.addWidget(self.header_card)
        
        # 滚动区域保存设置项
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.content_stack)
        
        self.layout.addWidget(self.scroll, 1)
        
    def add_config_panel(self, widget: QWidget):
        # 将现有的设置页面或设置部件加入堆栈
        self.content_stack.addWidget(widget)
        
    def switch_to_config(self, index: int):
        self.content_stack.setCurrentIndex(index)
        # 更新标题
        if index == 0: self.title.setText("AI 翻译设置")
        elif index == 1: self.title.setText("AI 检索")
        elif index == 2: self.title.setText("工具箱参数")
