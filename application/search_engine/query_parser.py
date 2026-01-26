"""
Query Parser Module

Implements a recursive descent parser for search queries.
Supports boolean operators (AND, OR, NOT), field-specific searches,
wildcard patterns, and parenthesized expressions.

Query Syntax:
    # Simple text search
    explosion
    
    # Boolean operators
    explosion AND fire
    explosion OR impact
    NOT fire
    
    # Field-specific searches
    duration:>5s
    samplerate:48000
    channels:2
    format:wav
    tags:footsteps
    
    # Wildcards
    explo*
    foot?teps
    
    # Combined with parentheses
    (explosion OR impact) AND duration:>3s
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Union

from transcriptionist_v3.domain.models.search import (
    SearchTerm, SearchExpression, SearchOperator, FieldOperator, SearchQuery
)

logger = logging.getLogger(__name__)


class TokenType(Enum):
    """Token types for the lexer."""
    WORD = auto()          # Regular word
    QUOTED = auto()        # "quoted string"
    AND = auto()           # AND operator
    OR = auto()            # OR operator
    NOT = auto()           # NOT operator
    LPAREN = auto()        # (
    RPAREN = auto()        # )
    FIELD = auto()         # field:value
    EOF = auto()           # End of input


@dataclass
class Token:
    """A lexer token."""
    type: TokenType
    value: str
    position: int
    
    def __repr__(self) -> str:
        return f"Token({self.type.name}, '{self.value}')"


class QueryLexer:
    """Tokenizes search query strings."""
    
    # Field pattern: field_name:operator?value
    FIELD_PATTERN = re.compile(
        r'^([a-zA-Z_]+):(>=|<=|!=|>|<|=|~)?(.+)$'
    )
    
    def __init__(self, query: str):
        self.query = query
        self.pos = 0
        self.tokens: List[Token] = []
    
    def tokenize(self) -> List[Token]:
        """Tokenize the query string."""
        self.tokens = []
        self.pos = 0
        
        while self.pos < len(self.query):
            self._skip_whitespace()
            if self.pos >= len(self.query):
                break
            
            char = self.query[self.pos]
            
            if char == '(':
                self.tokens.append(Token(TokenType.LPAREN, '(', self.pos))
                self.pos += 1
            elif char == ')':
                self.tokens.append(Token(TokenType.RPAREN, ')', self.pos))
                self.pos += 1
            elif char == '"':
                self._read_quoted()
            else:
                self._read_word()
        
        self.tokens.append(Token(TokenType.EOF, '', self.pos))
        return self.tokens
    
    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.pos < len(self.query) and self.query[self.pos].isspace():
            self.pos += 1
    
    def _read_quoted(self) -> None:
        """Read a quoted string."""
        start = self.pos
        self.pos += 1  # Skip opening quote
        
        value = []
        while self.pos < len(self.query):
            char = self.query[self.pos]
            if char == '"':
                self.pos += 1  # Skip closing quote
                break
            elif char == '\\' and self.pos + 1 < len(self.query):
                # Escape sequence
                self.pos += 1
                value.append(self.query[self.pos])
            else:
                value.append(char)
            self.pos += 1
        
        self.tokens.append(Token(TokenType.QUOTED, ''.join(value), start))
    
    def _read_word(self) -> None:
        """Read a word or operator."""
        start = self.pos
        value = []
        
        while self.pos < len(self.query):
            char = self.query[self.pos]
            if char.isspace() or char in '()':
                break
            value.append(char)
            self.pos += 1
        
        word = ''.join(value)
        upper = word.upper()
        
        # Check for operators
        if upper == 'AND':
            self.tokens.append(Token(TokenType.AND, word, start))
        elif upper == 'OR':
            self.tokens.append(Token(TokenType.OR, word, start))
        elif upper == 'NOT':
            self.tokens.append(Token(TokenType.NOT, word, start))
        elif ':' in word:
            # Field search
            self.tokens.append(Token(TokenType.FIELD, word, start))
        else:
            self.tokens.append(Token(TokenType.WORD, word, start))


class ParseError(Exception):
    """Error during query parsing."""
    
    def __init__(self, message: str, position: int):
        super().__init__(message)
        self.position = position


class QueryParser:
    """
    Recursive descent parser for search queries.
    
    Grammar:
        query       -> expression EOF
        expression  -> term ((AND | OR) term)*
        term        -> NOT? factor
        factor      -> LPAREN expression RPAREN | atom
        atom        -> FIELD | WORD | QUOTED
    """
    
    def __init__(self):
        self.tokens: List[Token] = []
        self.pos = 0
    
    def parse(self, query_string: str) -> SearchQuery:
        """Parse a query string into a SearchQuery object."""
        if not query_string or not query_string.strip():
            return SearchQuery(query_string="")
        
        lexer = QueryLexer(query_string)
        self.tokens = lexer.tokenize()
        self.pos = 0
        
        try:
            parsed = self._parse_expression()
            
            # Ensure we consumed all tokens
            if self.current().type != TokenType.EOF:
                raise ParseError(
                    f"Unexpected token: {self.current().value}",
                    self.current().position
                )
            
            return SearchQuery(
                query_string=query_string,
                parsed=parsed
            )
        except ParseError as e:
            logger.warning(f"Parse error at position {e.position}: {e}")
            # Fall back to simple text search
            return SearchQuery(
                query_string=query_string,
                parsed=SearchTerm(value=query_string)
            )
    
    def current(self) -> Token:
        """Get the current token."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, '', len(self.tokens))
    
    def advance(self) -> Token:
        """Advance to the next token and return the current one."""
        token = self.current()
        self.pos += 1
        return token
    
    def _parse_expression(self) -> Union[SearchTerm, SearchExpression]:
        """Parse an expression (handles AND/OR)."""
        left = self._parse_term()
        
        while self.current().type in (TokenType.AND, TokenType.OR):
            op_token = self.advance()
            operator = (SearchOperator.AND if op_token.type == TokenType.AND 
                       else SearchOperator.OR)
            right = self._parse_term()
            left = SearchExpression(left=left, operator=operator, right=right)
        
        return left
    
    def _parse_term(self) -> Union[SearchTerm, SearchExpression]:
        """Parse a term (handles NOT)."""
        if self.current().type == TokenType.NOT:
            self.advance()
            factor = self._parse_factor()
            
            if isinstance(factor, SearchTerm):
                factor.negated = True
                return factor
            else:
                # Wrap expression in NOT
                return SearchExpression(
                    left=SearchTerm(value="*"),  # Match all
                    operator=SearchOperator.NOT,
                    right=factor
                )
        
        return self._parse_factor()
    
    def _parse_factor(self) -> Union[SearchTerm, SearchExpression]:
        """Parse a factor (handles parentheses)."""
        if self.current().type == TokenType.LPAREN:
            self.advance()  # Skip (
            expr = self._parse_expression()
            
            if self.current().type != TokenType.RPAREN:
                raise ParseError(
                    "Expected closing parenthesis",
                    self.current().position
                )
            self.advance()  # Skip )
            return expr
        
        return self._parse_atom()
    
    def _parse_atom(self) -> SearchTerm:
        """Parse an atom (field, word, or quoted string)."""
        token = self.current()
        
        if token.type == TokenType.FIELD:
            return self._parse_field(token)
        elif token.type in (TokenType.WORD, TokenType.QUOTED):
            self.advance()
            return SearchTerm(value=token.value)
        elif token.type == TokenType.EOF:
            raise ParseError("Unexpected end of query", token.position)
        else:
            raise ParseError(f"Unexpected token: {token.value}", token.position)
    
    def _parse_field(self, token: Token) -> SearchTerm:
        """Parse a field search (e.g., duration:>5s)."""
        self.advance()
        
        match = QueryLexer.FIELD_PATTERN.match(token.value)
        if not match:
            # Treat as regular word if pattern doesn't match
            return SearchTerm(value=token.value)
        
        field_name = match.group(1).lower()
        op_str = match.group(2) or '='
        value = match.group(3)
        
        # Map operator string to FieldOperator
        op_map = {
            '=': FieldOperator.EQUALS,
            '!=': FieldOperator.NOT_EQUALS,
            '>': FieldOperator.GREATER_THAN,
            '<': FieldOperator.LESS_THAN,
            '>=': FieldOperator.GREATER_EQUAL,
            '<=': FieldOperator.LESS_EQUAL,
            '~': FieldOperator.CONTAINS,
        }
        operator = op_map.get(op_str, FieldOperator.EQUALS)
        
        # Parse duration values (e.g., 5s, 2m, 1h)
        if field_name == 'duration':
            value = self._parse_duration(value)
        
        return SearchTerm(
            value=str(value),
            field=field_name,
            operator=operator
        )
    
    def _parse_duration(self, value: str) -> str:
        """Parse duration string to seconds."""
        value = value.strip()
        
        # Check for time units
        match = re.match(r'^(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hr|ms)?$', value, re.I)
        if match:
            num = float(match.group(1))
            unit = (match.group(2) or 's').lower()
            
            if unit in ('ms',):
                return str(num / 1000)
            elif unit in ('s', 'sec'):
                return str(num)
            elif unit in ('m', 'min'):
                return str(num * 60)
            elif unit in ('h', 'hr'):
                return str(num * 3600)
        
        return value


# Convenience function
def parse_query(query_string: str) -> SearchQuery:
    """Parse a query string into a SearchQuery object."""
    parser = QueryParser()
    return parser.parse(query_string)
