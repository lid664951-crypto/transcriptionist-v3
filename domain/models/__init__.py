"""
Domain Models Module

Contains all domain models for Transcriptionist v3.
"""

from .audio_file import AudioFile
from .project import Project
from .search import (
    SearchOperator,
    FieldOperator,
    SearchTerm,
    SearchExpression,
    SearchFilters,
    SearchQuery,
    SavedSearch,
    SearchResult,
)
from .metadata import (
    AudioMetadata,
    UCSComponents,
    UCS_CATEGORIES,
)

__all__ = [
    # Audio file
    "AudioFile",
    # Project
    "Project",
    # Search
    "SearchOperator",
    "FieldOperator",
    "SearchTerm",
    "SearchExpression",
    "SearchFilters",
    "SearchQuery",
    "SavedSearch",
    "SearchResult",
    # Metadata
    "AudioMetadata",
    "UCSComponents",
    "UCS_CATEGORIES",
]
