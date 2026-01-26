"""
Project Domain Model

Represents a project for organizing audio files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Project:
    """
    Domain model representing a project.
    
    Projects are containers for organizing audio files.
    """
    
    # Identity
    id: Optional[int] = None
    
    # Basic info
    name: str = ""
    description: str = ""
    template_name: Optional[str] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    
    # File references (IDs only, not full objects)
    file_ids: List[int] = field(default_factory=list)
    
    @property
    def file_count(self) -> int:
        """Get the number of files in this project."""
        return len(self.file_ids)
    
    def add_file(self, file_id: int) -> None:
        """Add a file to the project."""
        if file_id not in self.file_ids:
            self.file_ids.append(file_id)
    
    def remove_file(self, file_id: int) -> None:
        """Remove a file from the project."""
        if file_id in self.file_ids:
            self.file_ids.remove(file_id)
    
    def has_file(self, file_id: int) -> bool:
        """Check if a file is in the project."""
        return file_id in self.file_ids
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "template_name": self.template_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "file_ids": self.file_ids.copy(),
            "file_count": self.file_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Project:
        """Create a Project from a dictionary."""
        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])
        
        modified_at = None
        if data.get("modified_at"):
            modified_at = datetime.fromisoformat(data["modified_at"])
        
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            template_name=data.get("template_name"),
            created_at=created_at,
            modified_at=modified_at,
            file_ids=data.get("file_ids", []).copy(),
        )
    
    def __repr__(self) -> str:
        return f"Project(id={self.id}, name='{self.name}', files={self.file_count})"
