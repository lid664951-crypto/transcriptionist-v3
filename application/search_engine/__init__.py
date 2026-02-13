"""
Search Engine Module

Provides search functionality for the audio library.
"""

from transcriptionist_v3.application.search_engine.query_parser import (
    QueryParser,
    QueryLexer,
    ParseError,
    parse_query,
)
from transcriptionist_v3.application.search_engine.search_engine import (
    SearchEngine,
    QueryCache,
    TFIDFScorer,
)
from transcriptionist_v3.application.search_engine.query_orchestrator import (
    QueryPlan,
    QueryOrchestrator,
    QueryObservation,
    QueryOrchestratorResult,
    OrchestratedItem,
)
from transcriptionist_v3.application.search_engine.benchmark_gate_status import (
    BenchmarkGateSnapshot,
    BenchmarkGateStatusService,
)

__all__ = [
    'QueryParser',
    'QueryLexer',
    'ParseError',
    'parse_query',
    'SearchEngine',
    'QueryCache',
    'TFIDFScorer',
    'QueryPlan',
    'QueryOrchestrator',
    'QueryObservation',
    'QueryOrchestratorResult',
    'OrchestratedItem',
    'BenchmarkGateSnapshot',
    'BenchmarkGateStatusService',
]
