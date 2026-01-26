"""
Freesound Integration Module

Provides API client and models for Freesound.org integration.

Freesound.org is the world's largest Creative Commons licensed sound library
with 500,000+ sounds and 8,000,000+ users.

Features:
- Text search with filters and bilingual support
- Sound preview and download with progress tracking
- OAuth2 and Token authentication
- License tracking and attribution generation
- Rate limiting with exponential backoff

API Documentation: https://freesound.org/docs/api/
"""

from .models import (
    FreesoundSound,
    FreesoundSearchResult,
    FreesoundSearchOptions,
    FreesoundLicense,
    FreesoundPreview,
    FreesoundAnalysis,
    FreesoundDownloadItem,
    FreesoundSettings,
    LICENSE_INFO,
)
from .client import (
    FreesoundClient,
    FreesoundError,
    FreesoundAuthError,
    FreesoundRateLimitError,
    FreesoundNotFoundError,
    RateLimiter,
)
from .downloader import FreesoundDownloader, download_single
from .auth import (
    FreesoundCredentials,
    FreesoundOAuth,
    LocalOAuthServer,
    authorize_with_browser,
)
from .search_service import (
    FreesoundSearchService,
    SearchHistoryItem,
    CachedSearchResult,
)
from .license_manager import (
    LicenseManager,
    LicenseRecord,
)

__all__ = [
    # Models
    'FreesoundSound',
    'FreesoundSearchResult',
    'FreesoundSearchOptions',
    'FreesoundLicense',
    'FreesoundPreview',
    'FreesoundAnalysis',
    'FreesoundDownloadItem',
    'FreesoundSettings',
    'LICENSE_INFO',
    # Client
    'FreesoundClient',
    'FreesoundError',
    'FreesoundAuthError',
    'FreesoundRateLimitError',
    'FreesoundNotFoundError',
    'RateLimiter',
    # Downloader
    'FreesoundDownloader',
    'download_single',
    # Auth
    'FreesoundCredentials',
    'FreesoundOAuth',
    'LocalOAuthServer',
    'authorize_with_browser',
    # Search Service
    'FreesoundSearchService',
    'SearchHistoryItem',
    'CachedSearchResult',
    # License Manager
    'LicenseManager',
    'LicenseRecord',
]
