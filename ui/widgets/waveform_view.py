"""
Waveform Visualization Widget

GTK4 波形可视化组件，显示音频波形并支持点击跳转。
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional, List
import threading

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib, Graphene, Gsk

logger = logging.getLogger(__name__)

# 尝试导入 numpy 用于波形数据处理
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.warning("NumPy not available, waveform display will be limited")


class WaveformData:
    """波形数据容器"""
    
    def __init__(self, peaks: List[float], duration_ms: int):
        self.peaks = peaks  # 归一化的峰值列表 (0.0 - 1.0)
        self.duration_ms = duration_ms
    
    @classmethod
    def from_audio_file(cls, file_path: Path, num_samples: int = 200) -> Optional['WaveformData']:
        """从音频文件提取波形数据"""
        if not NUMPY_AVAILABLE:
            logger.warning("NumPy not available, cannot extract waveform")
            return None
        
        logger.info(f"WaveformData: Extracting from {file_path}")
        
        try:
            # 优先使用librosa（支持更多格式）
            try:
                import librosa
                logger.info("WaveformData: Using librosa")
                
                # 加载音频文件
                y, sr = librosa.load(str(file_path), sr=None, mono=True)
                duration_ms = int(len(y) / sr * 1000)
                logger.info(f"WaveformData: Loaded {len(y)} samples, sr={sr}, duration={duration_ms}ms")
                
                # 计算峰值
                chunk_size = max(1, len(y) // num_samples)
                peaks = []
                for i in range(0, len(y), chunk_size):
                    chunk = y[i:i + chunk_size]
                    if len(chunk) > 0:
                        peak = np.abs(chunk).max()
                        peaks.append(float(peak))
                
                # 归一化
                max_peak = max(peaks) if peaks else 1.0
                if max_peak > 0:
                    peaks = [p / max_peak for p in peaks]
                
                logger.info(f"WaveformData: Generated {len(peaks)} peaks")
                return cls(peaks[:num_samples], duration_ms)
                
            except ImportError:
                logger.info("WaveformData: librosa not available, trying soundfile")
            except Exception as e:
                logger.warning(f"WaveformData: librosa failed: {e}, trying soundfile")
            
            # 回退到soundfile
            try:
                import soundfile as sf
                
                data, sr = sf.read(str(file_path))
                
                # 转换为单声道
                if len(data.shape) > 1:
                    data = data.mean(axis=1)
                
                duration_ms = int(len(data) / sr * 1000)
                
                # 计算峰值
                chunk_size = max(1, len(data) // num_samples)
                peaks = []
                for i in range(0, len(data), chunk_size):
                    chunk = data[i:i + chunk_size]
                    if len(chunk) > 0:
                        peak = np.abs(chunk).max()
                        peaks.append(float(peak))
                
                # 归一化
                max_peak = max(peaks) if peaks else 1.0
                if max_peak > 0:
                    peaks = [p / max_peak for p in peaks]
                
                return cls(peaks[:num_samples], duration_ms)
                
            except ImportError:
                pass
            
            # 最后回退到wave模块（仅支持WAV）
            import wave
            import struct
            
            with wave.open(str(file_path), 'rb') as wav:
                n_channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                framerate = wav.getframerate()
                n_frames = wav.getnframes()
                
                duration_ms = int(n_frames / framerate * 1000)
                
                # 读取所有帧
                raw_data = wav.readframes(n_frames)
                
                # 解析采样数据
                if sample_width == 1:
                    fmt = f"{n_frames * n_channels}B"
                    samples = np.array(struct.unpack(fmt, raw_data), dtype=np.float32) - 128
                elif sample_width == 2:
                    fmt = f"{n_frames * n_channels}h"
                    samples = np.array(struct.unpack(fmt, raw_data), dtype=np.float32)
                else:
                    return None
                
                # 转换为单声道
                if n_channels > 1:
                    samples = samples.reshape(-1, n_channels).mean(axis=1)
                
                # 计算峰值
                chunk_size = max(1, len(samples) // num_samples)
                peaks = []
                for i in range(0, len(samples), chunk_size):
                    chunk = samples[i:i + chunk_size]
                    if len(chunk) > 0:
                        peak = np.abs(chunk).max()
                        peaks.append(peak)
                
                # 归一化
                max_peak = max(peaks) if peaks else 1.0
                if max_peak > 0:
                    peaks = [p / max_peak for p in peaks]
                
                return cls(peaks[:num_samples], duration_ms)
                
        except Exception as e:
            logger.error(f"Failed to extract waveform: {e}")
            return None


class WaveformView(Gtk.DrawingArea):
    """
    波形可视化组件
    
    功能：
    - 显示音频波形
    - 显示播放进度
    - 点击跳转到指定位置
    - 现代化渐变设计
    """
    
    __gtype_name__ = "WaveformView"
    
    def __init__(self):
        super().__init__()
        
        self._waveform_data: Optional[WaveformData] = None
        self._position_ms = 0
        self._duration_ms = 0
        self._loading = False
        
        # 现代化颜色配置
        self._wave_color = Gdk.RGBA()
        self._wave_color.parse("#62a0ea")  # 亮蓝色
        
        self._played_color = Gdk.RGBA()
        self._played_color.parse("#3584e4")  # 主蓝色
        
        self._bg_color = Gdk.RGBA()
        self._bg_color.parse("#1e1e1e")  # 深色背景
        
        self._position_color = Gdk.RGBA()
        self._position_color.parse("#ffffff")  # 白色播放头
        
        self._grid_color = Gdk.RGBA()
        self._grid_color.parse("#2d2d2d")  # 网格线颜色
        
        # 设置最小尺寸
        self.set_size_request(200, 60)
        self.set_hexpand(True)
        
        # 设置绘制函数
        self.set_draw_func(self._draw)
        
        # 点击事件
        click_gesture = Gtk.GestureClick()
        click_gesture.connect("pressed", self._on_click)
        self.add_controller(click_gesture)
        
        # 鼠标移动事件（用于悬停效果）
        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect("motion", self._on_motion)
        motion_controller.connect("leave", self._on_leave)
        self.add_controller(motion_controller)
        
        self._hover_x = -1
        
        # 回调
        self._on_seek_callback: Optional[callable] = None
    
    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        """绘制波形 - 现代化设计"""
        import cairo
        
        # 绘制圆角背景
        radius = 8
        cr.new_sub_path()
        cr.arc(width - radius, radius, radius, -math.pi/2, 0)
        cr.arc(width - radius, height - radius, radius, 0, math.pi/2)
        cr.arc(radius, height - radius, radius, math.pi/2, math.pi)
        cr.arc(radius, radius, radius, math.pi, 3*math.pi/2)
        cr.close_path()
        
        # 背景渐变
        gradient = cairo.LinearGradient(0, 0, 0, height)
        gradient.add_color_stop_rgba(0, 0.12, 0.12, 0.12, 1)  # 顶部深色
        gradient.add_color_stop_rgba(1, 0.08, 0.08, 0.08, 1)  # 底部更深
        cr.set_source(gradient)
        cr.fill_preserve()
        
        # 边框
        cr.set_source_rgba(0.2, 0.2, 0.2, 0.5)
        cr.set_line_width(1)
        cr.stroke()
        
        # 绘制中心线
        center_y = height / 2
        cr.set_source_rgba(0.25, 0.25, 0.25, 0.5)
        cr.set_line_width(1)
        cr.move_to(radius, center_y)
        cr.line_to(width - radius, center_y)
        cr.stroke()
        
        if self._loading:
            # 显示加载中动画
            cr.set_source_rgba(1, 1, 1, 0.4)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(11)
            text = "加载波形..."
            extents = cr.text_extents(text)
            cr.move_to((width - extents.width) / 2, (height + extents.height) / 2)
            cr.show_text(text)
            return
        
        if not self._waveform_data or not self._waveform_data.peaks:
            # 无数据时显示占位符
            self._draw_placeholder(cr, width, height)
            return
        
        # 绘制波形
        peaks = self._waveform_data.peaks
        num_peaks = len(peaks)
        bar_width = max(2, (width - 2 * radius) / num_peaks)
        padding = radius
        
        # 计算播放进度位置
        progress = 0
        if self._duration_ms > 0:
            progress = self._position_ms / self._duration_ms
        progress_x = padding + int(progress * (width - 2 * padding))
        
        # 绘制波形条
        for i, peak in enumerate(peaks):
            x = padding + i * bar_width
            bar_height = max(2, peak * (height - 16) / 2)  # 最小高度2px
            
            # 已播放部分用亮色，未播放用暗色
            if x < progress_x:
                # 已播放 - 渐变蓝色
                bar_gradient = cairo.LinearGradient(0, center_y - bar_height, 0, center_y + bar_height)
                bar_gradient.add_color_stop_rgba(0, 0.38, 0.63, 0.92, 0.9)  # 亮蓝
                bar_gradient.add_color_stop_rgba(0.5, 0.21, 0.52, 0.89, 1)  # 主蓝
                bar_gradient.add_color_stop_rgba(1, 0.38, 0.63, 0.92, 0.9)  # 亮蓝
                cr.set_source(bar_gradient)
            else:
                # 未播放 - 灰色
                cr.set_source_rgba(0.4, 0.4, 0.4, 0.6)
            
            # 绘制圆角波形条
            bar_x = x
            bar_y = center_y - bar_height
            bar_w = max(1, bar_width - 1)
            bar_h = bar_height * 2
            bar_r = min(1.5, bar_w / 2)
            
            cr.new_sub_path()
            cr.arc(bar_x + bar_w - bar_r, bar_y + bar_r, bar_r, -math.pi/2, 0)
            cr.arc(bar_x + bar_w - bar_r, bar_y + bar_h - bar_r, bar_r, 0, math.pi/2)
            cr.arc(bar_x + bar_r, bar_y + bar_h - bar_r, bar_r, math.pi/2, math.pi)
            cr.arc(bar_x + bar_r, bar_y + bar_r, bar_r, math.pi, 3*math.pi/2)
            cr.close_path()
            cr.fill()
        
        # 绘制悬停指示线
        if self._hover_x >= 0 and self._duration_ms > 0:
            cr.set_source_rgba(1, 1, 1, 0.3)
            cr.set_line_width(1)
            cr.move_to(self._hover_x, 4)
            cr.line_to(self._hover_x, height - 4)
            cr.stroke()
        
        # 绘制播放位置指示线（播放头）
        if self._duration_ms > 0:
            # 播放头阴影
            cr.set_source_rgba(0, 0, 0, 0.3)
            cr.set_line_width(4)
            cr.move_to(progress_x + 1, 4)
            cr.line_to(progress_x + 1, height - 4)
            cr.stroke()
            
            # 播放头主体
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.set_line_width(2)
            cr.move_to(progress_x, 4)
            cr.line_to(progress_x, height - 4)
            cr.stroke()
            
            # 播放头顶部圆点
            cr.arc(progress_x, 4, 3, 0, 2 * math.pi)
            cr.fill()
    
    def _on_motion(self, controller, x: float, y: float) -> None:
        """鼠标移动"""
        self._hover_x = x
        self.queue_draw()
    
    def _on_leave(self, controller) -> None:
        """鼠标离开"""
        self._hover_x = -1
        self.queue_draw()
    
    def _draw_placeholder(self, cr, width: int, height: int) -> None:
        """绘制占位符 - 现代化设计"""
        import cairo
        
        center_y = height / 2
        
        # 绘制模拟波形（静态装饰）
        cr.set_source_rgba(0.3, 0.3, 0.3, 0.3)
        num_bars = 50
        bar_width = (width - 20) / num_bars
        
        for i in range(num_bars):
            # 生成伪随机高度
            h = abs(math.sin(i * 0.3) * math.cos(i * 0.7)) * (height - 20) / 2
            h = max(2, h)
            x = 10 + i * bar_width
            cr.rectangle(x, center_y - h, bar_width - 1, h * 2)
        cr.fill()
        
        # 绘制提示文字
        cr.set_source_rgba(1, 1, 1, 0.3)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        text = "选择音频文件播放"
        extents = cr.text_extents(text)
        cr.move_to((width - extents.width) / 2, (height + extents.height) / 2)
        cr.show_text(text)
    
    def _on_click(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        """点击跳转"""
        if self._duration_ms <= 0:
            return
        
        width = self.get_width()
        if width <= 0:
            return
        
        # 计算点击位置对应的时间
        progress = x / width
        position_ms = int(progress * self._duration_ms)
        
        if self._on_seek_callback:
            self._on_seek_callback(position_ms)
    
    def load_file(self, file_path) -> None:
        """加载音频文件波形"""
        from pathlib import Path
        
        # 确保是 Path 对象
        if not isinstance(file_path, Path):
            file_path = Path(file_path)
        
        logger.info(f"WaveformView: Loading waveform for {file_path}")
        
        self._loading = True
        self._waveform_data = None
        self.queue_draw()
        
        def load_in_thread():
            logger.info(f"WaveformView: Starting waveform extraction in thread")
            data = WaveformData.from_audio_file(file_path)
            if data:
                logger.info(f"WaveformView: Extracted {len(data.peaks)} peaks, duration={data.duration_ms}ms")
            else:
                logger.warning(f"WaveformView: Failed to extract waveform data")
            GLib.idle_add(self._on_load_complete, data)
        
        thread = threading.Thread(target=load_in_thread, daemon=True)
        thread.start()
    
    def _on_load_complete(self, data: Optional[WaveformData]) -> bool:
        """加载完成回调"""
        logger.info(f"WaveformView: Load complete, data={'present' if data else 'None'}")
        self._loading = False
        self._waveform_data = data
        if data:
            self._duration_ms = data.duration_ms
            logger.info(f"WaveformView: Set duration to {self._duration_ms}ms")
        self.queue_draw()
        return False
    
    def set_waveform_data(self, data: WaveformData) -> None:
        """直接设置波形数据"""
        self._waveform_data = data
        self._duration_ms = data.duration_ms
        self.queue_draw()
    
    def set_position(self, position_ms: int) -> None:
        """设置播放位置"""
        self._position_ms = position_ms
        self.queue_draw()
    
    def set_duration(self, duration_ms: int) -> None:
        """设置总时长"""
        self._duration_ms = duration_ms
        self.queue_draw()
    
    def set_on_seek(self, callback: callable) -> None:
        """设置跳转回调"""
        self._on_seek_callback = callback
    
    def clear(self) -> None:
        """清除波形数据"""
        self._waveform_data = None
        self._position_ms = 0
        self._duration_ms = 0
        self.queue_draw()
