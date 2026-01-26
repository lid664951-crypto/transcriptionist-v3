"""
Search Engine Module

Implements the core search functionality including:
- Boolean operators (AND, OR, NOT)
- Field-specific searches
- Wildcard pattern matching
- Relevance scoring with TF-IDF
- Query caching
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from sqlalchemy import and_, or_, not_, func, text
from sqlalchemy.orm import Session

from transcriptionist_v3.domain.models.search import (
    SearchTerm, SearchExpression, SearchOperator, FieldOperator,
    SearchQuery, SearchResult, SavedSearch, SearchFilters
)
from transcriptionist_v3.application.search_engine.query_parser import QueryParser

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry for search results."""
    result: SearchResult
    timestamp: float
    hit_count: int = 0


class QueryCache:
    """LRU cache for search queries."""
    
    def __init__(self, max_size: int = 100, ttl_seconds: float = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, CacheEntry] = {}
    
    def _make_key(self, query: SearchQuery) -> str:
        """Create a cache key from a query."""
        key_data = f"{query.query_string}:{query.limit}:{query.offset}"
        key_data += f":{query.filters.to_dict()}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, query: SearchQuery) -> Optional[SearchResult]:
        """Get cached result if available and not expired."""
        key = self._make_key(query)
        entry = self._cache.get(key)
        
        if entry is None:
            return None
        
        # Check TTL
        if time.time() - entry.timestamp > self.ttl_seconds:
            del self._cache[key]
            return None
        
        entry.hit_count += 1
        return entry.result
    
    def put(self, query: SearchQuery, result: SearchResult) -> None:
        """Cache a search result."""
        # Evict oldest entries if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache.keys(), 
                           key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]
        
        key = self._make_key(query)
        self._cache[key] = CacheEntry(
            result=result,
            timestamp=time.time()
        )
    
    def invalidate(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class TFIDFScorer:
    """TF-IDF relevance scorer for search results."""
    
    def __init__(self):
        # Document frequency: term -> count of documents containing term
        self._df: Dict[str, int] = defaultdict(int)
        # Total document count
        self._doc_count: int = 0
        # Term frequency per document: doc_id -> term -> count
        self._tf: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    
    def index_document(self, doc_id: int, text: str) -> None:
        """Index a document for TF-IDF scoring."""
        terms = self._tokenize(text)
        term_set = set(terms)
        
        # Update document frequency
        for term in term_set:
            self._df[term] += 1
        
        # Update term frequency
        for term in terms:
            self._tf[doc_id][term] += 1
        
        self._doc_count += 1
    
    def remove_document(self, doc_id: int) -> None:
        """Remove a document from the index."""
        if doc_id not in self._tf:
            return
        
        terms = set(self._tf[doc_id].keys())
        for term in terms:
            self._df[term] -= 1
            if self._df[term] <= 0:
                del self._df[term]
        
        del self._tf[doc_id]
        self._doc_count -= 1
    
    def score(self, doc_id: int, query_terms: List[str]) -> float:
        """Calculate TF-IDF score for a document given query terms."""
        if doc_id not in self._tf or self._doc_count == 0:
            return 0.0
        
        score = 0.0
        doc_tf = self._tf[doc_id]
        
        for term in query_terms:
            tf = doc_tf.get(term, 0)
            if tf == 0:
                continue
            
            df = self._df.get(term, 0)
            if df == 0:
                continue
            
            # TF-IDF formula: tf * log(N / df)
            idf = math.log(self._doc_count / df)
            score += tf * idf
        
        return score
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into terms."""
        # Convert to lowercase and split on non-alphanumeric
        text = text.lower()
        terms = re.split(r'[^a-z0-9]+', text)
        return [t for t in terms if t and len(t) > 1]


class SearchEngine:
    """
    Main search engine class.
    
    Provides search functionality with:
    - Boolean operators (AND, OR, NOT)
    - Field-specific searches
    - Wildcard pattern matching
    - TF-IDF relevance scoring
    - Query caching
    - Saved searches
    """
    
    # Searchable fields and their database column mappings
    FIELD_MAPPINGS = {
        'filename': 'filename',
        'name': 'filename',
        'path': 'file_path',
        'duration': 'duration',
        'samplerate': 'sample_rate',
        'sample_rate': 'sample_rate',
        'bitdepth': 'bit_depth',
        'bit_depth': 'bit_depth',
        'channels': 'channels',
        'format': 'format',
        'description': 'description',
        'size': 'file_size',
        'tags': '_tags',  # Special handling
    }
    
    def __init__(self, session_factory: Callable[[], Session]):
        """
        Initialize the search engine.
        
        Args:
            session_factory: Factory function to create database sessions
        """
        self._session_factory = session_factory
        self._parser = QueryParser()
        self._cache = QueryCache()
        self._scorer = TFIDFScorer()
    
    def parse_query(self, query_string: str) -> SearchQuery:
        """Parse a query string into a SearchQuery object."""
        return self._parser.parse(query_string)
    
    async def execute(self, query: SearchQuery) -> SearchResult:
        """
        Execute a search query.
        
        Args:
            query: The search query to execute
            
        Returns:
            SearchResult with matching file IDs and scores
        """
        start_time = time.time()
        
        # Check cache first
        cached = self._cache.get(query)
        if cached is not None:
            logger.debug(f"Cache hit for query: {query.query_string}")
            return cached
        
        # Execute the search
        with self._session_factory() as session:
            file_ids, scores = self._execute_query(session, query)
        
        # Build result
        result = SearchResult(
            query=query,
            file_ids=file_ids,
            scores=scores,
            total_count=len(file_ids),
            execution_time_ms=(time.time() - start_time) * 1000
        )
        
        # Cache the result
        self._cache.put(query, result)
        
        logger.info(
            f"Search completed: {len(file_ids)} results in "
            f"{result.execution_time_ms:.2f}ms"
        )
        
        return result
    
    def execute_sync(self, query: SearchQuery) -> SearchResult:
        """Synchronous version of execute."""
        start_time = time.time()
        
        # Check cache first
        cached = self._cache.get(query)
        if cached is not None:
            logger.debug(f"Cache hit for query: {query.query_string}")
            return cached
        
        # Execute the search synchronously
        with self._session_factory() as session:
            file_ids, scores = self._execute_query(session, query)
        
        # Build result
        result = SearchResult(
            query=query,
            file_ids=file_ids,
            scores=scores,
            total_count=len(file_ids),
            execution_time_ms=(time.time() - start_time) * 1000
        )
        
        # Cache the result
        self._cache.put(query, result)
        
        logger.info(
            f"Search completed: {len(file_ids)} results in "
            f"{result.execution_time_ms:.2f}ms"
        )
        
        return result
    
    def _execute_query(
        self, 
        session: Session, 
        query: SearchQuery
    ) -> Tuple[List[int], Dict[int, float]]:
        """Execute query against database."""
        from transcriptionist_v3.infrastructure.database.models import AudioFile as AudioFileModel
        
        # Start with base query
        base_query = session.query(AudioFileModel.id, AudioFileModel.filename)
        
        # Apply parsed query conditions
        if query.parsed:
            condition = self._build_condition(query.parsed, AudioFileModel)
            if condition is not None:
                base_query = base_query.filter(condition)
        
        # Apply additional filters
        base_query = self._apply_filters(base_query, query.filters, AudioFileModel)
        
        # Execute query
        results = base_query.limit(query.limit).offset(query.offset).all()
        
        # Calculate scores
        file_ids = []
        scores = {}
        query_terms = self._extract_query_terms(query)
        
        for file_id, filename in results:
            file_ids.append(file_id)
            # Simple scoring based on filename match
            scores[file_id] = self._calculate_score(filename, query_terms)
        
        # Sort by score descending
        file_ids.sort(key=lambda fid: scores.get(fid, 0), reverse=True)
        
        return file_ids, scores
    
    def _build_condition(
        self, 
        node: Union[SearchTerm, SearchExpression],
        model: Any
    ) -> Any:
        """Build SQLAlchemy condition from parsed query."""
        if isinstance(node, SearchTerm):
            return self._build_term_condition(node, model)
        elif isinstance(node, SearchExpression):
            return self._build_expression_condition(node, model)
        return None
    
    def _build_term_condition(self, term: SearchTerm, model: Any) -> Any:
        """Build condition for a single search term."""
        if term.field:
            # Field-specific search
            condition = self._build_field_condition(term, model)
        else:
            # Full-text search across multiple fields
            condition = self._build_fulltext_condition(term, model)
        
        if term.negated and condition is not None:
            condition = not_(condition)
        
        return condition
    
    def _build_field_condition(self, term: SearchTerm, model: Any) -> Any:
        """Build condition for field-specific search."""
        field_name = term.field.lower()
        
        # Map field name to column
        column_name = self.FIELD_MAPPINGS.get(field_name)
        if not column_name:
            logger.warning(f"Unknown field: {field_name}")
            return None
        
        # Special handling for tags
        if column_name == '_tags':
            return self._build_tag_condition(term, model)
        
        column = getattr(model, column_name, None)
        if column is None:
            return None
        
        value = term.value
        
        # Build comparison based on operator
        if term.operator == FieldOperator.EQUALS:
            return column == value
        elif term.operator == FieldOperator.NOT_EQUALS:
            return column != value
        elif term.operator == FieldOperator.GREATER_THAN:
            return column > float(value)
        elif term.operator == FieldOperator.LESS_THAN:
            return column < float(value)
        elif term.operator == FieldOperator.GREATER_EQUAL:
            return column >= float(value)
        elif term.operator == FieldOperator.LESS_EQUAL:
            return column <= float(value)
        elif term.operator == FieldOperator.CONTAINS:
            # Use LIKE for contains
            pattern = f"%{value}%"
            return column.ilike(pattern)
        
        return column == value
    
    def _build_tag_condition(self, term: SearchTerm, model: Any) -> Any:
        """Build condition for tag search."""
        from transcriptionist_v3.infrastructure.database.models import AudioFileTag
        from sqlalchemy.orm import aliased
        
        value = term.value
        
        # 创建子查询：查找包含指定标签的文件 ID
        if term.operator == FieldOperator.CONTAINS:
            # 模糊匹配标签
            subquery = (
                AudioFileTag.__table__.select()
                .where(AudioFileTag.tag.ilike(f"%{value}%"))
                .with_only_columns(AudioFileTag.audio_file_id)
            )
        else:
            # 精确匹配标签
            subquery = (
                AudioFileTag.__table__.select()
                .where(AudioFileTag.tag == value)
                .with_only_columns(AudioFileTag.audio_file_id)
            )
        
        # 返回条件：文件 ID 在子查询结果中
        return model.id.in_(subquery)
    
    def _build_fulltext_condition(self, term: SearchTerm, model: Any) -> Any:
        """Build full-text search condition."""
        value = term.value
        
        # Check for wildcards
        if '*' in value or '?' in value:
            # Convert glob pattern to SQL LIKE pattern
            pattern = self._glob_to_like(value)
            return or_(
                model.filename.ilike(pattern),
                model.description.ilike(pattern) if hasattr(model, 'description') else False
            )
        else:
            # Simple contains search
            pattern = f"%{value}%"
            return or_(
                model.filename.ilike(pattern),
                model.description.ilike(pattern) if hasattr(model, 'description') else False
            )
    
    def _build_expression_condition(
        self, 
        expr: SearchExpression, 
        model: Any
    ) -> Any:
        """Build condition for compound expression."""
        left_cond = self._build_condition(expr.left, model)
        right_cond = self._build_condition(expr.right, model)
        
        if left_cond is None and right_cond is None:
            return None
        if left_cond is None:
            return right_cond
        if right_cond is None:
            return left_cond
        
        if expr.operator == SearchOperator.AND:
            return and_(left_cond, right_cond)
        elif expr.operator == SearchOperator.OR:
            return or_(left_cond, right_cond)
        elif expr.operator == SearchOperator.NOT:
            return and_(left_cond, not_(right_cond))
        
        return and_(left_cond, right_cond)
    
    def _apply_filters(
        self, 
        query: Any, 
        filters: SearchFilters, 
        model: Any
    ) -> Any:
        """Apply additional filters to query."""
        if filters.min_duration is not None:
            query = query.filter(model.duration >= filters.min_duration)
        
        if filters.max_duration is not None:
            query = query.filter(model.duration <= filters.max_duration)
        
        if filters.sample_rates:
            query = query.filter(model.sample_rate.in_(filters.sample_rates))
        
        if filters.formats:
            query = query.filter(model.format.in_(filters.formats))
        
        if filters.channels is not None:
            query = query.filter(model.channels == filters.channels)
        
        return query
    
    def _glob_to_like(self, pattern: str) -> str:
        """Convert glob pattern to SQL LIKE pattern."""
        # Escape SQL special characters
        result = pattern.replace('%', r'\%').replace('_', r'\_')
        # Convert glob wildcards
        result = result.replace('*', '%').replace('?', '_')
        return result
    
    def _extract_query_terms(self, query: SearchQuery) -> List[str]:
        """Extract search terms from query for scoring."""
        terms = []
        
        def extract(node: Union[SearchTerm, SearchExpression, None]) -> None:
            if node is None:
                return
            if isinstance(node, SearchTerm):
                if not node.field:  # Only text terms
                    terms.extend(re.split(r'\W+', node.value.lower()))
            elif isinstance(node, SearchExpression):
                extract(node.left)
                extract(node.right)
        
        extract(query.parsed)
        return [t for t in terms if t]
    
    def _calculate_score(self, filename: str, query_terms: List[str]) -> float:
        """Calculate relevance score for a file."""
        if not query_terms:
            return 1.0
        
        filename_lower = filename.lower()
        score = 0.0
        
        for term in query_terms:
            if term in filename_lower:
                # Exact match in filename
                score += 2.0
                # Bonus for word boundary match
                if re.search(rf'\b{re.escape(term)}\b', filename_lower):
                    score += 1.0
        
        return score
    
    # Saved searches functionality
    async def save_search(
        self, 
        name: str, 
        query: SearchQuery
    ) -> SavedSearch:
        """Save a search query for later use."""
        from transcriptionist_v3.infrastructure.database.models import SavedSearch as SavedSearchModel
        
        with self._session_factory() as session:
            model = SavedSearchModel(
                name=name,
                query_string=query.query_string,
                filters=query.filters.to_dict(),
                created_at=datetime.now()
            )
            session.add(model)
            session.commit()
            
            return SavedSearch(
                id=model.id,
                name=model.name,
                query=query,
                created_at=model.created_at
            )
    
    async def load_search(self, search_id: int) -> Optional[SearchQuery]:
        """Load a saved search by ID."""
        from transcriptionist_v3.infrastructure.database.models import SavedSearch as SavedSearchModel
        
        with self._session_factory() as session:
            model = session.query(SavedSearchModel).get(search_id)
            if model is None:
                return None
            
            # Update usage stats
            model.use_count += 1
            model.last_used_at = datetime.now()
            session.commit()
            
            return self.parse_query(model.query_string)
    
    def get_saved_searches(self) -> List[SavedSearch]:
        """Get all saved searches."""
        from transcriptionist_v3.infrastructure.database.models import SavedSearch as SavedSearchModel
        
        with self._session_factory() as session:
            models = session.query(SavedSearchModel).order_by(
                SavedSearchModel.use_count.desc()
            ).all()
            
            return [
                SavedSearch(
                    id=m.id,
                    name=m.name,
                    query=self.parse_query(m.query_string),
                    use_count=m.use_count,
                    last_used_at=m.last_used_at,
                    created_at=m.created_at
                )
                for m in models
            ]
    
    async def delete_saved_search(self, search_id: int) -> bool:
        """Delete a saved search."""
        from transcriptionist_v3.infrastructure.database.models import SavedSearch as SavedSearchModel
        
        with self._session_factory() as session:
            model = session.query(SavedSearchModel).get(search_id)
            if model is None:
                return False
            
            session.delete(model)
            session.commit()
            return True
    
    def invalidate_cache(self) -> None:
        """Invalidate the query cache."""
        self._cache.invalidate()
    
    def index_file(self, file_id: int, filename: str, description: str = "") -> None:
        """Index a file for TF-IDF scoring."""
        text = f"{filename} {description}"
        self._scorer.index_document(file_id, text)
    
    def remove_file_from_index(self, file_id: int) -> None:
        """Remove a file from the TF-IDF index."""
        self._scorer.remove_document(file_id)
