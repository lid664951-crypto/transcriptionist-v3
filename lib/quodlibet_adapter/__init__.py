"""
Quod Libet Adapter Module

This module provides an adapter layer to integrate Quod Libet's mature
audio management functionality into Transcriptionist v3.

Based on Quod Libet - https://github.com/quodlibet/quodlibet
Copyright (C) 2004-2025 Quod Libet contributors
Copyright (C) 2024-2026 音译家开发者 (modifications and adaptations)

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

---

Quod Libet is a GPL-licensed open source audio player with excellent
support for:
- Audio playback (GStreamer)
- Metadata extraction (Mutagen)
- Library management
- Search/query parsing
- UI components (GTK)
- File renaming and pattern matching

We adapt and reuse these components while maintaining our own architecture.
"""

import sys
from pathlib import Path

# Add quodlibet to path for imports
_ql_path = Path(__file__).parent.parent.parent.parent / "quodlibet"
if _ql_path.exists() and str(_ql_path) not in sys.path:
    sys.path.insert(0, str(_ql_path))

from .player_adapter import GStreamerPlayer, PlayerState
from .formats_adapter import (
    AudioMetadata,
    extract_metadata,
    is_supported_format,
    get_mime_type,
    scan_directory,
    SUPPORTED_FORMATS,
)
from .query_adapter import (
    QueryParser,
    ParsedQuery,
    QueryTerm,
    QueryExpression,
    QueryOperator,
    CompareOperator,
    Units,
    TIME_UNITS,
    SIZE_UNITS,
    parse_query,
    parse_time_value,
    parse_size_value,
)
from .pattern_adapter import (
    Pattern,
    FilePattern,
    UCSPattern,
    PatternFormatter,
    FilePatternFormatter,
    UCSPatternFormatter,
    PatternError,
    ParseError as PatternParseError,
)
from .rename_adapter import (
    # Path utilities
    strip_win32_incompat,
    strip_win32_incompat_from_path,
    limit_path,
    # Filters
    RenameFilter,
    SpacesToUnderscores,
    ReplaceColons,
    StripWindowsIncompat,
    StripDiacriticals,
    StripNonASCII,
    Lowercase,
    Uppercase,
    TitleCase,
    RemoveMultipleSpaces,
    RemoveParentheses,
    RemoveBrackets,
    AVAILABLE_FILTERS,
    # Filter chain
    FilterChain,
    FilterResult,
    create_default_filter_chain,
    create_strict_filter_chain,
    sanitize_filename,
)

__all__ = [
    # Player
    'GStreamerPlayer',
    'PlayerState',
    # Formats
    'AudioMetadata',
    'extract_metadata',
    'is_supported_format',
    'get_mime_type',
    'scan_directory',
    'SUPPORTED_FORMATS',
    # Query
    'QueryParser',
    'ParsedQuery',
    'QueryTerm',
    'QueryExpression',
    'QueryOperator',
    'CompareOperator',
    'Units',
    'TIME_UNITS',
    'SIZE_UNITS',
    'parse_query',
    'parse_time_value',
    'parse_size_value',
    # Pattern
    'Pattern',
    'FilePattern',
    'UCSPattern',
    'PatternFormatter',
    'FilePatternFormatter',
    'UCSPatternFormatter',
    'PatternError',
    'PatternParseError',
    # Rename - Path utilities
    'strip_win32_incompat',
    'strip_win32_incompat_from_path',
    'limit_path',
    # Rename - Filters
    'RenameFilter',
    'SpacesToUnderscores',
    'ReplaceColons',
    'StripWindowsIncompat',
    'StripDiacriticals',
    'StripNonASCII',
    'Lowercase',
    'Uppercase',
    'TitleCase',
    'RemoveMultipleSpaces',
    'RemoveParentheses',
    'RemoveBrackets',
    'AVAILABLE_FILTERS',
    # Rename - Filter chain
    'FilterChain',
    'FilterResult',
    'create_default_filter_chain',
    'create_strict_filter_chain',
    'sanitize_filename',
]


def get_player():
    """Get a GStreamer player instance."""
    return GStreamerPlayer()


def get_formats():
    """Get the formats adapter module."""
    from . import formats_adapter
    return formats_adapter


def get_query_parser():
    """Get a query parser instance."""
    return QueryParser()


def get_filter_chain(strict: bool = False):
    """
    Get a filter chain for filename processing.
    
    Args:
        strict: If True, use strict filtering (maximum compatibility)
    """
    if strict:
        return create_strict_filter_chain()
    return create_default_filter_chain()


def get_pattern(pattern_string: str):
    """
    Get a cached pattern formatter.
    
    Args:
        pattern_string: Pattern like "<category>_<name>"
    """
    return Pattern(pattern_string)


def get_file_pattern(pattern_string: str, extension: str = ''):
    """
    Get a file pattern formatter for safe filenames.
    
    Args:
        pattern_string: Pattern like "<category>/<name>"
        extension: File extension to append
    """
    return FilePattern(pattern_string, extension)


def get_ucs_pattern(pattern_string: str = None):
    """
    Get a UCS pattern formatter for sound effects naming.
    
    Args:
        pattern_string: Pattern string, or None for default UCS pattern
    """
    return UCSPattern(pattern_string)
