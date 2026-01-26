"""
Library Manager Module

Provides library scanning, metadata extraction, and file management.
"""

from .scanner import (
    LibraryScanner,
    ScanProgress,
    ScanResult,
    SUPPORTED_FORMATS,
    calculate_content_hash,
    calculate_content_hash_async,
)

from .metadata_extractor import (
    MetadataExtractor,
    get_metadata_extractor,
    extract_metadata,
)

__all__ = [
    # Scanner
    "LibraryScanner",
    "ScanProgress",
    "ScanResult",
    "SUPPORTED_FORMATS",
    "calculate_content_hash",
    "calculate_content_hash_async",
    # Metadata
    "MetadataExtractor",
    "get_metadata_extractor",
    "extract_metadata",
]
