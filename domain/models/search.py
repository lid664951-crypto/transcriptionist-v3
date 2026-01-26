"""
Search Domain Models

Represents search queries and saved searches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class SearchOperator(Enum):
    """Boolean operators for search queries."""
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class FieldOperator(Enum):
    """Comparison operators for field searches."""
    EQUALS = "="
    NOT_EQUALS = "!="
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    CONTAINS = "~"


@dataclass
class SearchTerm:
    """A single search term."""
    value: str
    field: Optional[str] = None  # None means search all fields
    operator: FieldOperator = FieldOperator.CONTAINS
    negated: bool = False
    
    def __repr__(self) -> str:
        if self.field:
            return f"SearchTerm({self.field}{self.operator.value}{self.value})"
        return f"SearchTerm({self.value})"


@dataclass
class SearchExpression:
    """A compound search expression."""
    left: Union[SearchTerm, "SearchExpression"]
    operator: SearchOperator
    right: Union[SearchTerm, "SearchExpression"]
    
    def __repr__(self) -> str:
        return f"({self.left} {self.operator.value} {self.right})"


@dataclass
class SearchFilters:
    """Filters for search results."""
    
    # Duration filters (in seconds)
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    
    # Sample rate filter
    sample_rates: List[int] = field(default_factory=list)
    
    # Format filter
    formats: List[str] = field(default_factory=list)
    
    # Channel filter
    channels: Optional[int] = None
    
    # Tag filter
    tags: List[str] = field(default_factory=list)
    
    # Project filter
    project_id: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "min_duration": self.min_duration,
            "max_duration": self.max_duration,
            "sample_rates": self.sample_rates.copy(),
            "formats": self.formats.copy(),
            "channels": self.channels,
            "tags": self.tags.copy(),
            "project_id": self.project_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SearchFilters:
        """Create from dictionary."""
        return cls(
            min_duration=data.get("min_duration"),
            max_duration=data.get("max_duration"),
            sample_rates=data.get("sample_rates", []).copy(),
            formats=data.get("formats", []).copy(),
            channels=data.get("channels"),
            tags=data.get("tags", []).copy(),
            project_id=data.get("project_id"),
        )


@dataclass
class SearchQuery:
    """
    Represents a parsed search query.
    """
    
    # Original query string
    query_string: str = ""
    
    # Parsed AST (can be SearchTerm or SearchExpression)
    parsed: Optional[Union[SearchTerm, SearchExpression]] = None
    
    # Additional filters
    filters: SearchFilters = field(default_factory=SearchFilters)
    
    # Search options
    limit: int = 1000
    offset: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_string": self.query_string,
            "filters": self.filters.to_dict(),
            "limit": self.limit,
            "offset": self.offset,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SearchQuery:
        """Create from dictionary."""
        filters = SearchFilters.from_dict(data.get("filters", {}))
        return cls(
            query_string=data.get("query_string", ""),
            filters=filters,
            limit=data.get("limit", 1000),
            offset=data.get("offset", 0),
        )


@dataclass
class SavedSearch:
    """
    Represents a saved search query.
    """
    
    # Identity
    id: Optional[int] = None
    
    # Search info
    name: str = ""
    query: SearchQuery = field(default_factory=SearchQuery)
    
    # Usage tracking
    use_count: int = 0
    last_used_at: Optional[datetime] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "query": self.query.to_dict(),
            "use_count": self.use_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SavedSearch:
        """Create from dictionary."""
        query = SearchQuery.from_dict(data.get("query", {}))
        
        last_used_at = None
        if data.get("last_used_at"):
            last_used_at = datetime.fromisoformat(data["last_used_at"])
        
        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])
        
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            query=query,
            use_count=data.get("use_count", 0),
            last_used_at=last_used_at,
            created_at=created_at,
        )
    
    def __repr__(self) -> str:
        return f"SavedSearch(id={self.id}, name='{self.name}')"


@dataclass
class SearchResult:
    """
    Result of a search operation.
    """
    
    # Query that produced this result
    query: SearchQuery
    
    # Results
    file_ids: List[int] = field(default_factory=list)
    scores: Dict[int, float] = field(default_factory=dict)  # file_id -> relevance score
    
    # Pagination info
    total_count: int = 0
    
    # Timing
    execution_time_ms: float = 0.0
    
    @property
    def count(self) -> int:
        """Get the number of results returned."""
        return len(self.file_ids)
    
    def get_score(self, file_id: int) -> float:
        """Get the relevance score for a file."""
        return self.scores.get(file_id, 0.0)
