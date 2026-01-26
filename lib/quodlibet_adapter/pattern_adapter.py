"""
Pattern System Adapter

Provides pattern-based filename generation functionality.
Ported from Quod Libet's mature pattern system (20+ years of development).

Based on Quod Libet - https://github.com/quodlibet/quodlibet
Copyright (C) 2004-2010 Joe Wreschnig, Michael Urman
Copyright (C) 2010, 2013 Christoph Reiter
Copyright (C) 2013-2025 Nick Boultbee
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

Adapted for Transcriptionist v3 with simplified interface while
preserving the robust pattern parsing and formatting logic.

Pattern Syntax:
- <tag> - Insert tag value
- <tag|if|else> - Conditional: if tag exists, use 'if', otherwise 'else'
- <tag1||tag2> - Disjunction: use tag1 if exists, otherwise tag2
- Escape < > | with backslash: \< \> \|
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from collections import OrderedDict

logger = logging.getLogger(__name__)


# Token types (ported from Quod Libet)
OPEN = 0    # <
CLOSE = 1   # >
TEXT = 2    # plain text
COND = 3    # |
EOF = 4     # end of input
DISJ = 5    # ||


class PatternError(ValueError):
    """Error in pattern syntax."""
    pass


class ParseError(PatternError):
    """Error during pattern parsing."""
    pass


class LexerError(PatternError):
    """Error during pattern lexing."""
    pass


@dataclass
class PatternLexeme:
    """A token from the pattern lexer."""
    type: int
    lexeme: str
    
    _type_names = {
        OPEN: "OPEN",
        CLOSE: "CLOSE",
        TEXT: "TEXT",
        COND: "COND",
        EOF: "EOF",
        DISJ: "DISJ",
    }
    
    def __repr__(self):
        type_name = self._type_names.get(self.type, "UNKNOWN")
        return f"PatternLexeme(type={type_name}, lexeme={self.lexeme!r})"


class PatternLexer:
    """
    Lexer for pattern strings.
    
    Tokenizes patterns like "<artist|<album>|Unknown>" into tokens.
    """
    
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
    
    def __iter__(self):
        tokens = list(self._scan())
        tokens.append(PatternLexeme(EOF, ""))
        return iter(tokens)
    
    def _scan(self):
        """Scan the pattern and yield tokens."""
        text_buffer = []
        
        while self.pos < len(self.pattern):
            char = self.pattern[self.pos]
            
            # Handle escape sequences
            if char == '\\' and self.pos + 1 < len(self.pattern):
                next_char = self.pattern[self.pos + 1]
                if next_char in '<>|\\':
                    text_buffer.append(next_char)
                    self.pos += 2
                    continue
            
            # Handle special characters
            if char == '<':
                if text_buffer:
                    yield PatternLexeme(TEXT, ''.join(text_buffer))
                    text_buffer = []
                yield PatternLexeme(OPEN, '<')
                self.pos += 1
            elif char == '>':
                if text_buffer:
                    yield PatternLexeme(TEXT, ''.join(text_buffer))
                    text_buffer = []
                yield PatternLexeme(CLOSE, '>')
                self.pos += 1
            elif char == '|':
                if text_buffer:
                    yield PatternLexeme(TEXT, ''.join(text_buffer))
                    text_buffer = []
                # Check for ||
                if self.pos + 1 < len(self.pattern) and self.pattern[self.pos + 1] == '|':
                    yield PatternLexeme(DISJ, '||')
                    self.pos += 2
                else:
                    yield PatternLexeme(COND, '|')
                    self.pos += 1
            else:
                text_buffer.append(char)
                self.pos += 1
        
        if text_buffer:
            yield PatternLexeme(TEXT, ''.join(text_buffer))


# AST Node classes
@dataclass
class PatternNode:
    """Root pattern node containing children."""
    children: List[Any]
    
    def __repr__(self):
        return f"Pattern({', '.join(map(repr, self.children))})"


@dataclass
class TextNode:
    """Plain text node."""
    text: str
    
    def __repr__(self):
        return f'Text("{self.text}")'


@dataclass
class TagNode:
    """Tag reference node."""
    tag: str
    
    def __repr__(self):
        return f'Tag("{self.tag}")'


@dataclass
class ConditionNode:
    """Conditional node: <tag|if|else>."""
    expr: str
    ifcase: PatternNode
    elsecase: Optional[PatternNode]
    
    def __repr__(self):
        return f'Condition(expr="{self.expr}", if={self.ifcase!r}, else={self.elsecase!r})'


@dataclass
class DisjunctionNode:
    """Disjunction node: <tag1||tag2>."""
    nodelist: List[PatternNode]
    
    def __repr__(self):
        return f"Disjunction({self.nodelist!r})"


class PatternParser:
    """
    Parser for pattern strings.
    
    Builds an AST from pattern tokens.
    """
    
    def __init__(self, tokens):
        self.tokens = iter(tokens)
        self.lookahead = next(self.tokens)
        self.node = self._parse_pattern()
    
    def _parse_pattern(self) -> PatternNode:
        """Parse a pattern (sequence of text and tags)."""
        node = PatternNode(children=[])
        
        while self.lookahead.type in (OPEN, TEXT):
            la = self.lookahead
            self._match(TEXT, OPEN)
            
            if la.type == TEXT:
                node.children.append(TextNode(la.lexeme))
            elif la.type == OPEN:
                node.children.extend(self._parse_tags())
        
        return node
    
    def _parse_tags(self) -> List[Any]:
        """Parse tag expression inside < >."""
        nodes = []
        tag = self.lookahead.lexeme
        
        # Fix bad tied tags (from Quod Libet)
        if tag[:1] != "~" and "~" in tag:
            tag = "~" + tag
        
        first_node = None
        try:
            if self.lookahead.type == OPEN:
                first_node = self._parse_pattern()
            else:
                self._match(TEXT)
        except ParseError:
            # Skip to closing bracket
            while self.lookahead.type not in (CLOSE, EOF):
                self._match(self.lookahead.type)
            return nodes
        
        if self.lookahead.type == COND:
            # Conditional: <tag|if|else>
            self._match(COND)
            ifcase = self._parse_pattern()
            
            if self.lookahead.type == COND:
                self._match(COND)
                elsecase = self._parse_pattern()
            else:
                elsecase = None
            
            nodes.append(ConditionNode(tag, ifcase, elsecase))
            
            try:
                self._match(CLOSE)
            except ParseError:
                nodes.pop(-1)
                while self.lookahead.type not in (EOF, OPEN):
                    self._match(self.lookahead.type)
        
        elif self.lookahead.type == DISJ and first_node:
            # Disjunction: <tag1||tag2>
            nodelist = [first_node]
            while self.lookahead.type == DISJ:
                self._match(DISJ)
                nodelist.append(self._parse_pattern())
            
            nodes.append(DisjunctionNode(nodelist))
            
            try:
                self._match(CLOSE)
            except ParseError:
                nodes.pop(-1)
                while self.lookahead.type not in (EOF, OPEN):
                    self._match(self.lookahead.type)
        else:
            # Simple tag: <tag>
            nodes.append(TagNode(tag))
            try:
                self._match(CLOSE)
            except ParseError:
                nodes.pop(-1)
                while self.lookahead.type not in (EOF, OPEN):
                    self._match(self.lookahead.type)
        
        return nodes
    
    def _match(self, *tokens):
        """Match expected token types."""
        if tokens != (EOF,) and self.lookahead.type == EOF:
            raise ParseError("Unexpected end of pattern")
        
        try:
            if self.lookahead.type in tokens:
                self.lookahead = next(self.tokens)
            else:
                raise ParseError(
                    f"Unexpected token '{self.lookahead.lexeme}' "
                    f"(type {self.lookahead.type})"
                )
        except StopIteration:
            self.lookahead = PatternLexeme(EOF, "")


class PatternFormatter:
    """
    Formats patterns using tag values from a data source.
    
    This is the main class for applying patterns to generate filenames
    or other formatted strings.
    """
    
    def __init__(self, pattern_string: str):
        """
        Initialize with a pattern string.
        
        Args:
            pattern_string: Pattern like "<category>_<name>"
        """
        self.pattern_string = pattern_string
        self._ast = None
        self._tags: List[str] = []
        self._parse()
    
    def _parse(self):
        """Parse the pattern string into an AST."""
        try:
            lexer = PatternLexer(self.pattern_string)
            parser = PatternParser(lexer)
            self._ast = parser.node
            self._tags = self._extract_tags(self._ast)
        except Exception as e:
            logger.warning(f"Pattern parse error: {e}")
            # Fall back to literal text
            self._ast = PatternNode(children=[TextNode(self.pattern_string)])
            self._tags = []
    
    def _extract_tags(self, node) -> List[str]:
        """Extract all tag names from the AST."""
        tags = []
        
        if isinstance(node, PatternNode):
            for child in node.children:
                tags.extend(self._extract_tags(child))
        elif isinstance(node, TagNode):
            tags.append(node.tag)
        elif isinstance(node, ConditionNode):
            tags.append(node.expr)
            tags.extend(self._extract_tags(node.ifcase))
            if node.elsecase:
                tags.extend(self._extract_tags(node.elsecase))
        elif isinstance(node, DisjunctionNode):
            for n in node.nodelist:
                tags.extend(self._extract_tags(n))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return unique_tags
    
    @property
    def tags(self) -> List[str]:
        """Get list of tags used in this pattern."""
        return self._tags.copy()
    
    def format(self, data: Dict[str, Any]) -> str:
        """
        Format the pattern using the provided data.
        
        Args:
            data: Dictionary mapping tag names to values
            
        Returns:
            Formatted string
        """
        return self._format_node(self._ast, data)
    
    def _format_node(self, node, data: Dict[str, Any]) -> str:
        """Format a single AST node."""
        if isinstance(node, PatternNode):
            return ''.join(
                self._format_node(child, data) 
                for child in node.children
            )
        
        elif isinstance(node, TextNode):
            return node.text
        
        elif isinstance(node, TagNode):
            value = data.get(node.tag, '')
            return str(value) if value else ''
        
        elif isinstance(node, ConditionNode):
            # Check if the expression tag has a value
            value = data.get(node.expr)
            if value:
                return self._format_node(node.ifcase, data)
            elif node.elsecase:
                return self._format_node(node.elsecase, data)
            return ''
        
        elif isinstance(node, DisjunctionNode):
            # Return first non-empty result
            for n in node.nodelist:
                result = self._format_node(n, data)
                if result:
                    return result
            return ''
        
        return ''
    
    def __call__(self, data: Dict[str, Any]) -> str:
        """Shorthand for format()."""
        return self.format(data)


class FilePatternFormatter(PatternFormatter):
    """
    Pattern formatter specialized for generating safe filenames.
    
    Automatically sanitizes output for use as filenames.
    """
    
    # Characters not allowed in filenames (Windows)
    UNSAFE_CHARS = r'\/:*?"<>|'
    
    def __init__(self, pattern_string: str, extension: str = ''):
        """
        Initialize with a pattern string.
        
        Args:
            pattern_string: Pattern like "<category>/<name>"
            extension: File extension to append (e.g., ".wav")
        """
        super().__init__(pattern_string)
        self.extension = extension
    
    def format(self, data: Dict[str, Any]) -> str:
        """
        Format the pattern and sanitize for filename use.
        
        Args:
            data: Dictionary mapping tag names to values
            
        Returns:
            Safe filename string
        """
        result = super().format(data)
        result = self._sanitize(result)
        
        if self.extension and not result.endswith(self.extension):
            result += self.extension
        
        return result
    
    def _sanitize(self, value: str) -> str:
        """Sanitize a string for use in filenames."""
        # Replace unsafe characters with underscore
        for char in self.UNSAFE_CHARS:
            value = value.replace(char, '_')
        
        # Replace path separators in tag values (not in pattern structure)
        # This preserves intentional directory separators in the pattern
        
        # Remove leading/trailing whitespace and dots
        parts = value.split(os.sep)
        parts = [p.strip().strip('.') for p in parts]
        value = os.sep.join(parts)
        
        # Collapse multiple underscores
        while '__' in value:
            value = value.replace('__', '_')
        
        # Limit path component length
        parts = value.split(os.sep)
        parts = [p[:255] if len(p) > 255 else p for p in parts]
        value = os.sep.join(parts)
        
        return value


# Pattern cache (ported from Quod Libet)
_pattern_cache: OrderedDict[str, PatternFormatter] = OrderedDict()
_MAX_CACHE_SIZE = 100


def Pattern(pattern_string: str) -> PatternFormatter:
    """
    Get a cached PatternFormatter for the given pattern string.
    
    This function caches pattern formatters for performance.
    
    Args:
        pattern_string: Pattern like "<category>_<name>"
        
    Returns:
        PatternFormatter instance
    """
    if pattern_string not in _pattern_cache:
        while len(_pattern_cache) >= _MAX_CACHE_SIZE:
            _pattern_cache.popitem(last=False)
        _pattern_cache[pattern_string] = PatternFormatter(pattern_string)
    else:
        # Move to end (LRU)
        _pattern_cache.move_to_end(pattern_string)
    
    return _pattern_cache[pattern_string]


def FilePattern(pattern_string: str, extension: str = '') -> FilePatternFormatter:
    """
    Create a FilePatternFormatter for generating safe filenames.
    
    Args:
        pattern_string: Pattern like "<category>/<name>"
        extension: File extension to append (e.g., ".wav")
        
    Returns:
        FilePatternFormatter instance
    """
    return FilePatternFormatter(pattern_string, extension)


# UCS-specific patterns for sound effects
class UCSPatternFormatter(FilePatternFormatter):
    """
    Pattern formatter for UCS (Universal Category System) naming.
    
    Specialized for sound effects naming conventions.
    """
    
    # Standard UCS fields
    UCS_FIELDS = [
        'category', 'subcategory', 'fx_name', 'creator_id',
        'source_id', 'user_data', 'vendor_category'
    ]
    
    def __init__(self, pattern_string: str = None):
        """
        Initialize with a UCS pattern.
        
        Args:
            pattern_string: Pattern string, or None for default UCS pattern
        """
        if pattern_string is None:
            # Default UCS pattern
            pattern_string = "<category>_<subcategory>_<fx_name>"
        
        super().__init__(pattern_string, extension='')
    
    def format_ucs(
        self,
        category: str = '',
        subcategory: str = '',
        fx_name: str = '',
        creator_id: str = '',
        source_id: str = '',
        user_data: str = '',
        vendor_category: str = '',
        **extra
    ) -> str:
        """
        Format using UCS field names.
        
        Args:
            category: Main category (e.g., "AMB" for Ambience)
            subcategory: Subcategory (e.g., "City")
            fx_name: Effect name (e.g., "Traffic")
            creator_id: Creator identifier
            source_id: Source identifier
            user_data: User-defined data
            vendor_category: Vendor-specific category
            **extra: Additional fields
            
        Returns:
            Formatted UCS filename
        """
        data = {
            'category': category,
            'subcategory': subcategory,
            'fx_name': fx_name,
            'creator_id': creator_id,
            'source_id': source_id,
            'user_data': user_data,
            'vendor_category': vendor_category,
            **extra
        }
        return self.format(data)


def UCSPattern(pattern_string: str = None) -> UCSPatternFormatter:
    """
    Create a UCS pattern formatter.
    
    Args:
        pattern_string: Pattern string, or None for default UCS pattern
        
    Returns:
        UCSPatternFormatter instance
    """
    return UCSPatternFormatter(pattern_string)
