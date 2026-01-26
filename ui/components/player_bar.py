"""
底部播放器栏组件 - 支持深色主题
"""

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSlider
from PySide6.QtGui import QFont, QPainter, QFontMetrics

from qfluentwidgets import (
    TransparentToolButton, Slider, ToolButton,
    FluentIcon, BodyLabel, CaptionLabel, CardWidget, isDarkTheme
)


class ScrollingLabel(CaptionLabel):
    """可滚动的标签 - 用于显示长文本"""
    
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        self._scroll_pos = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.timeout.connect(self._scroll_text)
        self._needs_scroll = False
        self._scroll_delay_timer = QTimer(self)
        self._scroll_delay_timer.setSingleShot(True)
        self._scroll_delay_timer.timeout.connect(self._start_scrolling)
        
        # 设置初始文本
        if text:
            self.setText(text)
        
    def setText(self, text: str):
        """设置文本并检查是否需要滚动"""
        self._full_text = text
        super().setText(text)
        self._scroll_pos = 0
        self._scroll_timer.stop()
        self._scroll_delay_timer.stop()
        
        # 检查文本是否超出宽度
        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(text)
        if text_width > self.width():
            self._needs_scroll = True
            # 延迟2秒后开始滚动
            self._scroll_delay_timer.start(2000)
        else:
            self._needs_scroll = False
    
    def _start_scrolling(self):
        """开始滚动"""
        if self._needs_scroll:
            self._scroll_timer.start(150)  # 每150ms滚动一次
    
    def _scroll_text(self):
        """滚动文本"""
        if not self._needs_scroll:
            return
        
        self._scroll_pos += 1
        
        # 如果滚动到末尾,重置并暂停
        if self._scroll_pos >= len(self._full_text):
            self._scroll_pos = 0
            self._scroll_timer.stop()
            super().setText(self._full_text)
            # 暂停2秒后重新开始
            self._scroll_delay_timer.start(2000)
        else:
            # 显示滚动后的文本
            scrolled_text = self._full_text[self._scroll_pos:] + "  " + self._full_text[:self._scroll_pos]
            super().setText(scrolled_text)
    
    def resizeEvent(self, event):
        """窗口大小改变时重新检查是否需要滚动"""
        super().resizeEvent(event)
        if self._full_text:
            self.setText(self._full_text)


class PlayerBar(CardWidget):
    """底部播放器栏"""
    
    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    prev_clicked = Signal()
    next_clicked = Signal()
    volume_changed = Signal(int)
    position_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self._is_playing = False
        self._duration = 0
        self._position = 0
        self._is_sliding = False # Flag to prevent programmatic updates during user interaction
        self._updating_programmatically = False # Flag to distinguish programmatic updates from user interaction
        
        # Throttled seeking to prevent UI lag during fast dragging
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._do_throttled_seek)
        self._pending_seek_value = -1
        
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 12, 32, 12) # Modern UI: Increased margins
        layout.setSpacing(24)
        
        # 左侧：当前播放信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4) # Modern UI: Increased spacing
        
        self.title_label = BodyLabel("未播放")
        self.title_label.setStyleSheet("background: transparent;")
        # Removing hardcoded font family, keeping size/weight relative to app font
        font = self.title_label.font()
        font.setPixelSize(14) # Slightly larger for title
        font.setWeight(QFont.Weight.Medium)
        self.title_label.setFont(font)
        info_layout.addWidget(self.title_label)
        
        self.subtitle_label = ScrollingLabel("选择音效文件开始播放")
        self.subtitle_label.setStyleSheet("background: transparent;")
        info_layout.addWidget(self.subtitle_label)
        
        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent;")
        info_widget.setLayout(info_layout)
        info_widget.setFixedWidth(250)  # 增加宽度以显示更多路径
        layout.addWidget(info_widget)
        
        # 中间：播放控制
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(12)  # 增加按钮间距
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 上一曲
        self.prev_btn = TransparentToolButton(FluentIcon.CARE_LEFT_SOLID)
        self.prev_btn.setFixedSize(36, 36)
        self.prev_btn.clicked.connect(self.prev_clicked.emit)
        controls_layout.addWidget(self.prev_btn)
        
        # 播放/暂停
        self.play_btn = ToolButton(FluentIcon.PLAY_SOLID)
        self.play_btn.setFixedSize(44, 44)
        self._update_play_btn_style()
        self.play_btn.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self.play_btn)
        
        # 下一曲
        self.next_btn = TransparentToolButton(FluentIcon.CARE_RIGHT_SOLID)
        self.next_btn.setFixedSize(36, 36)
        self.next_btn.clicked.connect(self.next_clicked.emit)
        controls_layout.addWidget(self.next_btn)
        
        # 停止
        self.stop_btn = TransparentToolButton(FluentIcon.CANCEL_MEDIUM)
        self.stop_btn.setFixedSize(36, 36)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        controls_layout.addWidget(self.stop_btn)
        
        layout.addLayout(controls_layout)
        
        # 添加弹性空间
        layout.addSpacing(20)
        
        # 进度条区域
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(4)
        
        self.progress_slider = Slider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 100)
        self.progress_slider.setValue(0)
        
        # Connect signals for interactive control
        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        self.progress_slider.sliderMoved.connect(self._on_slider_moved)
        self.progress_slider.valueChanged.connect(self._on_position_changed)
        
        progress_layout.addWidget(self.progress_slider)
        
        # 时间显示
        time_layout = QHBoxLayout()
        self.current_time = CaptionLabel("0:00")
        self.current_time.setStyleSheet("background: transparent;")
        self.total_time = CaptionLabel("0:00")
        self.total_time.setStyleSheet("background: transparent;")
        time_layout.addWidget(self.current_time)
        time_layout.addStretch()
        time_layout.addWidget(self.total_time)
        progress_layout.addLayout(time_layout)
        
        progress_widget = QWidget()
        progress_widget.setStyleSheet("background: transparent;")
        progress_widget.setLayout(progress_layout)
        progress_widget.setMinimumWidth(350)  # 增加进度条最小宽度
        layout.addWidget(progress_widget, 1)  # 让进度条可以伸展
        
        # 添加弹性空间
        layout.addSpacing(20)
        
        # 右侧：音量控制
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(8)
        
        self.volume_btn = TransparentToolButton(FluentIcon.VOLUME)
        self.volume_btn.setFixedSize(32, 32)
        volume_layout.addWidget(self.volume_btn)
        
        self.volume_slider = Slider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.volume_changed.emit)
        volume_layout.addWidget(self.volume_slider)
        
        layout.addLayout(volume_layout)
    
    def _update_play_btn_style(self):
        """更新播放按钮样式"""
        self.play_btn.setStyleSheet("""
            ToolButton {
                background-color: #0078D4;
                border-radius: 22px;
            }
            ToolButton:hover {
                background-color: #1084D8;
            }
            ToolButton:pressed {
                background-color: #006CBD;
            }
        """)
    
    def _on_play_clicked(self):
        """播放/暂停按钮点击"""
        if self._is_playing:
            self.pause_clicked.emit()
        else:
            self.play_clicked.emit()
    
    def _on_stop_clicked(self):
        """停止按钮点击"""
        self.stop_clicked.emit()
        self.set_playing(False)
        self.set_position(0)
    
    def _on_slider_pressed(self):
        """Slider pressed - Lock updates"""
        self._is_sliding = True

    def _on_slider_released(self):
        """Slider released - Unlock updates and perform final seek"""
        self._is_sliding = False
        self._seek_timer.stop()
        self.position_changed.emit(self.progress_slider.value())

    def _on_slider_moved(self, value):
        """Slider moved during dragging - update UI and throttle seek"""
        self.current_time.setText(self._format_time(value))
        self._pending_seek_value = value
        if not self._seek_timer.isActive():
            self._seek_timer.start(40) # 40ms throttle for smooth scrolling

    def _do_throttled_seek(self):
        """Perform the actual seek after throttling"""
        if self._pending_seek_value != -1:
            self.position_changed.emit(self._pending_seek_value)
            self._pending_seek_value = -1

    def _on_position_changed(self, value):
        """Handle clicks or keyboard changes (when not dragging)"""
        if self._is_sliding or self._updating_programmatically:
            return
            
        # User clicked or used keyboard to change position
        self.position_changed.emit(value)
        self.current_time.setText(self._format_time(value))
    
    def set_playing(self, playing: bool):
        """设置播放状态"""
        self._is_playing = playing
        if playing:
            self.play_btn.setIcon(FluentIcon.PAUSE_BOLD)
        else:
            self.play_btn.setIcon(FluentIcon.PLAY_SOLID)
    
    def set_track_info(self, title: str, subtitle: str = ""):
        """设置当前播放信息"""
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle if subtitle else "正在播放")
    
    def set_duration(self, duration_ms: int):
        """设置总时长（毫秒）"""
        self._duration = duration_ms
        self.progress_slider.setRange(0, duration_ms)
        self.total_time.setText(self._format_time(duration_ms))
    
    def set_position(self, position_ms: int):
        """设置当前位置（毫秒）"""
        if self._is_sliding:
            return # Don't overwrite user's manual dragging
            
        self._position = position_ms
        self._updating_programmatically = True
        self.progress_slider.setValue(position_ms)
        self._updating_programmatically = False
        self.current_time.setText(self._format_time(position_ms))
    
    def _format_time(self, ms: int) -> str:
        """格式化时间"""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
