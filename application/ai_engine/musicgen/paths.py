import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def get_models_dir() -> Path:
    """
    获取 MusicGen 模型存放目录
    
    使用 runtime_config 统一管理路径，兼容开发和打包环境
    """
    try:
        # 使用 runtime_config 获取数据目录
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        data_dir = get_data_dir()
        musicgen_dir = data_dir / "models" / "musicgen"
        
        # 确保目录存在
        if not musicgen_dir.exists():
            musicgen_dir.mkdir(parents=True, exist_ok=True)
            
        return musicgen_dir
        
    except Exception as e:
        logger.error(f"Failed to resolve models dir: {e}")
        # 兜底：使用当前工作目录
        return Path.cwd() / "models" / "musicgen"
