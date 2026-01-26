"""
Online Resources Module

Provides integration with online sound libraries and resources.

Modules:
- freesound: Freesound.org API integration
"""

from .freesound import (
    FreesoundClient,
    FreesoundSound,
    FreesoundSearchResult,
    FreesoundSearchOptions,
    FreesoundLicense,
    LICENSE_INFO,
)

__all__ = [
    'FreesoundClient',
    'FreesoundSound',
    'FreesoundSearchResult',
    'FreesoundSearchOptions',
    'FreesoundLicense',
    'LICENSE_INFO',
]
