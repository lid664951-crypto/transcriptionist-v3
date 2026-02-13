"""
Query Orchestrator

Unifies lexical/semantic retrieval and optional RRF fusion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence, Tuple


Retriever = Callable[[str, int], Sequence[Tuple[str, float]]]


@dataclass
class QueryPlan:
    mode: str = "hybrid"  # lexical | semantic | hybrid
    top_k: int = 200
    rrf_k: int = 60
    lexical_weight: float = 1.0
    semantic_weight: float = 1.0


@dataclass
class OrchestratedItem:
    key: str
    score: float
    lexical_score: float | None = None
    semantic_score: float | None = None


@dataclass
class QueryObservation:
    lexical_count: int = 0
    semantic_count: int = 0
    fused_count: int = 0
    lexical_ms: float = 0.0
    semantic_ms: float = 0.0
    fuse_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class QueryOrchestratorResult:
    items: List[OrchestratedItem] = field(default_factory=list)
    observation: QueryObservation = field(default_factory=QueryObservation)


class QueryOrchestrator:
    """统一查询编排：支持文本检索、语义检索和融合排序。"""

    def execute(
        self,
        query_text: str,
        plan: QueryPlan,
        lexical_retriever: Retriever | None = None,
        semantic_retriever: Retriever | None = None,
    ) -> QueryOrchestratorResult:
        started = time.perf_counter()
        observation = QueryObservation()

        lexical_hits: List[Tuple[str, float]] = []
        semantic_hits: List[Tuple[str, float]] = []

        normalized_mode = (plan.mode or "hybrid").strip().lower()
        enable_lexical = normalized_mode in {"lexical", "hybrid"}
        enable_semantic = normalized_mode in {"semantic", "hybrid"}

        if enable_lexical and lexical_retriever:
            t0 = time.perf_counter()
            lexical_hits = self._normalize_hits(lexical_retriever(query_text, plan.top_k))
            observation.lexical_ms = (time.perf_counter() - t0) * 1000.0
            observation.lexical_count = len(lexical_hits)

        if enable_semantic and semantic_retriever:
            t0 = time.perf_counter()
            semantic_hits = self._normalize_hits(semantic_retriever(query_text, plan.top_k))
            observation.semantic_ms = (time.perf_counter() - t0) * 1000.0
            observation.semantic_count = len(semantic_hits)

        t0 = time.perf_counter()
        items = self.merge_ranked_lists(lexical_hits, semantic_hits, plan)
        observation.fuse_ms = (time.perf_counter() - t0) * 1000.0
        observation.fused_count = len(items)
        observation.total_ms = (time.perf_counter() - started) * 1000.0
        return QueryOrchestratorResult(items=items, observation=observation)

    def merge_ranked_lists(
        self,
        lexical_hits: Sequence[Tuple[str, float]],
        semantic_hits: Sequence[Tuple[str, float]],
        plan: QueryPlan,
    ) -> List[OrchestratedItem]:
        normalized_mode = (plan.mode or "hybrid").strip().lower()
        if normalized_mode == "lexical":
            return self._build_single_source_items(lexical_hits, source="lexical", top_k=plan.top_k)
        if normalized_mode == "semantic":
            return self._build_single_source_items(semantic_hits, source="semantic", top_k=plan.top_k)

        # hybrid: 默认 RRF 融合；单源缺失时退化
        has_lexical = bool(lexical_hits)
        has_semantic = bool(semantic_hits)
        if not has_lexical and not has_semantic:
            return []
        if has_lexical and not has_semantic:
            return self._build_single_source_items(lexical_hits, source="lexical", top_k=plan.top_k)
        if has_semantic and not has_lexical:
            return self._build_single_source_items(semantic_hits, source="semantic", top_k=plan.top_k)

        return self._fuse_rrf(
            lexical_hits=lexical_hits,
            semantic_hits=semantic_hits,
            top_k=plan.top_k,
            rrf_k=max(1, int(plan.rrf_k)),
            lexical_weight=max(0.0, float(plan.lexical_weight)),
            semantic_weight=max(0.0, float(plan.semantic_weight)),
        )

    def _fuse_rrf(
        self,
        lexical_hits: Sequence[Tuple[str, float]],
        semantic_hits: Sequence[Tuple[str, float]],
        top_k: int,
        rrf_k: int,
        lexical_weight: float,
        semantic_weight: float,
    ) -> List[OrchestratedItem]:
        lexical_map = {key: score for key, score in lexical_hits}
        semantic_map = {key: score for key, score in semantic_hits}
        fused_scores: Dict[str, float] = {}

        for rank, (key, _score) in enumerate(lexical_hits, start=1):
            fused_scores[key] = fused_scores.get(key, 0.0) + lexical_weight / (rrf_k + rank)

        for rank, (key, _score) in enumerate(semantic_hits, start=1):
            fused_scores[key] = fused_scores.get(key, 0.0) + semantic_weight / (rrf_k + rank)

        sorted_keys = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)
        items: List[OrchestratedItem] = []
        for key, score in sorted_keys[: max(1, int(top_k))]:
            items.append(
                OrchestratedItem(
                    key=key,
                    score=float(score),
                    lexical_score=lexical_map.get(key),
                    semantic_score=semantic_map.get(key),
                )
            )
        return items

    def _build_single_source_items(
        self,
        hits: Sequence[Tuple[str, float]],
        source: str,
        top_k: int,
    ) -> List[OrchestratedItem]:
        items: List[OrchestratedItem] = []
        for key, score in list(hits)[: max(1, int(top_k))]:
            if source == "lexical":
                items.append(OrchestratedItem(key=key, score=score, lexical_score=score))
            else:
                items.append(OrchestratedItem(key=key, score=score, semantic_score=score))
        return items

    def _normalize_hits(self, hits: Sequence[Tuple[str, float]]) -> List[Tuple[str, float]]:
        # 输入通常已按分值排序；这里只做去重与类型收敛，保留首次排序优先级。
        dedup: Dict[str, float] = {}
        order: List[str] = []
        for raw_key, raw_score in hits or []:
            key = str(raw_key)
            score = float(raw_score)
            if key not in dedup:
                dedup[key] = score
                order.append(key)
            elif score > dedup[key]:
                dedup[key] = score
        return [(key, dedup[key]) for key in order]

