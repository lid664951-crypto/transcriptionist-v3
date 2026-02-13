"""
Freesound Search Service

High-level search service with bilingual support (Chinese/English),
caching, and integration with AI translation.
"""

import asyncio
import logging
import re
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from .models import (
    FreesoundSound,
    FreesoundSearchResult,
    FreesoundSearchOptions,
    FreesoundSettings,
)
from .client import FreesoundClient, FreesoundError

logger = logging.getLogger(__name__)


@dataclass
class SearchHistoryItem:
    """A search history entry."""
    
    query: str
    query_translated: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    result_count: int = 0


@dataclass
class CachedSearchResult:
    """Cached search result with expiration."""
    
    result: FreesoundSearchResult
    timestamp: datetime = field(default_factory=datetime.now)
    ttl_seconds: int = 300  # 5 minutes default
    
    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.now() > self.timestamp + timedelta(seconds=self.ttl_seconds)


# Type alias for translation function
TranslateFunc = Callable[[str], str]


class FreesoundSearchService:
    """
    High-level search service for Freesound.
    
    Features:
    - Bilingual search (Chinese input → English search → Chinese results)
    - Search result caching
    - Search history
    - Filter presets
    """
    
    # Common duration filter presets
    DURATION_PRESETS = {
        'short': (0, 5),      # 0-5 seconds
        'medium': (5, 30),    # 5-30 seconds
        'long': (30, 120),    # 30 seconds - 2 minutes
        'very_long': (120, None),  # 2+ minutes
    }
    
    # License filter presets
    LICENSE_PRESETS = {
        'commercial': ['Creative Commons 0', 'Attribution'],
        'free': ['Creative Commons 0'],
        'all': None,
    }
    
    def __init__(
        self,
        client: FreesoundClient,
        settings: FreesoundSettings,
        translate_func: Optional[TranslateFunc] = None,
    ):
        """
        Initialize search service.
        
        Args:
            client: FreesoundClient instance
            settings: Freesound settings
            translate_func: Optional function to translate text (zh→en or en→zh)
        """
        self.client = client
        self.settings = settings
        self.translate_func = translate_func
        
        self._cache: Dict[str, CachedSearchResult] = {}
        self._history: List[SearchHistoryItem] = []
        self._max_history = 50
    
    @property
    def search_history(self) -> List[SearchHistoryItem]:
        """Get search history (most recent first)."""
        return list(reversed(self._history))
    
    def clear_cache(self) -> None:
        """Clear the search cache."""
        self._cache.clear()
        logger.debug("Search cache cleared")
    
    def clear_history(self) -> None:
        """Clear search history."""
        self._history.clear()
        logger.debug("Search history cleared")
    
    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters."""
        return bool(re.search(r'[\u4e00-\u9fff]', text))
    
    def _get_cache_key(self, options: FreesoundSearchOptions) -> str:
        """Generate cache key for search options."""
        parts = [
            options.query,
            str(options.page),
            str(options.page_size),
            options.sort,
            options.build_filter_string(),
        ]
        return '|'.join(parts)
    
    async def _translate_query(self, query: str) -> str:
        """
        Translate Chinese query to English.
        
        Args:
            query: Search query (possibly Chinese)
        
        Returns:
            English query
        """
        if not self._is_chinese(query):
            return query
        
        if not self.translate_func:
            logger.warning("No translation function available, using original query")
            return query
        
        if not self.settings.auto_translate_search:
            return query
        
        try:
            translated = self.translate_func(query)
            logger.debug(f"Translated query: '{query}' → '{translated}'")
            return translated
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return query
    
    async def _translate_results(
        self,
        sounds: List[FreesoundSound],
    ) -> List[FreesoundSound]:
        """
        Translate sound names and descriptions to Chinese.
        
        Args:
            sounds: List of FreesoundSound objects
        
        Returns:
            Sounds with translated fields populated
        """
        if not self.translate_func:
            return sounds
        
        if not self.settings.auto_translate_results:
            return sounds
        
        try:
            # Batch translate names
            names = [s.name for s in sounds]
            names_text = '\n'.join(names)
            translated_names = self.translate_func(names_text)
            name_lines = translated_names.strip().split('\n')
            
            # Update sounds with translations
            for i, sound in enumerate(sounds):
                if i < len(name_lines):
                    sound.name_zh = name_lines[i].strip()
            
            return sounds
        
        except Exception as e:
            logger.error(f"Result translation failed: {e}")
            return sounds
    
    async def search(
        self,
        query: str,
        page: int = 1,
        duration_preset: Optional[str] = None,
        license_preset: Optional[str] = None,
        file_types: Optional[List[str]] = None,
        min_rating: Optional[float] = None,
        sort: str = 'score',
        use_cache: bool = True,
        group_by_pack: bool = False,
    ) -> FreesoundSearchResult:
        """
        Search for sounds with automatic translation.
        
        Args:
            query: Search query (Chinese or English)
            page: Page number
            duration_preset: Duration preset name ('short', 'medium', 'long', 'very_long')
            license_preset: License preset name ('commercial', 'free', 'all')
            file_types: List of file types to filter (e.g., ['wav', 'mp3'])
            min_rating: Minimum average rating
            sort: Sort order ('score', 'rating_desc', 'downloads_desc', 'created_desc')
            use_cache: Whether to use cached results
        
        Returns:
            FreesoundSearchResult with translated results
        """
        # Translate query if Chinese
        original_query = query
        translated_query = await self._translate_query(query)
        
        # Build search options
        options = FreesoundSearchOptions(
            query=translated_query,
            page=page,
            page_size=self.settings.page_size,
            sort=sort,
            file_types=file_types,
            min_rating=min_rating,
        )
        
        # Apply duration preset
        if duration_preset and duration_preset in self.DURATION_PRESETS:
            min_dur, max_dur = self.DURATION_PRESETS[duration_preset]
            options.duration_min = min_dur
            options.duration_max = max_dur
        
        # Apply license preset
        if license_preset and license_preset in self.LICENSE_PRESETS:
            options.license_types = self.LICENSE_PRESETS[license_preset]
        
        # Check cache
        cache_key = f"{self._get_cache_key(options)}|group_by_pack:{int(group_by_pack)}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if not cached.is_expired:
                logger.debug(f"Cache hit for query: {translated_query}")
                return cached.result
        
        # Perform search
        result = await self.client.search(translated_query, options, group_by_pack=group_by_pack)
        
        # Translate results
        if result.results:
            result.results = await self._translate_results(result.results)
        
        # Cache result
        self._cache[cache_key] = CachedSearchResult(result=result)
        
        # Add to history
        self._add_to_history(original_query, translated_query, result.count)
        
        return result
    
    async def search_with_options(
        self,
        options: FreesoundSearchOptions,
        use_cache: bool = True,
    ) -> FreesoundSearchResult:
        """
        Search with full options control.
        
        Args:
            options: FreesoundSearchOptions
            use_cache: Whether to use cached results
        
        Returns:
            FreesoundSearchResult
        """
        # Translate query if Chinese
        original_query = options.query
        options.query = await self._translate_query(options.query)
        
        # Check cache
        cache_key = self._get_cache_key(options)
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if not cached.is_expired:
                return cached.result
        
        # Perform search
        result = await self.client.search(options.query, options)
        
        # Translate results
        if result.results:
            result.results = await self._translate_results(result.results)
        
        # Cache result
        self._cache[cache_key] = CachedSearchResult(result=result)
        
        # Add to history
        self._add_to_history(original_query, options.query, result.count)
        
        return result
    
    def _add_to_history(
        self,
        query: str,
        translated_query: Optional[str],
        result_count: int,
    ) -> None:
        """Add search to history."""
        # Don't add duplicates of the most recent search
        if self._history and self._history[-1].query == query:
            return
        
        item = SearchHistoryItem(
            query=query,
            query_translated=translated_query if translated_query != query else None,
            result_count=result_count,
        )
        
        self._history.append(item)
        
        # Trim history if too long
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
    
    async def get_similar(
        self,
        sound_id: int,
        limit: int = 10,
    ) -> List[FreesoundSound]:
        """
        Get sounds similar to a given sound.
        
        Args:
            sound_id: Freesound sound ID
            limit: Maximum number of results
        
        Returns:
            List of similar sounds with translations
        """
        sounds = await self.client.get_similar_sounds(sound_id, limit)
        return await self._translate_results(sounds)
    
    async def get_sound_details(
        self,
        sound_id: int,
    ) -> FreesoundSound:
        """
        Get detailed information about a sound.
        
        Args:
            sound_id: Freesound sound ID
        
        Returns:
            FreesoundSound with full details and translation
        """
        sound = await self.client.get_sound(sound_id)
        
        # Translate single sound
        if self.translate_func and self.settings.auto_translate_results:
            try:
                sound.name_zh = self.translate_func(sound.name)
                if sound.description:
                    sound.description_zh = self.translate_func(sound.description[:500])
            except Exception as e:
                logger.error(f"Translation failed: {e}")
        
        return sound
    
    def get_popular_tags(self) -> List[str]:
        """
        Get list of popular Freesound tags.
        
        Returns:
            List of popular tag names
        """
        return [
            'impact', 'hit', 'explosion', 'whoosh', 'swoosh',
            'ambient', 'atmosphere', 'nature', 'wind', 'rain',
            'footsteps', 'door', 'button', 'click', 'beep',
            'voice', 'human', 'crowd', 'laugh', 'scream',
            'music', 'loop', 'drum', 'synth', 'bass',
            'animal', 'bird', 'dog', 'cat', 'insect',
            'water', 'fire', 'thunder', 'storm', 'ocean',
            'car', 'engine', 'traffic', 'train', 'airplane',
            'sci-fi', 'horror', 'game', 'ui', 'notification',
            'foley', 'texture', 'noise', 'glitch', 'distortion',
        ]
    
    def get_suggested_queries(self, partial: str) -> List[str]:
        """
        Get query suggestions based on partial input.
        
        Args:
            partial: Partial query string
        
        Returns:
            List of suggested queries
        """
        suggestions = []
        partial_lower = partial.lower()
        
        # Add from history
        for item in reversed(self._history):
            if partial_lower in item.query.lower():
                if item.query not in suggestions:
                    suggestions.append(item.query)
        
        # Add from popular tags
        for tag in self.get_popular_tags():
            if partial_lower in tag.lower():
                if tag not in suggestions:
                    suggestions.append(tag)
        
        return suggestions[:10]
