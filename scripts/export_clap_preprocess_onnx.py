# -*- coding: utf-8 -*-
"""
一次性导出 CLAP 音频预处理为 ONNX（波形 -> Mel），与官方 ClapFeatureExtractor 逐 op 对齐。
运行前需安装: pip install torch
运行后生成: data/models/onnx_preprocess/preprocess_audio.onnx（独立于 CLAP 模型目录，删除模型时不会被清空）
运行时无需 PyTorch，用 ONNX Runtime + DirectML 即可。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root.parent))

import numpy as np
import torch
import torch.nn as nn

# 从项目内读取配置与 mel 滤波器
from transcriptionist_v3.application.ai.clap_preprocess import (
    load_preprocessor_config,
    mel_filter_bank_slaney,
    window_function_hann,
)

NB_MAX_SAMPLES = 480000
FFT_WINDOW = 1024
HOP_LENGTH = 480
MEL_FLOOR = 1e-10
LOG_REF = 1.0
LOG_MIN = 1e-10


class ClapPreprocessModule(nn.Module):
    """波形 (B, 480000) -> log-mel (B, 64, 1001)，与 clap_preprocess 一致。"""

    def __init__(self, model_dir: Path):
        super().__init__()
        config = load_preprocessor_config(model_dir)
        sr = int(config["sampling_rate"])
        n_fft = int(config["fft_window_size"])
        hop_length = int(config.get("hop_length", 480))
        n_mels = int(config["feature_size"])
        fmin = float(config.get("frequency_min", 50))
        fmax = float(config.get("frequency_max", 14000))
        n_freq = (n_fft >> 1) + 1
        window = window_function_hann(n_fft)
        mel_filters = mel_filter_bank_slaney(n_freq, n_mels, fmin, fmax, sr)
        self.register_buffer("window", torch.from_numpy(window).float())
        self.register_buffer("mel_filters", torch.from_numpy(mel_filters.T).float())  # (64, 513)
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.center_pad = n_fft // 2

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        # waveform: (B, 480000)
        B = waveform.shape[0]
        # center pad: 512 each side -> (B, 481024)
        padded = torch.nn.functional.pad(
            waveform,
            (self.center_pad, self.center_pad),
            mode="reflect",
        )
        # STFT: (B, 513, 1001) complex -> power (B, 513, 1001)
        stft = torch.stft(
            padded,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            win_length=self.n_fft,
            window=self.window,
            center=False,
            return_complex=True,
        )
        power = (stft.real.float() ** 2 + stft.imag.float() ** 2).clamp(min=MEL_FLOOR)
        # mel: (B, 513, 1001) @ (64, 513).T -> (B, 64, 1001)
        mel = torch.matmul(self.mel_filters, power)
        mel = mel.clamp(min=MEL_FLOOR)
        # log dB: 10 * (log10(mel) - log10(ref))
        ref = max(LOG_MIN, LOG_REF)
        log_mel = 10.0 * (torch.log10(mel) - np.log10(ref))
        return log_mel.float()


def main():
    # 导出到独立目录，避免用户在「设置-删除 CLAP 模型」时误删预处理 ONNX
    model_dir = project_root / "data" / "models" / "larger-clap-general"
    onnx_dir = model_dir.parent / "onnx_preprocess"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    out_path = onnx_dir / "preprocess_audio.onnx"

    model = ClapPreprocessModule(model_dir)
    model.eval()
    dummy = torch.zeros(1, NB_MAX_SAMPLES)
    with torch.no_grad():
        torch.onnx.export(
            model,
            dummy,
            str(out_path),
            input_names=["waveform"],
            output_names=["log_mel"],
            dynamic_axes={"waveform": {0: "batch"}, "log_mel": {0: "batch"}},
            opset_version=18,
        )
    print(f"Exported: {out_path}")


if __name__ == "__main__":
    main()
