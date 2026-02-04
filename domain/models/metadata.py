"""
Metadata Domain Model

Represents audio file metadata extracted from files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AudioMetadata:
    """
    Metadata extracted from an audio file.
    
    Contains both technical audio properties and embedded metadata tags.
    """
    
    # Database ID linkage
    id: Optional[int] = None
    
    # Technical properties
    duration: float = 0.0  # seconds
    sample_rate: int = 44100
    bit_depth: int = 16
    channels: int = 2
    format: str = "wav"
    codec: str = ""
    bitrate: Optional[int] = None  # kbps, for compressed formats
    
    # Embedded metadata (from ID3, Vorbis comments, etc.)
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    year: Optional[int] = None
    track_number: Optional[int] = None
    comment: str = ""
    
    # Original filename (for UI display)
    original_filename: str = ""
    
    # Translated filename (after AI translation and renaming)
    translated_name: Optional[str] = None
    
    # Additional tags
    tags: List[str] = field(default_factory=list)
    
    # Raw metadata (all extracted fields)
    raw: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "format": self.format,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "year": self.year,
            "track_number": self.track_number,
            "comment": self.comment,
            "tags": self.tags.copy(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AudioMetadata:
        """Create from dictionary."""
        return cls(
            duration=data.get("duration", 0.0),
            sample_rate=data.get("sample_rate", 44100),
            bit_depth=data.get("bit_depth", 16),
            channels=data.get("channels", 2),
            format=data.get("format", "wav"),
            codec=data.get("codec", ""),
            bitrate=data.get("bitrate"),
            title=data.get("title", ""),
            artist=data.get("artist", ""),
            album=data.get("album", ""),
            genre=data.get("genre", ""),
            year=data.get("year"),
            track_number=data.get("track_number"),
            comment=data.get("comment", ""),
            tags=data.get("tags", []).copy(),
            raw=data.get("raw", {}).copy(),
        )


@dataclass
class UCSComponents:
    """
    Components of a UCS (Universal Category System) filename.
    
    UCS naming pattern: Category_Subcategory_Descriptor_Variation_Version.ext
    
    Example: Explosion_Large_Debris_01_v1.wav
    """
    
    category: str = ""
    subcategory: str = ""
    descriptor: str = ""
    variation: str = ""
    version: str = ""
    extension: str = ""
    
    # Additional metadata
    creator_id: str = ""  # Optional creator identifier
    
    @property
    def is_valid(self) -> bool:
        """Check if this is a valid UCS name."""
        return bool(self.category and self.subcategory)
    
    @property
    def full_name(self) -> str:
        """Build the full UCS filename."""
        parts = [self.category, self.subcategory]
        
        if self.descriptor:
            parts.append(self.descriptor)
        if self.variation:
            parts.append(self.variation)
        if self.version:
            parts.append(self.version)
        
        name = "_".join(parts)
        
        if self.extension:
            name += f".{self.extension}"
        
        return name
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary."""
        return {
            "category": self.category,
            "subcategory": self.subcategory,
            "descriptor": self.descriptor,
            "variation": self.variation,
            "version": self.version,
            "extension": self.extension,
            "creator_id": self.creator_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> UCSComponents:
        """Create from dictionary."""
        return cls(
            category=data.get("category", ""),
            subcategory=data.get("subcategory", ""),
            descriptor=data.get("descriptor", ""),
            variation=data.get("variation", ""),
            version=data.get("version", ""),
            extension=data.get("extension", ""),
            creator_id=data.get("creator_id", ""),
        )
    
    def __repr__(self) -> str:
        return f"UCSComponents({self.full_name})"


# Common UCS categories
UCS_CATEGORIES = [
    "Ambience",
    "Animals",
    "Cartoon",
    "Crowds",
    "Destruction",
    "Doors",
    "Electronics",
    "Explosion",
    "Fire",
    "Foley",
    "Footsteps",
    "Household",
    "Human",
    "Impacts",
    "Industrial",
    "Machines",
    "Materials",
    "Movement",
    "Music",
    "Nature",
    "Office",
    "Science Fiction",
    "Sports",
    "Technology",
    "Tools",
    "Transportation",
    "UI",
    "Vehicles",
    "Water",
    "Weapons",
    "Weather",
    "Whoosh",
]
