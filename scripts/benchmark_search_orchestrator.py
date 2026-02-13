#!/usr/bin/env python3
"""M5 阶段检索压测脚本：10万条规模、耗时指标、自动阈值判定。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def _load_orchestrator_symbols():
    """优先常规导入，失败时降级为按文件加载，避免包级依赖阻塞。"""
    try:
        from transcriptionist_v3.application.search_engine.query_orchestrator import QueryOrchestrator, QueryPlan

        return QueryOrchestrator, QueryPlan
    except Exception:
        module_path = PROJECT_ROOT / "application" / "search_engine" / "query_orchestrator.py"
        spec = importlib.util.spec_from_file_location("query_orchestrator_fallback", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载 query_orchestrator 模块")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.QueryOrchestrator, module.QueryPlan


@dataclass
class BenchmarkThreshold:
    p95_total_ms_max: float = 220.0
    p95_fuse_ms_max: float = 60.0
    overlap_rate_min: float = 0.45


@dataclass
class BenchmarkResult:
    records: int
    queries: int
    top_k: int
    lexical_p95_ms: float
    semantic_p95_ms: float
    fuse_p95_ms: float
    total_p95_ms: float
    overlap_avg: float
    overlap_p50: float
    overlap_p95: float
    pass_total_ms: bool
    pass_fuse_ms: bool
    pass_overlap: bool
    passed: bool


class SearchBenchmarkDataset:
    def __init__(self, records: int, vocab_size: int, dim: int, rng_seed: int = 42):
        self.records = records
        self.vocab_size = vocab_size
        self.dim = dim
        self.rng = np.random.default_rng(rng_seed)
        random.seed(rng_seed)

        self.tokens = [f"tok_{idx:04d}" for idx in range(vocab_size)]
        self.token_vectors = self._build_token_vectors()
        self.record_tokens = self._build_record_tokens()
        self.token_inverted = self._build_inverted_index()
        self.embedding_matrix = self._build_embeddings()

    def _build_token_vectors(self) -> dict[str, np.ndarray]:
        vectors = self.rng.normal(0.0, 1.0, (self.vocab_size, self.dim)).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms > 0.0, norms, 1.0)
        vectors = vectors / norms
        return {token: vectors[idx] for idx, token in enumerate(self.tokens)}

    def _build_record_tokens(self) -> list[list[str]]:
        data: list[list[str]] = []
        for _ in range(self.records):
            size = random.randint(3, 5)
            data.append(random.sample(self.tokens, size))
        return data

    def _build_inverted_index(self) -> dict[str, list[int]]:
        inverted: dict[str, list[int]] = {}
        for record_id, terms in enumerate(self.record_tokens):
            for term in terms:
                inverted.setdefault(term, []).append(record_id)
        return inverted

    def _build_embeddings(self) -> np.ndarray:
        matrix = np.zeros((self.records, self.dim), dtype=np.float32)
        for record_id, terms in enumerate(self.record_tokens):
            vectors = [self.token_vectors[token] for token in terms]
            embedding = np.mean(vectors, axis=0)
            norm = np.linalg.norm(embedding)
            matrix[record_id] = embedding / norm if norm > 0.0 else embedding
        return matrix


def _build_query_terms(dataset: SearchBenchmarkDataset, query_count: int) -> list[list[str]]:
    terms_list: list[list[str]] = []
    for _ in range(query_count):
        size = random.randint(2, 3)
        terms_list.append(random.sample(dataset.tokens, size))
    return terms_list


def _build_query_embedding(dataset: SearchBenchmarkDataset, terms: Sequence[str]) -> np.ndarray:
    vectors = [dataset.token_vectors[token] for token in terms]
    embedding = np.mean(vectors, axis=0)
    norm = np.linalg.norm(embedding)
    if norm == 0.0:
        return embedding
    return embedding / norm


def _make_lexical_retriever(dataset: SearchBenchmarkDataset, terms: Sequence[str]) -> Callable[[str, int], list[tuple[str, float]]]:
    counter: dict[int, float] = {}
    for term in terms:
        for record_id in dataset.token_inverted.get(term, []):
            counter[record_id] = counter.get(record_id, 0.0) + 1.0

    ranked = sorted(counter.items(), key=lambda item: item[1], reverse=True)

    def _retriever(_query_text: str, top_k: int):
        limit = max(1, int(top_k))
        return [(str(record_id), score) for record_id, score in ranked[:limit]]

    return _retriever


def _make_semantic_retriever(dataset: SearchBenchmarkDataset, query_embedding: np.ndarray) -> Callable[[str, int], list[tuple[str, float]]]:
    sims = dataset.embedding_matrix @ query_embedding

    def _retriever(_query_text: str, top_k: int):
        limit = max(1, int(top_k))
        if limit >= len(sims):
            indices = np.argsort(-sims)
        else:
            partial = np.argpartition(-sims, limit - 1)[:limit]
            indices = partial[np.argsort(-sims[partial])]
        return [(str(int(idx)), float(sims[idx])) for idx in indices]

    return _retriever


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = int(round((len(ordered) - 1) * ratio))
    pos = max(0, min(len(ordered) - 1, pos))
    return float(ordered[pos])


def run_benchmark(records: int, query_count: int, top_k: int, threshold: BenchmarkThreshold) -> BenchmarkResult:
    QueryOrchestrator, QueryPlan = _load_orchestrator_symbols()
    orchestrator = QueryOrchestrator()

    dataset = SearchBenchmarkDataset(records=records, vocab_size=2400, dim=128)
    query_terms_list = _build_query_terms(dataset, query_count)

    lexical_ms: list[float] = []
    semantic_ms: list[float] = []
    fuse_ms: list[float] = []
    total_ms: list[float] = []
    overlaps: list[float] = []

    for terms in query_terms_list:
        query_text = " ".join(terms)
        query_embedding = _build_query_embedding(dataset, terms)

        lexical_retriever = _make_lexical_retriever(dataset, terms)
        semantic_retriever = _make_semantic_retriever(dataset, query_embedding)

        result = orchestrator.execute(
            query_text=query_text,
            plan=QueryPlan(
                mode="hybrid",
                top_k=top_k,
                rrf_k=60,
                lexical_weight=1.0,
                semantic_weight=1.0,
            ),
            lexical_retriever=lexical_retriever,
            semantic_retriever=semantic_retriever,
        )

        obs = result.observation
        lexical_ms.append(float(obs.lexical_ms))
        semantic_ms.append(float(obs.semantic_ms))
        fuse_ms.append(float(obs.fuse_ms))
        total_ms.append(float(obs.total_ms))

        semantic_only = semantic_retriever(query_text, top_k)
        semantic_set = {item[0] for item in semantic_only[:top_k]}
        hybrid_set = {item.key for item in result.items[:top_k]}
        overlap = len(semantic_set & hybrid_set) / max(1, min(len(semantic_set), len(hybrid_set)))
        overlaps.append(float(overlap))

    lexical_p95 = _percentile(lexical_ms, 0.95)
    semantic_p95 = _percentile(semantic_ms, 0.95)
    fuse_p95 = _percentile(fuse_ms, 0.95)
    total_p95 = _percentile(total_ms, 0.95)
    overlap_avg = float(statistics.mean(overlaps)) if overlaps else 0.0
    overlap_p50 = _percentile(overlaps, 0.50)
    overlap_p95 = _percentile(overlaps, 0.95)

    pass_total = total_p95 <= threshold.p95_total_ms_max
    pass_fuse = fuse_p95 <= threshold.p95_fuse_ms_max
    pass_overlap = overlap_avg >= threshold.overlap_rate_min

    return BenchmarkResult(
        records=records,
        queries=query_count,
        top_k=top_k,
        lexical_p95_ms=lexical_p95,
        semantic_p95_ms=semantic_p95,
        fuse_p95_ms=fuse_p95,
        total_p95_ms=total_p95,
        overlap_avg=overlap_avg,
        overlap_p50=overlap_p50,
        overlap_p95=overlap_p95,
        pass_total_ms=pass_total,
        pass_fuse_ms=pass_fuse,
        pass_overlap=pass_overlap,
        passed=pass_total and pass_fuse and pass_overlap,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检索编排压测脚本（M5）")
    parser.add_argument("--records", type=int, default=100_000, help="样本条数，默认 100000")
    parser.add_argument("--queries", type=int, default=50, help="查询次数，默认 50")
    parser.add_argument("--top-k", type=int, default=200, help="每次查询取 TopK，默认 200")
    parser.add_argument("--threshold-total-ms", type=float, default=220.0, help="P95 总耗时阈值(ms)")
    parser.add_argument("--threshold-fuse-ms", type=float, default=60.0, help="P95 融合耗时阈值(ms)")
    parser.add_argument("--threshold-overlap", type=float, default=0.45, help="平均重叠率阈值(0-1)")
    parser.add_argument("--json-out", type=str, default="", help="可选：输出 JSON 文件路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    threshold = BenchmarkThreshold(
        p95_total_ms_max=float(args.threshold_total_ms),
        p95_fuse_ms_max=float(args.threshold_fuse_ms),
        overlap_rate_min=float(args.threshold_overlap),
    )

    started = time.perf_counter()
    result = run_benchmark(
        records=max(1, int(args.records)),
        query_count=max(1, int(args.queries)),
        top_k=max(1, int(args.top_k)),
        threshold=threshold,
    )
    elapsed = (time.perf_counter() - started) * 1000.0

    print("=" * 72)
    print("M5 检索编排压测结果（Synthetic 100k 基线）")
    print("=" * 72)
    print(f"records={result.records}, queries={result.queries}, top_k={result.top_k}")
    print(f"lexical_p95={result.lexical_p95_ms:.2f}ms")
    print(f"semantic_p95={result.semantic_p95_ms:.2f}ms")
    print(f"fuse_p95={result.fuse_p95_ms:.2f}ms")
    print(f"total_p95={result.total_p95_ms:.2f}ms")
    print(f"overlap_avg={result.overlap_avg:.2%}, overlap_p50={result.overlap_p50:.2%}, overlap_p95={result.overlap_p95:.2%}")
    print("-" * 72)
    print(f"阈值判定: total_p95<={threshold.p95_total_ms_max:.2f}ms -> {'PASS' if result.pass_total_ms else 'FAIL'}")
    print(f"阈值判定: fuse_p95<={threshold.p95_fuse_ms_max:.2f}ms -> {'PASS' if result.pass_fuse_ms else 'FAIL'}")
    print(f"阈值判定: overlap_avg>={threshold.overlap_rate_min:.2%} -> {'PASS' if result.pass_overlap else 'FAIL'}")
    print(f"整体结论: {'PASS' if result.passed else 'FAIL'}")
    print(f"总执行时间: {elapsed:.2f}ms")
    print("=" * 72)

    payload = {
        "result": asdict(result),
        "threshold": asdict(threshold),
        "elapsed_ms": elapsed,
    }
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已输出 JSON: {out_path}")

    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
