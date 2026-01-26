"""
Configuration Management Module

Provides configuration management with JSON storage for Transcriptionist v3.
Supports user preferences, application settings, and plugin configurations.

Validates: Requirements 13.1, 13.4, 13.5
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, TypeVar, Generic
from copy import deepcopy

logger = logging.getLogger(__name__)

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
        "theme": "system",  # "light", "dark", "system"
        "language": "zh_CN",
        "window_width": 1200,
        "window_height": 800,
        "sidebar_width": 250,
        "show_waveform": True,
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
    },
    
    # AI settings
    "ai": {
        "enabled": True,
        "translation_backend": "google",
        "auto_classify": False,
        "auto_tag": False,
    },
    
    # Performance settings
    "performance": {
        "scan_workers": 4,
        "cache_size_mb": 256,
        "waveform_cache_enabled": True,
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
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Configuration saved to {self.config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
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


class AppConfig:
    """Static wrapper for configuration access (Backwards Compatibility / Ease of use)."""
    
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        return get_config(key, default)
        
    @staticmethod
    def set(key: str, value: Any) -> None:
        set_config(key, value)
