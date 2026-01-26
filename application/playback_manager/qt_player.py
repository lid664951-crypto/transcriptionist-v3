"""
Qt Audio Player Module

使用 PySide6 的 QMediaPlayer 实现音频播放
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

logger = logging.getLogger(__name__)


class QtAudioPlayer(QObject):
    """
    基于 Qt 的音频播放器
    
    Features:
    - 播放、暂停、停止、跳转
    - 音量控制
    - 位置/时长追踪（使用定时器轮询）
    """
    
    # 信号
    state_changed = Signal(str)  # "playing", "paused", "stopped"
    position_changed = Signal(int)  # 毫秒
    duration_changed = Signal(int)  # 毫秒
    error_occurred = Signal(str)
    media_ended = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        
        self._current_file: Optional[Path] = None
        self._volume = 0.8
        self._audio_output.setVolume(self._volume)
        
        # 连接信号
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        
        # 使用定时器轮询位置（比信号更可靠）
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(100)  # 每100ms更新一次
        self._position_timer.timeout.connect(self._update_position)
        
        logger.info("Qt Audio Player initialized")
    
    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    
    @property
    def is_paused(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    
    @property
    def volume(self) -> float:
        return self._volume
    
    @volume.setter
    def volume(self, value: float):
        self._volume = max(0.0, min(1.0, value))
        self._audio_output.setVolume(self._volume)
    
    @property
    def current_file(self) -> Optional[Path]:
        return self._current_file
    
    def load(self, file_path: str) -> bool:
        """加载音频文件 (支持本地路径和 URL)"""
        # Check if URL
        is_url = file_path.startswith("http://") or file_path.startswith("https://")
        
        if is_url:
            self.stop()
            self._current_file = None # URL has no Path
            url = QUrl(file_path)
            self._player.setSource(url)
            logger.info(f"Loaded URL: {file_path}")
            return True
        else:
            path = Path(file_path)
            if not path.exists():
                logger.error(f"File not found: {path}")
                self.error_occurred.emit(f"文件不存在: {path.name}")
                return False
            
            # 停止当前播放
            self.stop()
            
            self._current_file = path
            url = QUrl.fromLocalFile(str(path))
            self._player.setSource(url)
            
            logger.info(f"Loaded file: {path.name}")
            return True
    
    def play(self) -> bool:
        """开始或恢复播放"""
        if self._player.source().isEmpty():
            return False
        
        self._player.play()
        self._position_timer.start()
        return True
    
    def pause(self):
        """暂停播放"""
        self._player.pause()
        self._position_timer.stop()
    
    def stop(self):
        """停止播放"""
        self._player.stop()
        self._position_timer.stop()
        
    def unload(self):
        """卸载当前媒体，释放文件占用"""
        self.stop()
        self._player.setSource(QUrl())
        self._current_file = None
    
    def toggle_play_pause(self):
        """切换播放/暂停"""
        if self.is_playing:
            self.pause()
        else:
            self.play()
    
    def seek(self, position_ms: int):
        """跳转到指定位置（毫秒）"""
        self._player.setPosition(position_ms)
    
    def skip(self, offset_ms: int):
        """相对跳转（毫秒，正数前进，负数后退）"""
        new_pos = max(0, min(self.get_duration(), self.get_position() + offset_ms))
        self.seek(new_pos)
    
    def get_position(self) -> int:
        """获取当前位置（毫秒）"""
        return self._player.position()
    
    def get_duration(self) -> int:
        """获取总时长（毫秒）"""
        return self._player.duration()
    
    def _update_position(self):
        """定时更新位置"""
        pos = self._player.position()
        self.position_changed.emit(pos)
    
    def _on_state_changed(self, state):
        """播放状态改变"""
        state_map = {
            QMediaPlayer.PlaybackState.StoppedState: "stopped",
            QMediaPlayer.PlaybackState.PlayingState: "playing",
            QMediaPlayer.PlaybackState.PausedState: "paused"
        }
        state_str = state_map.get(state, "stopped")
        self.state_changed.emit(state_str)
        
        # 根据状态控制定时器
        if state == QMediaPlayer.PlaybackState.PlayingState:
            if not self._position_timer.isActive():
                self._position_timer.start()
        else:
            self._position_timer.stop()
    
    def _on_duration_changed(self, duration):
        """时长改变"""
        self.duration_changed.emit(duration)
        logger.info(f"Duration: {duration}ms")
    
    def _on_error(self, error, error_string):
        """错误处理"""
        logger.error(f"Player error: {error_string}")
        self.error_occurred.emit(error_string)
    
    def _on_media_status(self, status):
        """媒体状态改变"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._position_timer.stop()
            self.media_ended.emit()


# 全局播放器实例
_qt_player: Optional[QtAudioPlayer] = None


def get_qt_player() -> QtAudioPlayer:
    """获取全局 Qt 播放器实例"""
    global _qt_player
    if _qt_player is None:
        _qt_player = QtAudioPlayer()
    return _qt_player
