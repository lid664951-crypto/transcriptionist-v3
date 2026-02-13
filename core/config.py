"""
Configuration Management Module

Provides configuration management with JSON storage for Transcriptionist v3.
Supports user preferences, application settings, and plugin configurations.

Validates: Requirements 13.1, 13.4, 13.5
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any, Optional, TypeVar, Generic
from copy import deepcopy

logger = logging.getLogger(__name__)


def get_default_scan_workers() -> int:
    """
    根据 CPU 核心数计算库扫描/元数据提取的默认并行数。
    用于软件启动时自动适配用户 CPU，无需硬编码上限。
    """
    try:
        n = cpu_count() or 4
    except Exception:
        n = 4
    # 保留 1 核给系统，上限 64，至少 1
    return max(1, min(n - 1, 64)) if n > 1 else 1


def get_default_waveform_workers() -> int:
    """根据 CPU 核心数计算波形渲染推荐线程数（默认倾向 4）。"""
    try:
        n = cpu_count() or 4
    except Exception:
        n = 4

    if n <= 1:
        return 1
    if n <= 8:
        return 4
    if n <= 16:
        return 6
    return 8


def get_recommended_indexing_cpu_processes() -> int:
    """
    根据本机 CPU 推荐 AI 索引的 CPU 预处理进程数。
    使用逻辑核心数、物理核心数（若可检测）计算，不硬编码固定值。
    策略：不超过物理核心数、不超过逻辑核一半，上限 16，至少 1。
    """
    try:
        n_logical = cpu_count() or 4
    except Exception:
        n_logical = 4
    try:
        from transcriptionist_v3.core.utils import get_physical_cpu_count
        n_physical = get_physical_cpu_count()
    except Exception:
        n_physical = None
    n_physical = n_physical or n_logical
    # 不超过物理核、不超过逻辑核一半，上限 16
    return max(1, min(n_physical, n_logical // 2, 16))


def get_recommended_indexing_chunk_size() -> int:
    """
    根据本机内存大小推荐 AI 索引的块大小（每块文件数）。
    按检测到的内存 GB 线性计算，不硬编码档位。
    公式：约 80 个文件/GB，限制在 100–3000 之间。
    """
    try:
        from transcriptionist_v3.core.utils import get_system_ram_gb
        ram_gb = get_system_ram_gb()
    except Exception:
        ram_gb = 8.0
    chunk = int(ram_gb * 80)
    return max(100, min(3000, chunk))


def get_recommended_indexing_gpu_batch_size() -> int:
    """
    根据 GPU 显存推荐索引批量大小。
    规则：vram_mb / 512，范围限制 2-16；检测失败时回退 4。
    """
    vram_mb = None

    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_mb = int(info.total / (1024 * 1024))
        pynvml.nvmlShutdown()
    except Exception:
        vram_mb = None

    if not vram_mb and sys.platform in {"win32", "linux"}:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                first = result.stdout.strip().splitlines()[0].strip()
                vram_mb = int(first)
        except Exception:
            vram_mb = None

    if vram_mb and vram_mb > 0:
        return max(2, min(16, int(vram_mb / 512)))
    return 4


def get_recommended_translate_concurrency(
    provider_id: Optional[str] = None,
    network_profile: str = "normal",
) -> int:
    """
    根据翻译服务商 + 网络环境给出推荐并发数。
    该值用于“未显式配置并发”时的默认回退，避免固定 20 导致限流。
    """
    provider = str(provider_id or "deepseek").strip().lower()
    profile = str(network_profile or "normal").strip().lower()
    profile_idx = {"normal": 0, "good": 1, "lan": 2}.get(profile, 0)

    # 与设置页提示区间保持一致，取区间低位偏中，优先稳定性
    table = {
        "deepseek": (6, 10, 14),
        "doubao": (8, 12, 16),
        "volcengine": (8, 12, 16),
        "openai": (2, 3, 4),
        "local": (12, 18, 24),
    }
    values = table.get(provider, (6, 10, 14))
    value = values[max(0, min(2, profile_idx))]
    return max(1, min(32, int(value)))


def get_recommended_translate_chunk_size(
    provider_id: Optional[str] = None,
    network_profile: str = "normal",
) -> int:
    """
    根据翻译服务商 + 网络环境给出推荐翻译批次大小。
    """
    provider = str(provider_id or "deepseek").strip().lower()
    profile = str(network_profile or "normal").strip().lower()
    profile_idx = {"normal": 0, "good": 1, "lan": 2}.get(profile, 0)

    table = {
        "openai": (20, 30, 40),
        "deepseek": (30, 40, 50),
        "doubao": (30, 45, 60),
        "volcengine": (30, 45, 60),
        "local": (40, 60, 80),
    }
    values = table.get(provider, (30, 40, 50))
    value = values[max(0, min(2, profile_idx))]
    return max(5, min(200, int(value)))

T = TypeVar('T')


# Default configuration values
DEFAULT_CONFIG = {
    # Library settings
    "library": {
        "paths": [],
        "scan_on_startup": True,
        "watch_for_changes": True,
        "supported_formats": ["wav", "flac", "mp3", "ogg", "aiff", "m4a"],
    },
    
    # UI settings
    "ui": {
        "theme": "dark",  # "light" | "dark"
        "language": "zh_CN",
        "window_width": 1200,
        "window_height": 800,
        "sidebar_width": 250,
        "show_waveform": True,
        "library_list_view_mode": "card",     # "card" | "table"
        "library_card_density": "standard",   # "standard" | "compact"
    },
    
    # Player settings
    "player": {
        "volume": 0.8,
        "gapless_playback": True,
        "auto_play_on_select": False,
    },
    
    # Search settings
    "search": {
        "max_results": 1000,
        "enable_fuzzy": True,
        "recent_searches_limit": 20,
        "library_orchestrator_mode": "lexical",  # "lexical" | "hybrid"
        "library_orchestrator_top_k": 5000,
        "library_show_observation": True,
    },
    
    # AI settings
    "ai": {
        "enabled": True,
        "translation_backend": "google",
        "auto_classify": False,
        "auto_tag": False,
        # LLM 相关
        "model_index": 0,              # 0=DeepSeek, 1=OpenAI, 2=Doubao, 3=本地模型
        "api_key": "",
        # AI 翻译模型选择
        "translation_model_type": "general",  # "general" | "hy_mt15_onnx"
        # AI 批量翻译性能设置
        "translate_chunk_size": None,  # None=按模型+网络环境动态推荐
        "translate_concurrency": None, # None=按模型+网络环境动态推荐
        "translate_network_profile": "normal",  # "normal" | "good" | "lan"
        # AI 检索性能设置（推荐值由设备检测计算，此处仅为未检测时的回退默认）
        "indexing_mode": "balanced",   # "balanced" | "performance"
        "gpu_acceleration": True,      # 统一开关：True=预处理+推理均用 GPU（ONNX+DirectML），False=均用 CPU
        "batch_size": 4,               # GPU 批次：仅当 gpu_acceleration=True 时生效；未检测显存时的回退值
        "cpu_processes": None,         # CPU 进程：None=按本机逻辑核与物理核计算推荐（GPU 关时用于并行）
        "indexing_chunk_size": None,   # 块大小：None=按本机内存 GB×80 计算推荐
        "indexing_chunk_small_threshold": 500,  # 总文件数低于此值时不拆块（100-1000）
        "indexing_memory_limit_mb": None,  # 可选：单块内存上限 MB，用于进一步约束块大小，避免百万级 OOM
        # 查询编排（M4）
        "search_orchestrator_mode": "hybrid",  # "semantic" | "lexical" | "hybrid"
        "search_orchestrator_top_k": 500,
        "search_rrf_k": 60,
        "search_rrf_lexical_weight": 1.0,
        "search_rrf_semantic_weight": 1.0,
        "search_consistency_check_enabled": True,
        "search_consistency_top_n": 20,
        # AI 音效生成（可灵）
        "audio_provider": "kling",
        "audio_access_key": "",
        "audio_secret_key": "",
        "audio_base_url": "https://api-beijing.klingai.com",
        "audio_callback_url": "",
        "audio_poll_interval": 2,
        "audio_task_timeout_seconds": 300,
    },
    
    # Performance settings
    # scan_workers: 库扫描/元数据提取并行数。None 表示“自动”（按 CPU 检测）；首次加载时若为 4 会迁移为自动检测值
    "performance": {
        "scan_workers": None,  # None = 自动根据 CPU 检测，见 get_default_scan_workers()
        "waveform_workers": None,  # None = 自动根据 CPU 检测，见 get_default_waveform_workers()
        "cache_size_mb": 256,
        "waveform_cache_enabled": True,
    },
    
    # Database settings
    "database": {
        "sqlite_filename": "transcriptionist.db",
    },

    # Backup settings
    "backup": {
        "enabled": True,
        "interval_hours": 24,
        "max_backups": 7,
    },
    
    # Project settings
    "projects_dir": "./data/projects",
}


@dataclass
class ConfigManager:
    """
    Manages application configuration with JSON storage.
    
    Features:
    - Load/save configuration from JSON files
    - Default value fallback
    - Configuration validation
    - Import/export profiles
    """
    
    config_dir: Path
    config_file: str = "config.json"
    _config: dict = field(default_factory=dict)
    _defaults: dict = field(default_factory=lambda: deepcopy(DEFAULT_CONFIG))
    _loaded: bool = False
    
    def __post_init__(self):
        """Initialize configuration after dataclass creation."""
        self.config_dir = Path(self.config_dir)
        self._config = deepcopy(self._defaults)
    
    @property
    def config_path(self) -> Path:
        """Get the full path to the configuration file."""
        return self.config_dir / self.config_file
    
    def load(self) -> bool:
        """
        Load configuration from file.
        
        Returns:
            bool: True if loaded successfully, False otherwise.
        """
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                
                # Merge with defaults (loaded values override defaults)
                self._config = self._merge_config(self._defaults, loaded)
                dirty = False

                # 迁移：旧版默认 4 改为 None，表示“自动根据 CPU”
                perf = self._config.get("performance") or {}
                if perf.get("scan_workers") == 4:
                    self._config.setdefault("performance", {})["scan_workers"] = None
                    dirty = True

                # 迁移：翻译性能默认值从固定写死改为动态推荐（仅迁移旧默认，不覆盖用户自定义）
                ai_cfg = self._config.get("ai") or {}
                profile = str(ai_cfg.get("translate_network_profile") or "normal")
                model_index = int(ai_cfg.get("model_index") or 0)
                provider_map = {0: "deepseek", 1: "openai", 2: "doubao", 3: "local"}
                provider = provider_map.get(model_index, "deepseek")

                raw_chunk = ai_cfg.get("translate_chunk_size", None)
                raw_chunk_int = None
                try:
                    raw_chunk_int = int(raw_chunk)
                except Exception:
                    raw_chunk_int = None
                if raw_chunk in (None, "") or raw_chunk_int == 40:
                    self._config.setdefault("ai", {})["translate_chunk_size"] = get_recommended_translate_chunk_size(provider, profile)
                    dirty = True

                raw_conc = ai_cfg.get("translate_concurrency", None)
                raw_conc_int = None
                try:
                    raw_conc_int = int(raw_conc)
                except Exception:
                    raw_conc_int = None
                if raw_conc in (None, "") or raw_conc_int == 20:
                    self._config.setdefault("ai", {})["translate_concurrency"] = get_recommended_translate_concurrency(provider, profile)
                    dirty = True

                # 迁移：索引 GPU 批量旧默认 4 改为“按显存推荐”（仅未自定义场景）
                if ai_cfg.get("batch_size", None) in (None, 4):
                    rec_batch = get_recommended_indexing_gpu_batch_size()
                    self._config.setdefault("ai", {})["batch_size"] = rec_batch
                    dirty = True

                if dirty:
                    self.save()
                logger.info(f"Configuration loaded from {self.config_path}")
            else:
                # Use defaults and save them
                self._config = deepcopy(self._defaults)
                self.save()
                logger.info("Using default configuration")
            
            self._loaded = True
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid configuration file: {e}")
            # Fall back to defaults
            self._config = deepcopy(self._defaults)
            self._loaded = True
            return False
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            self._config = deepcopy(self._defaults)
            self._loaded = True
            return False
    
    def save(self) -> bool:
        """
        Save configuration to file.
        
        Returns:
            bool: True if saved successfully.
        """
        try:
            # 确保配置目录存在
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            # 写入配置文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            
            # 验证文件是否真的写入了（检查文件是否存在且有内容）
            if self.config_path.exists() and self.config_path.stat().st_size > 0:
                logger.info(f"Configuration saved successfully to {self.config_path}")
                return True
            else:
                logger.error(f"Configuration file was not created or is empty: {self.config_path}")
                return False
            
        except PermissionError as e:
            logger.error(f"Permission denied saving configuration to {self.config_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.config_path}: {e}", exc_info=True)
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.
        
        Args:
            key: Configuration key (e.g., "ui.theme", "player.volume")
            default: Default value if key not found
            
        Returns:
            The configuration value or default.
        """
        if not self._loaded:
            self.load()
        
        parts = key.split('.')
        value = self._config
        
        try:
            for part in parts:
                value = value[part]
            # 库扫描并行数：None 表示“自动”，返回 CPU 检测值
            if key == "performance.scan_workers" and value is None:
                return get_default_scan_workers()
            if key == "performance.waveform_workers" and value is None:
                return get_default_waveform_workers()
            return value
        except (KeyError, TypeError):
            return default
    
    def get_raw(self, key: str, default: Any = None) -> Any:
        """返回配置原始存储值，不做「自动」等替换（如 performance.scan_workers 的 None）。"""
        if not self._loaded:
            self.load()
        parts = key.split('.')
        value = self._config
        try:
            for part in parts:
                value = value[part]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """
        Set a configuration value using dot notation.
        
        Args:
            key: Configuration key (e.g., "ui.theme")
            value: Value to set
            save: Whether to save immediately
        """
        if not self._loaded:
            self.load()
        
        parts = key.split('.')
        config = self._config
        
        # Navigate to the parent
        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            config = config[part]
        
        # Set the value
        config[parts[-1]] = value
        
        if save:
            self.save()
    
    def reset(self, key: Optional[str] = None) -> None:
        """
        Reset configuration to defaults.
        
        Args:
            key: Specific key to reset, or None to reset all.
        """
        if key is None:
            self._config = deepcopy(self._defaults)
        else:
            default_value = self._get_default(key)
            if default_value is not None:
                self.set(key, default_value, save=False)
        
        self.save()
    
    def _get_default(self, key: str) -> Any:
        """Get the default value for a key."""
        parts = key.split('.')
        value = self._defaults
        
        try:
            for part in parts:
                value = value[part]
            return deepcopy(value)
        except (KeyError, TypeError):
            return None
    
    def _merge_config(self, defaults: dict, loaded: dict) -> dict:
        """
        Recursively merge loaded config with defaults.
        
        Args:
            defaults: Default configuration
            loaded: Loaded configuration
            
        Returns:
            Merged configuration
        """
        result = deepcopy(defaults)
        
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def export_profile(self, path: Path) -> bool:
        """
        Export current configuration as a profile.
        
        Args:
            path: Path to export to
            
        Returns:
            bool: True if exported successfully
        """
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"Configuration exported to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export configuration: {e}")
            return False
    
    def import_profile(self, path: Path) -> bool:
        """
        Import configuration from a profile.
        
        Args:
            path: Path to import from
            
        Returns:
            bool: True if imported successfully
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                imported = json.load(f)
            
            self._config = self._merge_config(self._defaults, imported)
            self.save()
            logger.info(f"Configuration imported from {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to import configuration: {e}")
            return False
    
    def get_all(self) -> dict:
        """Get the entire configuration dictionary."""
        if not self._loaded:
            self.load()
        return deepcopy(self._config)


# Global configuration instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """
    Get the global configuration manager.
    
    Returns:
        ConfigManager: The configuration manager instance.
    """
    global _config_manager
    
    if _config_manager is None:
        from transcriptionist_v3.runtime.runtime_config import get_config_dir
        _config_manager = ConfigManager(config_dir=get_config_dir())
        _config_manager.load()
    
    return _config_manager


def get_config(key: str, default: Any = None) -> Any:
    """
    Get a configuration value.
    
    Args:
        key: Configuration key using dot notation
        default: Default value if not found
        
    Returns:
        The configuration value
    """
    return get_config_manager().get(key, default)


def set_config(key: str, value: Any) -> None:
    """
    Set a configuration value.
    
    Args:
        key: Configuration key using dot notation
        value: Value to set
    """
    get_config_manager().set(key, value)


def get_data_dir() -> Path:
    """
    向后兼容的辅助函数。

    旧版本部分模块会从 ``transcriptionist_v3.core.config`` 导入
    ``get_data_dir``。现在数据目录的逻辑已经统一迁移到
    ``runtime.runtime_config``，这里提供一个简单的包装，避免
    打包环境下出现 ImportError。
    """
    from transcriptionist_v3.runtime.runtime_config import get_data_dir as _get_data_dir

    return _get_data_dir()


class AppConfig:
    """Static wrapper for configuration access (Backwards Compatibility / Ease of use)."""
    
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        return get_config(key, default)
        
    @staticmethod
    def set(key: str, value: Any) -> None:
        set_config(key, value)
