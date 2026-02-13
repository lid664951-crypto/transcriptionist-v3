#!/usr/bin/env python3
"""M5 阶段矩阵压测：多规模批跑 + 汇总报表 + 失败自动中断。"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_benchmark_module():
    module_path = PROJECT_ROOT / "scripts" / "benchmark_search_orchestrator.py"
    spec = importlib.util.spec_from_file_location("benchmark_search_orchestrator_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 benchmark_search_orchestrator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_records_list(raw_text: str) -> list[int]:
    values: list[int] = []
    for part in (raw_text or "").split(","):
        text = part.strip()
        if not text:
            continue
        value = int(text)
        if value <= 0:
            continue
        values.append(value)
    if not values:
        raise ValueError("records-list 不能为空")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检索矩阵压测脚本（M5-阶段2）")
    parser.add_argument("--records-list", default="100000,500000,1000000", help="样本规模列表，逗号分隔")
    parser.add_argument("--queries", type=int, default=50, help="每个规模查询次数")
    parser.add_argument("--top-k", type=int, default=200, help="每次查询 TopK")
    parser.add_argument("--threshold-total-ms", type=float, default=220.0, help="P95 总耗时阈值")
    parser.add_argument("--threshold-fuse-ms", type=float, default=60.0, help="P95 融合耗时阈值")
    parser.add_argument("--threshold-overlap", type=float, default=0.45, help="平均重叠率阈值")
    parser.add_argument("--stop-on-fail", action="store_true", help="任意规模失败时立即停止后续压测")
    parser.add_argument("--json-out", default="docs/reports/search_benchmark_matrix.json", help="矩阵汇总 JSON 输出")
    parser.add_argument("--csv-out", default="docs/reports/search_benchmark_matrix.csv", help="矩阵汇总 CSV 输出")
    return parser.parse_args()


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "records",
        "queries",
        "top_k",
        "lexical_p95_ms",
        "semantic_p95_ms",
        "fuse_p95_ms",
        "total_p95_ms",
        "overlap_avg",
        "overlap_p50",
        "overlap_p95",
        "pass_total_ms",
        "pass_fuse_ms",
        "pass_overlap",
        "passed",
        "elapsed_ms",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in headers})


def main() -> int:
    args = parse_args()
    records_list = _parse_records_list(args.records_list)

    module = _load_benchmark_module()
    threshold = module.BenchmarkThreshold(
        p95_total_ms_max=float(args.threshold_total_ms),
        p95_fuse_ms_max=float(args.threshold_fuse_ms),
        overlap_rate_min=float(args.threshold_overlap),
    )

    rows: list[dict] = []
    failed_records: list[int] = []

    print("=" * 80)
    print("M5 矩阵压测开始")
    print(f"records_list={records_list}, queries={args.queries}, top_k={args.top_k}")
    print("=" * 80)

    for records in records_list:
        t0 = time.perf_counter()
        result = module.run_benchmark(
            records=int(records),
            query_count=max(1, int(args.queries)),
            top_k=max(1, int(args.top_k)),
            threshold=threshold,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        row = asdict(result)
        row["elapsed_ms"] = elapsed_ms
        rows.append(row)

        print("-" * 80)
        print(
            f"records={records} | total_p95={result.total_p95_ms:.2f}ms | "
            f"fuse_p95={result.fuse_p95_ms:.2f}ms | overlap_avg={result.overlap_avg:.2%} | "
            f"result={'PASS' if result.passed else 'FAIL'}"
        )

        if not result.passed:
            failed_records.append(int(records))
            if args.stop_on_fail:
                print(f"触发 stop-on-fail，提前终止于 records={records}")
                break

    json_path = Path(args.json_out)
    csv_path = Path(args.csv_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "threshold": asdict(threshold),
        "records_list": records_list,
        "queries": int(args.queries),
        "top_k": int(args.top_k),
        "stop_on_fail": bool(args.stop_on_fail),
        "results": rows,
        "failed_records": failed_records,
        "passed": len(failed_records) == 0,
        "generated_at_unix": time.time(),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(csv_path, rows)

    print("=" * 80)
    print(f"已输出 JSON: {json_path}")
    print(f"已输出 CSV : {csv_path}")
    if failed_records:
        print(f"失败规模: {failed_records}")
        print("矩阵结论: FAIL")
        print("=" * 80)
        return 2

    print("矩阵结论: PASS")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

