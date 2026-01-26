"""
Freesound UI Components

GTK4 + Libadwaita views for Freesound integration.
"""

from .search_view import FreesoundSearchView
from .results_view import FreesoundResultsView
from .sound_card import FreesoundSoundCard
from .sound_detail import FreesoundSoundDetail
from .download_queue import FreesoundDownloadQueue
from .license_dialog import LicenseConfirmDialog

__all__ = [
    'FreesoundSearchView',
    'FreesoundResultsView',
    'FreesoundSoundCard',
    'FreesoundSoundDetail',
    'FreesoundDownloadQueue',
    'LicenseConfirmDialog',
]
