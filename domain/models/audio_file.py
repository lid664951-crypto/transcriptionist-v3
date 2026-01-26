"""
AudioFile Domain Model

Represents an audio file with all its properties and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AudioFile:
    """
    Domain model representing an audio file in the library.
    
    This is a pure domain object, independent of database implementation.
    """
    
    # Identity
    id: Optional[int] = None
    
    # File information
    file_path: Path = field(default_factory=Path)
    filename: str = ""
    file_size: int = 0
    content_hash: str = ""
    
    # Audio properties
    duration: float = 0.0  # seconds
    sample_rate: int = 44100
    bit_depth: int = 16
    channels: int = 2
    format: str = "wav"
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    description: str = ""
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    last_played_at: Optional[datetime] = None
    
    # Relationships
    project_ids: List[int] = field(default_factory=list)
    
    def __post_init__(self):
        """Post-initialization processing."""
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        
        if not self.filename and self.file_path:
            self.filename = self.file_path.name
    
    @property
    def extension(self) -> str:
        """Get the file extension without the dot."""
        return self.file_path.suffix.lstrip('.').lower()
    
    @property
    def duration_formatted(self) -> str:
        """Get duration as formatted string (MM:SS or HH:MM:SS)."""
        total_seconds = int(self.duration)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    
    @property
    def file_size_formatted(self) -> str:
        """Get file size as formatted string."""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    @property
    def sample_rate_formatted(self) -> str:
        """Get sample rate as formatted string (e.g., '48 kHz')."""
        if self.sample_rate >= 1000:
            return f"{self.sample_rate / 1000:.1f} kHz"
        return f"{self.sample_rate} Hz"
    
    @property
    def channels_formatted(self) -> str:
        """Get channels as formatted string."""
        if self.channels == 1:
            return "Mono"
        elif self.channels == 2:
            return "Stereo"
        else:
            return f"{self.channels} channels"
    
    def has_tag(self, tag: str) -> bool:
        """Check if the file has a specific tag."""
        return tag.lower() in [t.lower() for t in self.tags]
    
    def add_tag(self, tag: str) -> None:
        """Add a tag if not already present."""
        if not self.has_tag(tag):
            self.tags.append(tag)
    
    def remove_tag(self, tag: str) -> None:
        """Remove a tag if present."""
        self.tags = [t for t in self.tags if t.lower() != tag.lower()]
    
    def get_custom_field(self, name: str, default: Any = None) -> Any:
        """Get a custom field value."""
        return self.custom_fields.get(name, default)
    
    def set_custom_field(self, name: str, value: Any) -> None:
        """Set a custom field value."""
        self.custom_fields[name] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "file_path": str(self.file_path),
            "filename": self.filename,
            "file_size": self.file_size,
            "content_hash": self.content_hash,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "format": self.format,
            "tags": self.tags.copy(),
            "description": self.description,
            "custom_fields": self.custom_fields.copy(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "last_played_at": self.last_played_at.isoformat() if self.last_played_at else None,
            "project_ids": self.project_ids.copy(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AudioFile:
        """Create an AudioFile from a dictionary."""
        # Parse datetime fields
        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])
        
        modified_at = None
        if data.get("modified_at"):
            modified_at = datetime.fromisoformat(data["modified_at"])
        
        last_played_at = None
        if data.get("last_played_at"):
            last_played_at = datetime.fromisoformat(data["last_played_at"])
        
        return cls(
            id=data.get("id"),
            file_path=Path(data.get("file_path", "")),
            filename=data.get("filename", ""),
            file_size=data.get("file_size", 0),
            content_hash=data.get("content_hash", ""),
            duration=data.get("duration", 0.0),
            sample_rate=data.get("sample_rate", 44100),
            bit_depth=data.get("bit_depth", 16),
            channels=data.get("channels", 2),
            format=data.get("format", "wav"),
            tags=data.get("tags", []).copy(),
            description=data.get("description", ""),
            custom_fields=data.get("custom_fields", {}).copy(),
            created_at=created_at,
            modified_at=modified_at,
            last_played_at=last_played_at,
            project_ids=data.get("project_ids", []).copy(),
        )
    
    def __repr__(self) -> str:
        return f"AudioFile(id={self.id}, filename='{self.filename}')"
