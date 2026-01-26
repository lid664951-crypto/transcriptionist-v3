"""
Internationalization (i18n) Framework

Provides multi-language support using gettext for Transcriptionist v3.
Supports Chinese, English, Japanese, Korean, French, German, and Spanish.

Validates: Requirements 9.7, 4.1
"""

from __future__ import annotations

import gettext
import locale
import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Supported languages
SUPPORTED_LANGUAGES = {
    "zh_CN": "简体中文",
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "fr_FR": "Français",
    "de_DE": "Deutsch",
    "es_ES": "Español",
}

# Default language
DEFAULT_LANGUAGE = "zh_CN"

# Global translation function
_: Callable[[str], str] = lambda s: s
ngettext: Callable[[str, str, int], str] = lambda s, p, n: s if n == 1 else p


class I18nManager:
    """
    Manages internationalization and translations.
    
    Features:
    - Load translations from .mo files
    - Switch languages at runtime
    - Fallback to default language
    - Plural form support
    """
    
    def __init__(self, locale_dir: Path, domain: str = "transcriptionist"):
        """
        Initialize the i18n manager.
        
        Args:
            locale_dir: Directory containing locale files
            domain: Translation domain name
        """
        self.locale_dir = Path(locale_dir)
        self.domain = domain
        self.current_language: str = DEFAULT_LANGUAGE
        self._translations: Optional[gettext.GNUTranslations] = None
        self._initialized = False
    
    def init(self, language: Optional[str] = None) -> bool:
        """
        Initialize translations.
        
        Args:
            language: Language code to use, or None for auto-detect
            
        Returns:
            bool: True if initialized successfully
        """
        if language is None:
            language = self._detect_system_language()
        
        return self.set_language(language)
    
    def _detect_system_language(self) -> str:
        """
        Detect the system language.
        
        Returns:
            str: Detected language code or default
        """
        try:
            # Try to get system locale
            system_locale = locale.getdefaultlocale()[0]
            
            if system_locale:
                # Check if we support this language
                if system_locale in SUPPORTED_LANGUAGES:
                    return system_locale
                
                # Try language part only (e.g., "zh" from "zh_CN")
                lang_part = system_locale.split('_')[0]
                for code in SUPPORTED_LANGUAGES:
                    if code.startswith(lang_part):
                        return code
            
        except Exception as e:
            logger.debug(f"Could not detect system language: {e}")
        
        return DEFAULT_LANGUAGE
    
    def set_language(self, language: str) -> bool:
        """
        Set the current language.
        
        Args:
            language: Language code (e.g., "zh_CN", "en_US")
            
        Returns:
            bool: True if language was set successfully
        """
        global _, ngettext
        
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unsupported language: {language}, using default")
            language = DEFAULT_LANGUAGE
        
        try:
            # Try to load translations
            locale_path = self.locale_dir / language / "LC_MESSAGES"
            mo_file = locale_path / f"{self.domain}.mo"
            
            if mo_file.exists():
                with open(mo_file, 'rb') as f:
                    self._translations = gettext.GNUTranslations(f)
                
                # Install translation functions
                _ = self._translations.gettext
                ngettext = self._translations.ngettext
                
                logger.info(f"Loaded translations for {language}")
            else:
                # No translation file, use null translations
                self._translations = gettext.NullTranslations()
                _ = self._translations.gettext
                ngettext = self._translations.ngettext
                
                logger.debug(f"No translations found for {language}, using original strings")
            
            self.current_language = language
            self._initialized = True
            
            # Update global functions
            _update_global_functions(_, ngettext)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load translations for {language}: {e}")
            
            # Fall back to null translations
            self._translations = gettext.NullTranslations()
            _ = lambda s: s
            ngettext = lambda s, p, n: s if n == 1 else p
            _update_global_functions(_, ngettext)
            
            self.current_language = language
            self._initialized = True
            return False
    
    def get_text(self, message: str) -> str:
        """
        Translate a message.
        
        Args:
            message: Message to translate
            
        Returns:
            str: Translated message
        """
        if self._translations:
            return self._translations.gettext(message)
        return message
    
    def get_ntext(self, singular: str, plural: str, n: int) -> str:
        """
        Translate a message with plural forms.
        
        Args:
            singular: Singular form
            plural: Plural form
            n: Count
            
        Returns:
            str: Translated message
        """
        if self._translations:
            return self._translations.ngettext(singular, plural, n)
        return singular if n == 1 else plural
    
    def get_available_languages(self) -> dict[str, str]:
        """
        Get available languages.
        
        Returns:
            dict: Language codes to display names
        """
        available = {}
        
        for code, name in SUPPORTED_LANGUAGES.items():
            # Check if translation exists or it's the default
            locale_path = self.locale_dir / code / "LC_MESSAGES"
            mo_file = locale_path / f"{self.domain}.mo"
            
            if mo_file.exists() or code == DEFAULT_LANGUAGE:
                available[code] = name
        
        # Always include at least the default
        if not available:
            available[DEFAULT_LANGUAGE] = SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]
        
        return available
    
    def get_language_name(self, code: str) -> str:
        """
        Get the display name for a language code.
        
        Args:
            code: Language code
            
        Returns:
            str: Display name
        """
        return SUPPORTED_LANGUAGES.get(code, code)


# Global i18n manager instance
_i18n_manager: Optional[I18nManager] = None


def _update_global_functions(gettext_func: Callable, ngettext_func: Callable) -> None:
    """Update the global translation functions."""
    global _, ngettext
    _ = gettext_func
    ngettext = ngettext_func


def get_i18n_manager() -> I18nManager:
    """
    Get the global i18n manager.
    
    Returns:
        I18nManager: The i18n manager instance
    """
    global _i18n_manager
    
    if _i18n_manager is None:
        from transcriptionist_v3.runtime.runtime_config import get_runtime_config
        config = get_runtime_config()
        _i18n_manager = I18nManager(locale_dir=config.paths.locale_dir)
    
    return _i18n_manager


def init_i18n(language: Optional[str] = None) -> bool:
    """
    Initialize internationalization.
    
    Args:
        language: Language code or None for auto-detect
        
    Returns:
        bool: True if initialized successfully
    """
    return get_i18n_manager().init(language)


def set_language(language: str) -> bool:
    """
    Set the current language.
    
    Args:
        language: Language code
        
    Returns:
        bool: True if set successfully
    """
    return get_i18n_manager().set_language(language)


def get_current_language() -> str:
    """
    Get the current language code.
    
    Returns:
        str: Current language code
    """
    return get_i18n_manager().current_language


def get_available_languages() -> dict[str, str]:
    """
    Get available languages.
    
    Returns:
        dict: Language codes to display names
    """
    return get_i18n_manager().get_available_languages()


# Convenience function for translation
def translate(message: str) -> str:
    """
    Translate a message.
    
    Args:
        message: Message to translate
        
    Returns:
        str: Translated message
    """
    return _(message)
