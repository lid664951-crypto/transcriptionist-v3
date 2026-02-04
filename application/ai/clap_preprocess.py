# -*- coding: utf-8 -*-
"""
CLAP 官方对齐预处理（与 HuggingFace ClapFeatureExtractor 逐 op 一致）

纯 NumPy 实现，不依赖 PyTorch/ClapProcessor。
逻辑与 transformers.models.clap + audio_utils 一致：
- window: Hann (periodic)
- STFT: frame_length=fft_window_size, hop_length, power=2.0, center=True, pad_mode=reflect
- Mel: slaney scale + slaney norm (truncation=rand_trunc 路径)
- Log: dB, reference=1.0, min_value=1e-10
- Padding: repeatpad（短音频先 tile 再 pad 到 nb_max_samples）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LAION-CLAP 官方量化函数 (来自 training/data.py)
# ---------------------------------------------------------------------------

def int16_to_float32(x: np.ndarray) -> np.ndarray:
    """LAION-CLAP 官方: 将 int16 音频转换为 float32。"""
    return (x / 32767.0).astype(np.float32)

def float32_to_int16(x: np.ndarray) -> np.ndarray:
    """LAION-CLAP 官方: 将 float32 音频量化到 int16 范围再转回 float32。"""
    x = np.clip(x, a_min=-1.0, a_max=1.0)
    return (x * 32767.0).astype(np.int16)

def quantize_audio(x: np.ndarray) -> np.ndarray:
    """LAION-CLAP 训练时的量化步骤: float32 -> int16 -> float32。"""
    return int16_to_float32(float32_to_int16(x))

# ---------------------------------------------------------------------------
# 与 HuggingFace audio_utils 一致的工具函数
# ---------------------------------------------------------------------------


def _hertz_to_mel_slaney(freq: float | np.ndarray) -> float | np.ndarray:
    """Slaney mel scale: 3*f/200 (linear below 1kHz), 15+27*log(f/1000)/log(6.4) above."""
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = 27.0 / np.log(6.4)
    if isinstance(freq, np.ndarray):
        mels = 3.0 * freq / 200.0
        log_region = freq >= min_log_hertz
        mels[log_region] = min_log_mel + np.log(freq[log_region] / min_log_hertz) * logstep
        return mels
    if freq >= min_log_hertz:
        return min_log_mel + np.log(freq / min_log_hertz) * logstep
    return 3.0 * freq / 200.0


def _mel_to_hertz_slaney(mels: float | np.ndarray) -> float | np.ndarray:
    """Inverse Slaney mel scale."""
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = np.log(6.4) / 27.0
    if isinstance(mels, np.ndarray):
        freq = 200.0 * mels / 3.0
        log_region = mels >= min_log_mel
        freq[log_region] = min_log_hertz * np.exp(logstep * (mels[log_region] - min_log_mel))
        return freq
    if mels >= min_log_mel:
        return min_log_hertz * np.exp(logstep * (mels - min_log_mel))
    return 200.0 * mels / 3.0


def _create_triangular_filter_bank(fft_freqs: np.ndarray, filter_freqs: np.ndarray) -> np.ndarray:
    """Triangular filter bank (from transformers audio_utils)."""
    filter_diff = np.diff(filter_freqs)
    slopes = np.expand_dims(filter_freqs, 0) - np.expand_dims(fft_freqs, 1)
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    return np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))


def mel_filter_bank_slaney(
    num_frequency_bins: int,
    num_mel_filters: int,
    min_frequency: float,
    max_frequency: float,
    sampling_rate: int,
) -> np.ndarray:
    """Slaney mel filter bank (norm=slaney, mel_scale=slaney). 与 ClapFeatureExtractor mel_filters_slaney 一致。"""
    mel_min = _hertz_to_mel_slaney(min_frequency)
    mel_max = _hertz_to_mel_slaney(max_frequency)
    mel_freqs = np.linspace(mel_min, mel_max, num_mel_filters + 2)
    filter_freqs = _mel_to_hertz_slaney(mel_freqs)
    fft_freqs = np.linspace(0, sampling_rate // 2, num_frequency_bins)
    mel_filters = _create_triangular_filter_bank(fft_freqs, filter_freqs)
    enorm = 2.0 / (filter_freqs[2 : num_mel_filters + 2] - filter_freqs[:num_mel_filters])
    mel_filters *= np.expand_dims(enorm, 0)
    return mel_filters.astype(np.float32)


def window_function_hann(frame_length: int) -> np.ndarray:
    """Hann window, periodic (与 audio_utils window_function 一致)."""
    length = frame_length + 1
    window = np.hanning(length)
    window = window[:-1]
    return window.astype(np.float64)


def trim_silence_start(
    waveform: np.ndarray,
    sample_rate: int,
    window_sec: float = 0.1,
    threshold_db: float = -40,
) -> np.ndarray:
    """
    从第一个「有声音」的窗口开始截取，跳过开头静音段。
    用于 CLAP 前处理：避免前几秒静音导致只分析到很少有效内容。
    
    Args:
        waveform: 单声道 float 波形
        sample_rate: 采样率
        window_sec: 检测窗口长度（秒）
        threshold_db: 能量阈值（dB），高于此视为有声，默认 -40 dB
    
    Returns:
        从有声起点开始的波形（可能变短），若全程静音则返回原波形
    """
    waveform = np.asarray(waveform, dtype=np.float64)
    if waveform.ndim > 1:
        waveform = np.mean(waveform, axis=0)
    if len(waveform) == 0:
        return waveform
    window_samples = int(sample_rate * window_sec)
    if window_samples <= 0 or len(waveform) < window_samples:
        return waveform
    threshold_linear = 10.0 ** (threshold_db / 20.0)
    hop = max(1, window_samples // 2)
    for start in range(0, len(waveform) - window_samples + 1, hop):
        chunk = waveform[start : start + window_samples]
        rms = np.sqrt(np.mean(chunk ** 2))
        if rms > threshold_linear:
            return waveform[start:].copy()
    return waveform


def spectrogram_impl(
    waveform: np.ndarray,
    window: np.ndarray,
    frame_length: int,
    hop_length: int,
    fft_length: Optional[int] = None,
    power: float = 2.0,
    center: bool = True,
    pad_mode: str = "reflect",
    mel_filters: Optional[np.ndarray] = None,
    mel_floor: float = 1e-10,
    log_mel: str = "dB",
    reference: float = 1.0,
    min_value: float = 1e-10,
) -> np.ndarray:
    """
    与 HuggingFace audio_utils.spectrogram 一致的 STFT + mel + log。
    返回 (num_mel_filters, time) 或 (num_freq_bins, time)。
    """
    if fft_length is None:
        fft_length = frame_length
    window_length = len(window)
    if window_length != frame_length:
        raise ValueError(f"window length {window_length} != frame_length {frame_length}")

    if center:
        padding = [(int(frame_length // 2), int(frame_length // 2))]
        waveform = np.pad(waveform, padding, mode=pad_mode)

    waveform = waveform.astype(np.float64)
    window = window.astype(np.float64)
    num_frames = int(1 + np.floor((waveform.size - frame_length) / hop_length))
    num_frequency_bins = (fft_length // 2) + 1
    spec = np.empty((num_frames, num_frequency_bins), dtype=np.complex64)
    buffer = np.zeros(fft_length)
    timestep = 0
    for frame_idx in range(num_frames):
        buffer[:frame_length] = waveform[timestep : timestep + frame_length]
        buffer[:frame_length] *= window
        spec[frame_idx] = np.fft.rfft(buffer)
        timestep += hop_length

    spec = np.abs(spec, dtype=np.float64) ** power
    spec = spec.T

    if mel_filters is not None:
        spec = np.maximum(mel_floor, np.dot(mel_filters.T, spec))


    if log_mel == "dB":
        # LAION-CLAP 官方使用 torchaudio.transforms.AmplitudeToDB(top_db=None)
        # 这等价于 10 * log10(spec) 使用固定 reference=1.0
        # 不使用 np.max，保持与训练时一致
        reference = max(min_value, reference)  # reference=1.0 from caller
        spec = np.clip(spec, a_min=min_value, a_max=None)
        spec = 10.0 * (np.log10(spec) - np.log10(reference))

    return spec.astype(np.float32)


def power_to_db_impl(
    spectrogram: np.ndarray,
    reference: float = 1.0,
    min_value: float = 1e-10,
) -> np.ndarray:
    """与 audio_utils.power_to_db 一致。"""
    reference = max(min_value, reference)
    spectrogram = np.clip(spectrogram, a_min=min_value, a_max=None)
    return (10.0 * (np.log10(spectrogram) - np.log10(reference))).astype(np.float32)


# ---------------------------------------------------------------------------
# 配置与主入口
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "sampling_rate": 48000,
    "max_length_s": 10,
    "nb_max_samples": 480000,
    "fft_window_size": 1024,
    "hop_length": 480,
    "feature_size": 64,
    "frequency_min": 50,
    "frequency_max": 14000,
    "padding": "repeatpad",
    "padding_value": 0.0,
    "truncation": "rand_trunc",
}


def load_preprocessor_config(model_dir: str | Path) -> Dict[str, Any]:
    """从模型目录加载 preprocessor_config.json，缺失键用 DEFAULT_CONFIG 补全。"""
    path = Path(model_dir) / "preprocessor_config.json"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k in cfg or k in ("n_fft", "nb_frequency_bins", "chunk_length_s"):
                    if k == "n_fft":
                        cfg["fft_window_size"] = v
                    elif k == "nb_frequency_bins":
                        pass
                    elif k == "chunk_length_s":
                        cfg["max_length_s"] = v
                        cfg["nb_max_samples"] = cfg["sampling_rate"] * v
                    else:
                        cfg[k] = v
        except Exception as e:
            logger.warning(f"Failed to load preprocessor_config.json: {e}")
    cfg.setdefault("nb_max_samples", cfg["sampling_rate"] * cfg["max_length_s"])
    cfg.setdefault("nb_frequency_bins", (cfg["fft_window_size"] >> 1) + 1)
    return cfg


class CLAPPreprocessor:
    """
    与官方 ClapFeatureExtractor (truncation=rand_trunc) 逐 op 对齐的预处理器。
    无 PyTorch 依赖，可用 preprocessor_config.json 驱动。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, model_dir: Optional[str | Path] = None):
        if config is None and model_dir is not None:
            config = load_preprocessor_config(model_dir)
        self.config = config or dict(DEFAULT_CONFIG)
        self.sampling_rate = int(self.config["sampling_rate"])
        self.nb_max_samples = int(self.config["nb_max_samples"])
        self.fft_window_size = int(self.config["fft_window_size"])
        self.hop_length = int(self.config["hop_length"])
        self.feature_size = int(self.config["feature_size"])
        self.frequency_min = float(self.config.get("frequency_min", 50))
        self.frequency_max = float(self.config.get("frequency_max", 14000))
        self.padding = self.config.get("padding", "repeatpad")
        self.truncation = self.config.get("truncation", "rand_trunc")

        self.nb_frequency_bins = (self.fft_window_size >> 1) + 1
        self._window = window_function_hann(self.fft_window_size)
        self._mel_filters = mel_filter_bank_slaney(
            self.nb_frequency_bins,
            self.feature_size,
            self.frequency_min,
            self.frequency_max,
            self.sampling_rate,
        )

    def _pad_waveform(self, waveform: np.ndarray, deterministic_truncate: bool = True) -> np.ndarray:
        """所有音频均直接零填充到 nb_max_samples，不再使用 repeatpad。
        避免短文件的重复模式导致嵌入中心化（Hubness 问题）。"""
        max_length = self.nb_max_samples
        if waveform.shape[0] >= max_length:
            if self.truncation == "rand_trunc" and not deterministic_truncate:
                overflow = len(waveform) - max_length
                idx = np.random.randint(0, overflow + 1) if overflow > 0 else 0
                return waveform[idx : idx + max_length].copy()
            return waveform[:max_length].copy()
            
        # 彻底禁用 repeatpad，统一使用零填充
        waveform = np.pad(
            waveform,
            (0, max_length - waveform.shape[0]),
            mode="constant",
            constant_values=float(self.config.get("padding_value", 0.0)),
        )
        return waveform.astype(np.float64)

    def extract_mel(self, waveform: np.ndarray, deterministic_truncate: bool = True) -> np.ndarray:
        """
        波形 -> log-mel。
        注意：Xenova/larger_clap_general 的 preprocessor_config.json 中无 mean/std，
        因此不应进行额外归一化，直接输出 dB 值。
        """
        waveform = np.asarray(waveform, dtype=np.float64)
        if waveform.ndim > 1:
            waveform = np.mean(waveform, axis=0)
        waveform = self._pad_waveform(waveform, deterministic_truncate=deterministic_truncate)
        log_mel = spectrogram_impl(
            waveform,
            self._window,
            self.fft_window_size,
            self.hop_length,
            fft_length=self.fft_window_size,
            power=2.0,
            center=True,
            pad_mode="reflect",
            mel_filters=self._mel_filters,
            mel_floor=1e-10,
            log_mel="dB",
            reference=1.0,
            min_value=1e-10,
        )
        # 不进行额外归一化，此模型直接使用 dB 值
        return log_mel.astype(np.float32)



def extract_mel_from_config(waveform: np.ndarray, config: Dict[str, Any]) -> np.ndarray:
    """单次调用：用 config 构建预处理器并提取 mel。"""
    preprocessor = CLAPPreprocessor(config=config)
    return preprocessor.extract_mel(waveform)
