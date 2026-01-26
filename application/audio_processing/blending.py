
import numpy as np

class AudioBlender:
    """音频融合处理工具"""
    
    @staticmethod
    def smart_fade_out(audio: np.ndarray, duration_sec: float = 2.0, sample_rate: int = 32000) -> np.ndarray:
        """
        应用智能淡出
        对音频末尾 duration_sec 秒应用指数衰减
        """
        if len(audio) == 0:
            return audio
            
        fade_samples = int(duration_sec * sample_rate)
        if fade_samples > len(audio):
            fade_samples = len(audio)
            
        fade_curve = np.linspace(1.0, 0.0, fade_samples)
        # 使用指数曲线 sound more natural
        fade_curve = np.power(fade_curve, 2) 
        
        output = audio.copy()
        output[-fade_samples:] *= fade_curve
        return output

    @staticmethod
    def crossfade(audio1: np.ndarray, audio2: np.ndarray, duration_sec: float = 1.0, sample_rate: int = 32000) -> np.ndarray:
        """
        交叉淡入淡出连接两段音频
        Audio 1 [fade out]
                  +
                [fade in] Audio 2
        """
        fade_samples = int(duration_sec * sample_rate)
        
        if fade_samples == 0:
            return np.concatenate([audio1, audio2])
            
        if len(audio1) < fade_samples or len(audio2) < fade_samples:
            # 音频太短，直接拼接
            return np.concatenate([audio1, audio2])
            
        # 提取重叠部分
        overlap_len = fade_samples
        
        # Audio 1 结尾淡出
        out_part = audio1[-overlap_len:] * np.linspace(1.0, 0.0, overlap_len)
        
        # Audio 2 开头淡入
        in_part = audio2[:overlap_len] * np.linspace(0.0, 1.0, overlap_len)
        
        # 混合
        overlap = out_part + in_part
        
        # 拼接: Audio1[:-overlap] + overlap + Audio2[overlap:]
        return np.concatenate([audio1[:-overlap_len], overlap, audio2[overlap_len:]])
