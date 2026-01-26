"""
Audio Formats Adapter

Provides audio file format detection and metadata extraction.
Uses Mutagen library (same as Quod Libet) for metadata handling.

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
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Try to import mutagen
try:
    import mutagen
    from mutagen import File as MutagenFile
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wavpack import WavPack
    from mutagen.aiff import AIFF
    from mutagen.mp4 import MP4
    from mutagen.wave import WAVE
    MUTAGEN_AVAILABLE = True
except ImportError as e:
    MUTAGEN_AVAILABLE = False
    logger.warning(f"Mutagen not available: {e}")


# Supported audio formats
SUPPORTED_FORMATS: Set[str] = {
    '.wav', '.wave',
    '.mp3',
    '.flac',
    '.ogg', '.oga',
    '.m4a', '.mp4', '.aac',
    '.aiff', '.aif',
    '.wv',  # WavPack
}

# MIME type mappings
MIME_TYPES: Dict[str, str] = {
    '.wav': 'audio/wav',
    '.wave': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.flac': 'audio/flac',
    '.ogg': 'audio/ogg',
    '.oga': 'audio/ogg',
    '.m4a': 'audio/mp4',
    '.mp4': 'audio/mp4',
    '.aac': 'audio/aac',
    '.aiff': 'audio/aiff',
    '.aif': 'audio/aiff',
    '.wv': 'audio/x-wavpack',
}


@dataclass
class AudioMetadata:
    """Audio file metadata."""
    
    # File info
    file_path: str
    filename: str
    file_size: int
    format: str
    mime_type: str
    
    # Audio properties
    duration: float  # seconds
    sample_rate: int
    bit_depth: int
    channels: int
    bitrate: int  # kbps
    
    # Tags
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[str] = None
    track_number: Optional[int] = None
    comment: Optional[str] = None
    
    # Additional tags as dict
    extra_tags: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra_tags is None:
            self.extra_tags = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'file_path': self.file_path,
            'filename': self.filename,
            'file_size': self.file_size,
            'format': self.format,
            'mime_type': self.mime_type,
            'duration': self.duration,
            'sample_rate': self.sample_rate,
            'bit_depth': self.bit_depth,
            'channels': self.channels,
            'bitrate': self.bitrate,
            'title': self.title,
            'artist': self.artist,
            'album': self.album,
            'genre': self.genre,
            'year': self.year,
            'track_number': self.track_number,
            'comment': self.comment,
            'extra_tags': self.extra_tags,
        }


def is_supported_format(file_path: Path | str) -> bool:
    """Check if a file format is supported."""
    path = Path(file_path)
    return path.suffix.lower() in SUPPORTED_FORMATS


def get_mime_type(file_path: Path | str) -> str:
    """Get MIME type for a file."""
    path = Path(file_path)
    return MIME_TYPES.get(path.suffix.lower(), 'application/octet-stream')


def extract_metadata(file_path: Path | str) -> Optional[AudioMetadata]:
    """
    Extract metadata from an audio file.
    
    Args:
        file_path: Path to the audio file
        
    Returns:
        AudioMetadata object or None if extraction fails
    """
    if not MUTAGEN_AVAILABLE:
        logger.error("Mutagen is required for metadata extraction")
        return None
    
    path = Path(file_path)
    if not path.exists():
        logger.error(f"File not found: {path}")
        return None
    
    if not is_supported_format(path):
        logger.warning(f"Unsupported format: {path.suffix}")
        return None
    
    try:
        audio = MutagenFile(str(path), easy=True)
        if audio is None:
            # Try without easy mode
            audio = MutagenFile(str(path))
        
        if audio is None:
            logger.error(f"Could not read audio file: {path}")
            return None
        
        # Get audio info
        info = audio.info if hasattr(audio, 'info') else None
        
        # Extract basic properties
        duration = info.length if info else 0.0
        sample_rate = getattr(info, 'sample_rate', 0)
        channels = getattr(info, 'channels', 0)
        bitrate = getattr(info, 'bitrate', 0)
        
        # Bit depth varies by format
        bit_depth = _get_bit_depth(audio, info)
        
        # Extract tags
        tags = _extract_tags(audio)
        
        return AudioMetadata(
            file_path=str(path.absolute()),
            filename=path.name,
            file_size=path.stat().st_size,
            format=path.suffix.lower().lstrip('.'),
            mime_type=get_mime_type(path),
            duration=duration,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            bitrate=bitrate,
            title=tags.get('title'),
            artist=tags.get('artist'),
            album=tags.get('album'),
            genre=tags.get('genre'),
            year=tags.get('year'),
            track_number=tags.get('track_number'),
            comment=tags.get('comment'),
            extra_tags=tags.get('extra', {}),
        )
        
    except Exception as e:
        logger.error(f"Error extracting metadata from {path}: {e}")
        return None


def _get_bit_depth(audio: Any, info: Any) -> int:
    """Get bit depth from audio file."""
    # FLAC
    if hasattr(info, 'bits_per_sample'):
        return info.bits_per_sample
    
    # WAV
    if hasattr(info, 'bits_per_sample'):
        return info.bits_per_sample
    
    # AIFF
    if hasattr(info, 'bits_per_sample'):
        return info.bits_per_sample
    
    # Default for lossy formats
    return 16


def _extract_tags(audio: Any) -> Dict[str, Any]:
    """Extract tags from audio file."""
    tags = {}
    extra = {}
    
    def get_first(value):
        """Get first value from list or return value."""
        if isinstance(value, list) and value:
            return value[0]
        return value
    
    # Try easy tags first
    if hasattr(audio, 'tags') and audio.tags:
        raw_tags = audio.tags
        
        # Common tag mappings
        tag_map = {
            'title': ['title', 'TIT2', '\xa9nam'],
            'artist': ['artist', 'TPE1', '\xa9ART'],
            'album': ['album', 'TALB', '\xa9alb'],
            'genre': ['genre', 'TCON', '\xa9gen'],
            'year': ['date', 'year', 'TDRC', '\xa9day'],
            'track_number': ['tracknumber', 'TRCK', 'trkn'],
            'comment': ['comment', 'COMM', '\xa9cmt'],
        }
        
        for key, possible_tags in tag_map.items():
            for tag in possible_tags:
                if tag in raw_tags:
                    value = get_first(raw_tags[tag])
                    if value:
                        if key == 'track_number':
                            try:
                                # Handle "1/10" format
                                if isinstance(value, str) and '/' in value:
                                    value = int(value.split('/')[0])
                                elif isinstance(value, tuple):
                                    value = value[0]
                                else:
                                    value = int(value)
                            except (ValueError, TypeError):
                                value = None
                        tags[key] = value
                        break
        
        # Collect extra tags
        for tag, value in raw_tags.items():
            if tag not in sum(tag_map.values(), []):
                extra[tag] = get_first(value)
    
    tags['extra'] = extra
    return tags


def scan_directory(
    directory: Path | str,
    recursive: bool = True
) -> List[Path]:
    """
    Scan a directory for supported audio files.
    
    Args:
        directory: Directory to scan
        recursive: Whether to scan subdirectories
        
    Returns:
        List of paths to audio files
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    
    audio_files = []
    
    if recursive:
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = Path(root) / file
                if is_supported_format(file_path):
                    audio_files.append(file_path)
    else:
        for file_path in directory.iterdir():
            if file_path.is_file() and is_supported_format(file_path):
                audio_files.append(file_path)
    
    return audio_files
