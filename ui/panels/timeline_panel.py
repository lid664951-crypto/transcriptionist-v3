"""
TimelinePanel - 多轨时间线编辑器 (概念预览)
核心展示波形与音轨信息
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, 
    QGraphicsScene, QGraphicsItem, QFrame
)
from qfluentwidgets import CaptionLabel, TransparentToolButton, FluentIcon

class TrackHeader(QFrame):
    """音轨头部控制区"""
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 80)
        self.setStyleSheet("background: #333; border-bottom: 1px solid #1a1a1a;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        
        self.label = CaptionLabel(name)
        self.label.setStyleSheet("color: #ddd; font-weight: bold;")
        layout.addWidget(self.label)
        
        btn_layout = QHBoxLayout()
        self.mute_btn = TransparentToolButton(FluentIcon.VOLUME)
        self.mute_btn.setFixedSize(24, 24)
        btn_layout.addWidget(self.mute_btn)
        
        self.solo_btn = TransparentToolButton(FluentIcon.PEOPLE)
        self.solo_btn.setFixedSize(24, 24)
        btn_layout.addWidget(self.solo_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

class TimelinePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 1. 音轨列表 (固定宽度)
        self.track_list = QFrame()
        self.track_list.setFixedWidth(180)
        self.track_list.setStyleSheet("background: #252525;")
        self.track_layout = QVBoxLayout(self.track_list)
        self.track_layout.setContentsMargins(0, 0, 0, 0)
        self.track_layout.setSpacing(0)
        
        # 添加一些演示音轨
        self.track_layout.addWidget(TrackHeader("Audio 1"))
        self.track_layout.addWidget(TrackHeader("Audio 2"))
        self.track_layout.addWidget(TrackHeader("AI FX Track"))
        self.track_layout.addStretch()
        
        self.layout.addWidget(self.track_list)
        
        # 2. 波形展示区 (可水平滚动)
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet("background: #1a1a1a; border: none;")
        
        # 绘制一些模拟波形块
        self._add_demo_clips()
        
        self.layout.addWidget(self.view, 1)
        
    def _add_demo_clips(self):
        # 模拟 Clip 块
        from PySide6.QtGui import QColor, QPen, QBrush
        
        # Track 1 Clip
        rect1 = self.scene.addRect(10, 5, 200, 70)
        rect1.setBrush(QBrush(QColor("#4a6a8a")))
        rect1.setPen(QPen(QColor("#3399ff"), 1))
        
        # Track 2 Clip
        rect2 = self.scene.addRect(220, 85, 150, 70)
        rect2.setBrush(QBrush(QColor("#6a4a8a")))
        rect2.setPen(QPen(QColor("#9966ff"), 1))
        
        # Playhead (Red line)
        self.playhead = self.scene.addLine(50, 0, 50, 240)
        self.playhead.setPen(QPen(QColor("#ff3333"), 2))
