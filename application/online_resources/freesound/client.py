"""
Freesound API Client

Async client for Freesound.org API v2.
Implements search, sound details, similar sounds, and download functionality.

API Documentation: https://freesound.org/docs/api/
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus
import aiohttp

from .models import (
    FreesoundSound,
    FreesoundSearchResult,
    FreesoundSearchOptions,
    FreesoundAnalysis,
)

logger = logging.getLogger(__name__)

# Freesound API base URL
BASE_URL = "https://freesound.org/apiv2"

# Default fields to request from API
DEFAULT_FIELDS = [
    'id', 'name', 'description', 'username', 'license', 'license_url',
    'duration', 'channels', 'samplerate', 'bitdepth', 'bitrate', 'filesize',
    'type', 'tags', 'avg_rating', 'num_ratings', 'num_downloads', 'created',
    'previews', 'images', 'download', 'pack', 'n_from_same_pack', 'more_from_same_pack',
]


class FreesoundError(Exception):
    """Base exception for Freesound API errors."""
    pass


class FreesoundAuthError(FreesoundError):
    """Authentication error (invalid or missing token)."""
    pass


class FreesoundRateLimitError(FreesoundError):
    """Rate limit exceeded error."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class FreesoundNotFoundError(FreesoundError):
    """Resource not found error."""
    pass


class RateLimiter:
    """
    Rate limiter with exponential backoff.
    
    Freesound API limit: 60 requests per minute.
    """
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0
        self.consecutive_errors = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Wait until a request can be made."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_request_time
            
            # Calculate wait time with exponential backoff if errors occurred
            wait_time = self.min_interval
            if self.consecutive_errors > 0:
                backoff = min(2 ** self.consecutive_errors, 60)  # Max 60 seconds
                wait_time = max(wait_time, backoff)
            
            if elapsed < wait_time:
                await asyncio.sleep(wait_time - elapsed)
            
            self.last_request_time = asyncio.get_event_loop().time()
    
    def record_success(self) -> None:
        """Record a successful request."""
        self.consecutive_errors = 0
    
    def record_error(self) -> None:
        """Record a failed request."""
        self.consecutive_errors += 1


class FreesoundClient:
    """
    Async client for Freesound API.
    
    Usage:
        async with FreesoundClient(token) as client:
            results = await client.search("wind chimes")
            for sound in results.results:
                print(sound.name)
    """
    
    def __init__(
        self,
        token: str,
        requests_per_minute: int = 60,
        timeout: float = 30.0,
    ):
        """
        Initialize Freesound client.
        
        Args:
            token: Freesound API token
            requests_per_minute: Rate limit (default 60)
            timeout: Request timeout in seconds
        """
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.rate_limiter = RateLimiter(requests_per_minute)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self) -> 'FreesoundClient':
        """Enter async context."""
        # Disable SSL verification to avoid SSLCertVerificationError on Windows
        connector = aiohttp.TCPConnector(ssl=False)
        self._session = aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        if self._session:
            await self._session.close()
            self._session = None
    
    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None:
            # Disable SSL verification to avoid SSLCertVerificationError on Windows
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        return self._session
    
    async def close(self) -> None:
        """Close the client session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make an API request with rate limiting and error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., '/search/text/')
            params: Query parameters
            **kwargs: Additional arguments for aiohttp request
        
        Returns:
            JSON response as dictionary
        
        Raises:
            FreesoundAuthError: Invalid or missing token
            FreesoundRateLimitError: Rate limit exceeded
            FreesoundNotFoundError: Resource not found
            FreesoundError: Other API errors
        """
        await self.rate_limiter.acquire()
        
        # Add token to params
        if params is None:
            params = {}
        params['token'] = self.token
        
        url = f"{BASE_URL}{endpoint}"
        
        try:
            async with self.session.request(method, url, params=params, **kwargs) as response:
                if response.status == 200:
                    self.rate_limiter.record_success()
                    return await response.json()
                
                elif response.status == 401:
                    self.rate_limiter.record_error()
                    raise FreesoundAuthError("Invalid or missing API token")
                
                elif response.status == 403:
                    self.rate_limiter.record_error()
                    raise FreesoundAuthError("Access forbidden. Check your API token permissions.")
                
                elif response.status == 404:
                    self.rate_limiter.record_error()
                    raise FreesoundNotFoundError(f"Resource not found: {endpoint}")
                
                elif response.status == 429:
                    self.rate_limiter.record_error()
                    retry_after = response.headers.get('Retry-After')
                    retry_seconds = int(retry_after) if retry_after else 60
                    raise FreesoundRateLimitError(
                        f"Rate limit exceeded. Retry after {retry_seconds} seconds.",
                        retry_after=retry_seconds
                    )
                
                else:
                    self.rate_limiter.record_error()
                    text = await response.text()
                    raise FreesoundError(f"API error {response.status}: {text}")
        
        except aiohttp.ClientError as e:
            self.rate_limiter.record_error()
            raise FreesoundError(f"Network error: {e}")
    
    async def test_connection(self) -> bool:
        """
        Test API connection and token validity.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            await self._request('GET', '/search/text/', params={
                'query': 'test',
                'page_size': '1',
            })
            return True
        except FreesoundError:
            return False
    
    async def search(
        self,
        query: str,
        options: Optional[FreesoundSearchOptions] = None,
        group_by_pack: bool = False,
    ) -> FreesoundSearchResult:
        """
        Search for sounds by text query.
        
        Args:
            query: Search query string
            options: Search options (filters, sorting, pagination)
        
        Returns:
            FreesoundSearchResult with matching sounds
        """
        if options is None:
            options = FreesoundSearchOptions(query=query)
        else:
            options.query = query
        
        params = {
            'query': options.query,
            'page': str(options.page),
            'page_size': str(options.page_size),
            'sort': options.sort,
            'fields': ','.join(DEFAULT_FIELDS),
        }

        if group_by_pack:
            params['group_by_pack'] = '1'
        
        # Add filter string if any filters specified
        filter_str = options.build_filter_string()
        if filter_str:
            params['filter'] = filter_str
        
        logger.debug(f"Searching Freesound: query='{query}', filters='{filter_str}'")
        
        data = await self._request('GET', '/search/text/', params=params)
        result = FreesoundSearchResult.from_api_response(data, options.page_size)
        result.current_page = options.page
        
        logger.info(f"Freesound search returned {result.count} results")
        return result

    async def get_pack(self, pack_id: int) -> Dict[str, Any]:
        """
        Get pack details by pack id.

        Args:
            pack_id: Freesound pack ID

        Returns:
            Pack detail dictionary from API
        """
        return await self._request('GET', f'/packs/{pack_id}/')

    async def get_pack_sounds(
        self,
        pack_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> FreesoundSearchResult:
        """
        Get sounds from a specific pack.

        Args:
            pack_id: Freesound pack ID
            page: Page number
            page_size: Results per page

        Returns:
            FreesoundSearchResult with pack sounds
        """
        params = {
            'page': str(page),
            'page_size': str(page_size),
            'fields': ','.join(DEFAULT_FIELDS),
        }

        data = await self._request('GET', f'/packs/{pack_id}/sounds/', params=params)
        result = FreesoundSearchResult.from_api_response(data, page_size)
        result.current_page = page
        return result

    async def search_packs(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        Search packs by text query.

        Args:
            query: Search query string
            page: Page number
            page_size: Results per page

        Returns:
            Raw API response dictionary for packs search
        """
        params = {
            'query': query,
            'page': str(page),
            'page_size': str(page_size),
        }
        return await self._request('GET', '/search/packs/', params=params)

    @staticmethod
    def _extract_cover_from_sound_data(sound_data: Dict[str, Any]) -> str:
        """Extract a displayable image URL from sound payload if available."""
        images = sound_data.get('images')
        if not isinstance(images, dict):
            return ""

        for key in ('waveform_m', 'waveform_l', 'spectral_m', 'spectral_l'):
            value = images.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    async def get_pack_cover(self, pack_id: int) -> str:
        """Try to derive a visual cover for pack from its first sound waveform/spectral image."""
        params = {
            'page': '1',
            'page_size': '1',
            'fields': 'id,name,images,previews',
        }
        data = await self._request('GET', f'/packs/{pack_id}/sounds/', params=params)
        results = data.get('results', [])
        if not isinstance(results, list) or not results:
            return ""
        first = results[0]
        if not isinstance(first, dict):
            return ""
        return self._extract_cover_from_sound_data(first)

    async def get_trending_packs(self, limit: int = 6) -> List[Dict[str, Any]]:
        """
        Get trending packs using live Freesound data.

        Strategy:
        - Query multiple high-frequency categories with group_by_pack search.
        - Aggregate candidate pack ids by score.
        - Fetch pack details and best-effort cover.
        """
        if limit <= 0:
            return []

        seed_queries = [
            'cinematic',
            'ambience',
            'foley',
            'impact',
            'ui',
            'horror',
        ]

        pack_candidates: Dict[int, Dict[str, Any]] = {}
        fetch_size = max(18, min(limit * 4, 40))

        for query in seed_queries:
            try:
                options = FreesoundSearchOptions(
                    query=query,
                    page=1,
                    page_size=fetch_size,
                    sort='downloads_desc',
                )
                result = await self.search(query, options, group_by_pack=True)
            except Exception as exc:
                logger.debug(f"get_trending_packs seed '{query}' failed: {exc}")
                continue

            for sound in result.results:
                pack_id = sound.pack_id
                if not pack_id:
                    continue

                score = (
                    float(sound.num_downloads or 0)
                    + float(sound.n_from_same_pack or 0) * 20.0
                    + float(sound.avg_rating or 0) * 120.0
                )

                existing = pack_candidates.get(pack_id)
                if existing is None or score > existing.get('score', 0):
                    pack_candidates[pack_id] = {
                        'pack_id': pack_id,
                        'query': query,
                        'score': score,
                    }

        if not pack_candidates:
            return []

        sorted_candidates = sorted(
            pack_candidates.values(),
            key=lambda item: float(item.get('score', 0)),
            reverse=True,
        )

        packs: List[Dict[str, Any]] = []
        max_probe = min(len(sorted_candidates), max(limit * 3, 12))
        for candidate in sorted_candidates[:max_probe]:
            pack_id = int(candidate['pack_id'])
            fallback_query = str(candidate.get('query', '')).strip()
            try:
                detail = await self.get_pack(pack_id)
            except Exception as exc:
                logger.debug(f"get_pack({pack_id}) failed: {exc}")
                continue

            title = str(detail.get('name', '') or '').strip() or f"Pack {pack_id}"
            description = str(detail.get('description', '') or '').strip()
            username = str(detail.get('username', '') or '').strip()
            num_sounds = int(detail.get('num_sounds') or detail.get('num_sounds_in_pack') or 0)

            source_url = ''
            if username:
                source_url = f"https://freesound.org/people/{username}/packs/{pack_id}/"
            elif fallback_query:
                source_url = f"https://freesound.org/search/?q={quote_plus(fallback_query)}"

            # Use image-style cover for card UI (not waveform screenshot)
            # Keep deterministic seed so the same pack keeps a stable cover.
            seed = quote_plus(f"pack-{pack_id}-{fallback_query or title}")
            cover = f"https://picsum.photos/seed/{seed}/640/360"

            packs.append(
                {
                    'pack_id': pack_id,
                    'title': title,
                    'desc': description,
                    'query': fallback_query or title,
                    'cover': cover,
                    'source_url': source_url,
                    'sounds_count': num_sounds,
                    'provider': 'freesound-live',
                }
            )

            if len(packs) >= limit:
                break

        return packs
    
    async def get_sound(self, sound_id: int) -> FreesoundSound:
        """
        Get detailed information about a specific sound.
        
        Args:
            sound_id: Freesound sound ID
        
        Returns:
            FreesoundSound with full details
        """
        params = {
            'fields': ','.join(DEFAULT_FIELDS),
        }
        
        data = await self._request('GET', f'/sounds/{sound_id}/', params=params)
        return FreesoundSound.from_api_response(data)
    
    async def get_sound_analysis(self, sound_id: int) -> FreesoundAnalysis:
        """
        Get audio analysis data for a sound.
        
        Args:
            sound_id: Freesound sound ID
        
        Returns:
            FreesoundAnalysis with audio features
        """
        data = await self._request('GET', f'/sounds/{sound_id}/analysis/')
        return FreesoundAnalysis.from_dict(data)
    
    async def get_similar_sounds(
        self,
        sound_id: int,
        limit: int = 10,
    ) -> List[FreesoundSound]:
        """
        Get sounds similar to a given sound.
        
        Args:
            sound_id: Freesound sound ID
            limit: Maximum number of similar sounds to return
        
        Returns:
            List of similar FreesoundSound objects
        """
        params = {
            'page_size': str(limit),
            'fields': ','.join(DEFAULT_FIELDS),
        }
        
        data = await self._request('GET', f'/sounds/{sound_id}/similar/', params=params)
        return [
            FreesoundSound.from_api_response(sound_data)
            for sound_data in data.get('results', [])
        ]
    
    async def get_download_url(self, sound_id: int) -> str:
        """
        Get the download URL for a sound.
        
        Note: The download URL requires the token to be passed as a parameter.
        
        Args:
            sound_id: Freesound sound ID
        
        Returns:
            Download URL with token
        """
        sound = await self.get_sound(sound_id)
        if not sound.download_url:
            raise FreesoundError(f"No download URL available for sound {sound_id}")
        
        # Append token to download URL
        separator = '&' if '?' in sound.download_url else '?'
        return f"{sound.download_url}{separator}token={self.token}"
    
    async def search_by_content(
        self,
        target_sound_id: int,
        options: Optional[FreesoundSearchOptions] = None,
    ) -> FreesoundSearchResult:
        """
        Search for sounds similar to a target sound by audio content.
        
        Args:
            target_sound_id: ID of the sound to find similar sounds for
            options: Search options (pagination)
        
        Returns:
            FreesoundSearchResult with similar sounds
        """
        if options is None:
            options = FreesoundSearchOptions(query='')
        
        params = {
            'target': str(target_sound_id),
            'page': str(options.page),
            'page_size': str(options.page_size),
            'fields': ','.join(DEFAULT_FIELDS),
        }
        
        data = await self._request('GET', '/search/content/', params=params)
        result = FreesoundSearchResult.from_api_response(data, options.page_size)
        result.current_page = options.page
        
        return result
    
    async def get_user_sounds(
        self,
        username: str,
        page: int = 1,
        page_size: int = 20,
    ) -> FreesoundSearchResult:
        """
        Get sounds uploaded by a specific user.
        
        Args:
            username: Freesound username
            page: Page number
            page_size: Results per page
        
        Returns:
            FreesoundSearchResult with user's sounds
        """
        params = {
            'page': str(page),
            'page_size': str(page_size),
            'fields': ','.join(DEFAULT_FIELDS),
        }
        
        data = await self._request('GET', f'/users/{username}/sounds/', params=params)
        result = FreesoundSearchResult.from_api_response(data, page_size)
        result.current_page = page
        
        return result
