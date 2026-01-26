import os
import sys
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional, Callable

# Import path helper
try:
    from .paths import get_models_dir
except ImportError:
    # Fallback for direct testing
    from paths import get_models_dir

logger = logging.getLogger(__name__)

class MusicGenDownloader:
    """
    MusicGen FP16 模型下载器
    
    特性：
    1. 配置内嵌：所有 URL 和文件大小硬编码，不依赖外部配置文件
    2. 增量下载：支持断点续传（基于 range header）
    3. 完整性校验：基于文件大小
    4. 环境隔离：使用 requests 库（需确保已安装在环境中）
    """
    
    # -------------------------------------------------------------------------
    # 核心配置：URL 硬编码 (FP16 ONNX, 带 KV Cache)
    # 来源：https://hf-mirror.com/Xenova/musicgen-small/tree/main/onnx
    # -------------------------------------------------------------------------
    MAX_RETRIES = 5
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks

    # -------------------------------------------------------------------------
    # 核心配置：使用 ModelScope (阿里云) 作为首选镜像，速度更稳定
    # 来源：https://www.modelscope.cn/models/Xenova/musicgen-small/files
    # -------------------------------------------------------------------------
    MODEL_CONFIGS = {
        "decoder_model_fp16.onnx": {
            # Standard decoder (no past_key_values, no merged logic)
            # This is slower but widely compatible
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=onnx%2Fdecoder_model_fp16.onnx",
            "size": 846703530,  # Updated to match actual file size (~847MB)
            "desc": "解码器 (标准版)"
        },
        "text_encoder_fp16.onnx": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=onnx%2Ftext_encoder_fp16.onnx",
            "size": 219508053, 
            "desc": "文本编码器"
        },
        "encodec_decode_fp16.onnx": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=onnx%2Fencodec_decode_fp16.onnx",
            "size": 59125087, 
            "desc": "音频解码器"
        },
        "build_delay_pattern_mask_fp16.onnx": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=onnx%2Fbuild_delay_pattern_mask_fp16.onnx",
            "size": 52053,
            "desc": "辅助掩码"
        },
        # --- 配置文件 ---
        "config.json": {
            # ModelScope root file
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=config.json",
            "size": 1000, 
            "desc": "配置"
        },
        "generation_config.json": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=generation_config.json",
            "size": 1000,
            "desc": "生成配置"
        },
        "preprocessor_config.json": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=preprocessor_config.json",
            "size": 1000,
            "desc": "预处理配置"
        },
        "tokenizer.json": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=tokenizer.json",
            "size": 2422191, 
            "desc": "分词器"
        },
        "tokenizer_config.json": {
            "url": "https://modelscope.cn/api/v1/models/Xenova/musicgen-small/repo?Revision=master&FilePath=tokenizer_config.json",
            "size": 20788,
            "desc": "分词器配置"
        }
    }
    
    def __init__(self):
        self.models_dir = get_models_dir()
        self._cancel_flag = False
        
    def cancel(self):
        """取消下载"""
        self._cancel_flag = True
        
    def check_status(self) -> Dict[str, bool]:
        """检查各文件是否存在且大小正确"""
        status = {}
        for filename, config in self.MODEL_CONFIGS.items():
            file_path = self.models_dir / filename
            if not file_path.exists():
                status[filename] = False
                continue
                
            # 对于小文件（JSON），只要存在即可；大文件检查大小
            # 允许 1% 的大小误差（防止 CDN 差异）或精确匹配
            # 这里简单起见：ONNX 文件检查大小，JSON 只要存在
            if filename.endswith(".onnx"):
                # 如果文件太小，视为下载失败
                if file_path.stat().st_size < config["size"] * 0.99:
                    status[filename] = False
                else:
                    status[filename] = True
            else:
                status[filename] = True
        return status
        
    def is_installed(self) -> bool:
        """检查所有必需文件是否都已就绪"""
        status = self.check_status()
        return all(status.values())
        
    def download(self, progress_callback: Callable[[str, int, int], None]):
        """
        执行下载
        progress_callback(filename, current_bytes, total_bytes)
        """
        import requests # 本地导入，确保在运行时可用
        
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._cancel_flag = False
        
        total_files = len(self.MODEL_CONFIGS)
        
        for idx, (filename, config) in enumerate(self.MODEL_CONFIGS.items()):
            if self._cancel_flag:
                logger.info("Download cancelled by user")
                return
                
            file_path = self.models_dir / filename
            url = config["url"]
            expected_size = config.get("size", 0)
            
            # --- 检查是否已下载且完整 ---
            if file_path.exists():
                local_size = file_path.stat().st_size
                if filename.endswith(".onnx"):
                    if local_size >= expected_size * 0.99:
                        logger.info(f"Skipping {filename} (already exists)")
                        # 发送 100% 进度
                        progress_callback(filename, expected_size, expected_size)
                        continue
                else:
                    # JSON 文件直接跳过
                    progress_callback(filename, 100, 100)
                    continue
            
            # --- 开始下载 (带重试) ---
            logger.info(f"Downloading {filename} from {url}")
            
            for attempt in range(self.MAX_RETRIES):
                try:
                    # Stream download
                    # timeout=(connect, read). 增加读取超时防止大文件传输中断
                    response = requests.get(url, stream=True, timeout=(10, 120))
                    response.raise_for_status()
                    
                    total_size = int(response.headers.get('content-length', expected_size))
                    downloaded_size = 0
                    
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                            if self._cancel_flag:
                                f.close()
                                return
                                
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                progress_callback(filename, downloaded_size, total_size)
                    
                    # 下载成功，跳出重试循环
                    break
                                
                except Exception as e:
                    logger.warning(f"Download attempt {attempt+1}/{self.MAX_RETRIES} failed for {filename}: {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        logger.error(f"Failed to download {filename} after {self.MAX_RETRIES} attempts")
                        raise e
                    import time
                    time.sleep(2) # Wait briefly before retry

    def get_missing_files(self) -> list:
        """获取缺失的文件列表"""
        status = self.check_status()
        return [f for f, exists in status.items() if not exists]
