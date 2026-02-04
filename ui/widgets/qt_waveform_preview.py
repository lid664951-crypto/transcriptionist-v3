"""
Qt Waveform Preview Widget

简化版波形预览组件：
- 只显示当前音效的一条波形条
- 显示播放进度
- 支持点击波形跳转播放位置

注意：为控制复杂度和依赖，本组件：
- 优先使用 librosa，其次 soundfile，最后退回到 wave 仅支持 WAV
- 若依赖缺失或读取失败，会显示占位提示，不影响主功能
- 波形加载在后台线程执行，避免阻塞 UI
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import List, Optional, Callable

from PySide6.QtCore import Qt, QRectF, QThread, QObject, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

try:
    import numpy as np  # type: ignore
    NUMPY_AVAILABLE = True
except Exception:  # pragma: no cover
    NUMPY_AVAILABLE = False
    logger.warning("NumPy not available, waveform preview will be disabled.")


class WaveformData:
    """简单的波形数据容器."""

    def __init__(self, peaks: List[float], duration_ms: int):
        self.peaks = peaks  # 0.0 - 1.0 之间的归一化峰值
        self.duration_ms = duration_ms

    @classmethod
    def from_audio_file(cls, file_path: Path, num_samples: int = 400) -> Optional["WaveformData"]:
        """从音频文件提取波形数据（同步版本，仅用于单文件预览）。"""
        if not NUMPY_AVAILABLE:
            return None

        try:
            # 优先使用 librosa（支持更多格式）
            try:
                import librosa  # type: ignore

                y, sr = librosa.load(str(file_path), sr=None, mono=True)
                duration_ms = int(len(y) / sr * 1000) if sr > 0 else 0
                if len(y) == 0:
                    return None

                chunk_size = max(1, len(y) // num_samples)
                peaks: List[float] = []
                for i in range(0, len(y), chunk_size):
                    chunk = y[i : i + chunk_size]
                    if len(chunk) > 0:
                        peak = float(np.abs(chunk).max())
                        peaks.append(peak)

                max_peak = max(peaks) if peaks else 1.0
                if max_peak > 0:
                    peaks = [p / max_peak for p in peaks]

                return cls(peaks[:num_samples], duration_ms)
            except ImportError:
                logger.info("WaveformPreview: librosa not available, trying soundfile")
            except Exception as e:
                logger.warning(f"WaveformPreview: librosa failed: {e}, trying soundfile")

            # 回退到 soundfile
            try:
                import soundfile as sf  # type: ignore

                data, sr = sf.read(str(file_path))
                if sr <= 0:
                    return None

                if len(data.shape) > 1:
                    data = data.mean(axis=1)

                duration_ms = int(len(data) / sr * 1000)
                if len(data) == 0:
                    return None

                chunk_size = max(1, len(data) // num_samples)
                peaks = []
                for i in range(0, len(data), chunk_size):
                    chunk = data[i : i + chunk_size]
                    if len(chunk) > 0:
                        peak = float(np.abs(chunk).max())
                        peaks.append(peak)

                max_peak = max(peaks) if peaks else 1.0
                if max_peak > 0:
                    peaks = [p / max_peak for p in peaks]

                return cls(peaks[:num_samples], duration_ms)
            except ImportError:
                logger.info("WaveformPreview: soundfile not available, trying wave module")
            except Exception as e:
                logger.warning(f"WaveformPreview: soundfile failed: {e}, trying wave module")

            # 最后回退到 wave，只支持 PCM WAV
            import wave
            import struct

            with wave.open(str(file_path), "rb") as wav:
                n_channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                framerate = wav.getframerate()
                n_frames = wav.getnframes()

                if framerate <= 0 or n_frames <= 0:
                    return None

                duration_ms = int(n_frames / framerate * 1000)
                raw_data = wav.readframes(n_frames)

                if sample_width == 1:
                    fmt = f"{n_frames * n_channels}B"
                    samples = np.array(struct.unpack(fmt, raw_data), dtype=np.float32) - 128
                elif sample_width == 2:
                    fmt = f"{n_frames * n_channels}h"
                    samples = np.array(struct.unpack(fmt, raw_data), dtype=np.float32)
                else:
                    return None

                if n_channels > 1:
                    samples = samples.reshape(-1, n_channels).mean(axis=1)

                if len(samples) == 0:
                    return None

                chunk_size = max(1, len(samples) // num_samples)
                peaks = []
                for i in range(0, len(samples), chunk_size):
                    chunk = samples[i : i + chunk_size]
                    if len(chunk) > 0:
                        peak = float(np.abs(chunk).max())
                        peaks.append(peak)

                max_peak = max(peaks) if peaks else 1.0
                if max_peak > 0:
                    peaks = [p / max_peak for p in peaks]

                return cls(peaks[:num_samples], duration_ms)
        except Exception as e:
            logger.error(f"WaveformPreview: failed to extract waveform from {file_path}: {e}")
            return None


class _WaveformLoadWorker(QObject):
    """后台线程加载波形数据，避免阻塞 UI."""
    
    finished = Signal(object)  # WaveformData or None
    
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
    
    def run(self):
        """在后台线程中加载波形."""
        try:
            path = Path(self.file_path)
            if not path.exists():
                self.finished.emit(None)
                return
            
            data = WaveformData.from_audio_file(path)
            self.finished.emit(data)
        except Exception as e:
            logger.error(f"WaveformLoadWorker: failed to load {self.file_path}: {e}")
            self.finished.emit(None)


class WaveformPreviewWidget(QWidget):
    """
    Qt 简化版波形预览组件。

    仅展示单条音频的波形与播放进度，并支持点击跳转。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._waveform: Optional[WaveformData] = None
        self._position_ms: int = 0
        self._duration_ms: int = 0
        self._loading: bool = False
        self._seek_callback: Optional[Callable[[int], None]] = None
        
        # 后台线程相关
        self._load_thread: Optional[QThread] = None
        self._load_worker: Optional[_WaveformLoadWorker] = None
        self._pending_file: Optional[str] = None  # 用于取消旧的加载请求

        self.setMinimumHeight(72)
        self.setMaximumHeight(96)
        self.setMouseTracking(True)
        self._hover_x: int = -1

    # ---------- 公共 API ----------
    def load_file(self, file_path: str) -> None:
        """从给定音频文件加载波形数据（异步，不阻塞 UI）."""
        # 取消正在进行的加载
        self._cancel_loading()
        
        path = Path(file_path)
        if not path.exists():
            self._waveform = None
            self._duration_ms = 0
            self._position_ms = 0
            self.update()
            return

        if not NUMPY_AVAILABLE:
            logger.warning("WaveformPreview: NumPy not available, skip waveform extraction.")
            self._waveform = None
            self._duration_ms = 0
            self._position_ms = 0
            self.update()
            return

        # 标记正在加载
        self._loading = True
        self._waveform = None
        self._duration_ms = 0
        self._position_ms = 0
        self._pending_file = file_path
        self.update()
        
        # 启动后台线程加载
        self._load_thread = QThread()
        self._load_worker = _WaveformLoadWorker(file_path)
        self._load_worker.moveToThread(self._load_thread)
        
        # 保存当前文件路径，用于验证回调时是否仍然有效
        current_file = file_path
        
        def on_finished(data):
            # 验证文件路径是否仍然匹配（避免旧文件的回调覆盖新文件）
            if self._pending_file == current_file:
                self._on_load_finished(data)
        
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(on_finished)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._cleanup_load_thread)
        
        self._load_thread.start()
    
    def _on_load_finished(self, data: Optional[WaveformData]) -> None:
        """后台加载完成回调."""
        # 检查是否已经被取消（文件已切换）
        if self._load_thread is None or not self._load_thread.isRunning():
            # 加载已被取消，忽略结果
            return
        
        self._loading = False
        if data:
            self._waveform = data
            self._duration_ms = data.duration_ms
        else:
            self._waveform = None
            self._duration_ms = 0
        self._position_ms = 0
        self.update()
    
    def _cancel_loading(self) -> None:
        """取消正在进行的加载任务."""
        if self._load_thread is not None and self._load_thread.isRunning():
            # 断开信号连接，避免回调执行
            try:
                if self._load_worker is not None:
                    self._load_worker.finished.disconnect()
            except Exception:
                pass
            # 请求线程退出
            self._load_thread.quit()
            # 等待线程结束，但设置更长的超时（librosa/soundfile 可能需要时间）
            if not self._load_thread.wait(2000):  # 增加到 2 秒
                # 如果线程还在运行，强制终止（避免资源泄漏）
                logger.warning("WaveformLoadWorker thread did not exit in time, terminating")
                try:
                    self._load_thread.terminate()
                    self._load_thread.wait(500)
                except Exception as e:
                    logger.error(f"Failed to terminate waveform load thread: {e}")
        self._cleanup_load_thread()
    
    def _cleanup_load_thread(self) -> None:
        """清理加载线程资源."""
        if self._load_thread is not None:
            try:
                if self._load_thread.isRunning():
                    self._load_thread.quit()
                    if not self._load_thread.wait(200):  # 短暂等待
                        self._load_thread.terminate()
                        self._load_thread.wait(200)
            except (RuntimeError, Exception) as e:
                logger.debug(f"Error cleaning up waveform load thread: {e}")
            finally:
                # 确保线程对象被删除
                self._load_thread.deleteLater()
                self._load_thread = None
        if self._load_worker is not None:
            try:
                self._load_worker.deleteLater()
            except Exception:
                pass
            self._load_worker = None

    def set_position(self, position_ms: int) -> None:
        """设置播放位置（毫秒），用于与 QtAudioPlayer 联动。"""
        self._position_ms = max(0, position_ms)
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        """设置总时长（可用于覆盖播放器时长信息）。"""
        self._duration_ms = max(0, duration_ms)
        self.update()

    def set_seek_callback(self, callback: Callable[[int], None]) -> None:
        """设置点击波形时用于跳转播放位置的回调函数。"""
        self._seek_callback = callback

    def clear(self) -> None:
        """清除当前波形。"""
        self._cancel_loading()
        self._waveform = None
        self._duration_ms = 0
        self._position_ms = 0
        self._loading = False
        self.update()

    # ---------- 绘制逻辑 ----------
    def paintEvent(self, event) -> None:  # type: ignore[override]
        """自绘波形条（更扁平、贴合整体深色工作台的风格）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 使用更扁平的风格：不再画大卡片，只在中间区域画波形
        rect = self.rect().adjusted(16, 6, -16, -6)
        center_y = rect.center().y()

        # 细中线，颜色更柔和，避免太扎眼
        painter.setPen(QPen(QColor(70, 70, 70, 120), 1))
        painter.drawLine(rect.left(), center_y, rect.right(), center_y)

        if self._loading:
            painter.setPen(QColor(220, 220, 220))
            painter.drawText(rect, Qt.AlignCenter, "加载波形中…")
            return

        if not self._waveform or not self._waveform.peaks:
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(rect, Qt.AlignCenter, "选择音效以预览波形")
            return

        peaks = self._waveform.peaks
        num_peaks = len(peaks)
        bar_area = rect.adjusted(0, 4, 0, -4)
        total_width = bar_area.width()
        bar_width = max(2.0, total_width / max(1, num_peaks))

        # 播放进度 X 坐标
        if self._duration_ms > 0:
            progress = max(0.0, min(1.0, self._position_ms / max(1, self._duration_ms)))
        else:
            progress = 0.0
        progress_x = bar_area.left() + int(progress * bar_area.width())

        for i, peak in enumerate(peaks):
            x = bar_area.left() + int(i * bar_width)
            # 波形更“饱满”一些，占据更大高度
            h = max(2.0, float(peak) * (bar_area.height() - 2) / 2.0)
            y = center_y - h
            w = max(1.0, bar_width - 1.0)
            rect_bar = QRectF(x, y, w, h * 2.0)

            if x + w < progress_x:
                # 已播放部分：使用与整体主题接近的 Fluent 蓝
                painter.setBrush(QColor(51, 153, 255))  # #3399FF
            else:
                # 未播放部分：稍暗的灰，减少干扰
                painter.setBrush(QColor(70, 70, 70))

            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect_bar, 2.0, 2.0)

        # 播放头
        if self._duration_ms > 0:
            # 播放头主体
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(progress_x, bar_area.top(), progress_x, bar_area.bottom())

            # 播放头顶部小圆点
            painter.setBrush(QColor(255, 255, 255))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(progress_x - 3, bar_area.top() - 5, 6, 6))

        # 悬停指示线
        if self._hover_x >= bar_area.left() and self._hover_x <= bar_area.right():
            painter.setPen(QPen(QColor(255, 255, 255, 60), 1))
            painter.drawLine(self._hover_x, bar_area.top(), self._hover_x, bar_area.bottom())

    # ---------- 交互 ----------
    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_x = -1
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._seek_callback or self._duration_ms <= 0:
            return

        rect = self.rect().adjusted(8, 8, -8, -8)
        bar_area = rect.adjusted(8, 6, -8, -6)
        if bar_area.width() <= 0:
            return

        x = event.position().x()
        x = max(bar_area.left(), min(bar_area.right(), x))
        progress = (x - bar_area.left()) / bar_area.width()
        position_ms = int(progress * self._duration_ms)
        self._seek_callback(position_ms)

