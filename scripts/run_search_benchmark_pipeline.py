#!/usr/bin/env python3
"""M5 stage-4 pipeline: run benchmark matrix and optional regression gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run search benchmark pipeline (M5-stage4)")
    parser.add_argument("--records-list", default="100000,500000,1000000", help="Comma separated records list")
    parser.add_argument("--queries", type=int, default=50, help="Query count per records size")
    parser.add_argument("--top-k", type=int, default=200, help="Top K per query")
    parser.add_argument("--threshold-total-ms", type=float, default=220.0, help="P95 total threshold")
    parser.add_argument("--threshold-fuse-ms", type=float, default=60.0, help="P95 fuse threshold")
    parser.add_argument("--threshold-overlap", type=float, default=0.45, help="Overlap average threshold")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop matrix when one scale fails")
    parser.add_argument("--baseline-json", default="", help="Optional baseline matrix json for regression gate")
    parser.add_argument("--allow-total-p95-delta-ms", type=float, default=15.0, help="Allowed total_p95 increase")
    parser.add_argument("--allow-fuse-p95-delta-ms", type=float, default=10.0, help="Allowed fuse_p95 increase")
    parser.add_argument("--allow-overlap-drop", type=float, default=0.05, help="Allowed overlap average drop")
    parser.add_argument("--reports-dir", default="docs/reports", help="Output directory for pipeline reports")
    parser.add_argument("--tag", default="", help="Optional report tag suffix")
    return parser.parse_args()


def _run_command(command: list[str]) -> int:
    print("[pipeline] running:", " ".join(command))
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    return int(completed.returncode)


def _build_tag(raw_tag: str) -> str:
    if raw_tag:
        return raw_tag.strip()
    return time.strftime("%Y%m%d_%H%M%S")


def main() -> int:
    args = parse_args()
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    tag = _build_tag(args.tag)

    matrix_json = reports_dir / f"search_benchmark_matrix_{tag}.json"
    matrix_csv = reports_dir / f"search_benchmark_matrix_{tag}.csv"
    regression_json = reports_dir / f"search_benchmark_regression_{tag}.json"
    summary_json = reports_dir / f"search_benchmark_pipeline_summary_{tag}.json"

    matrix_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_search_benchmark_matrix.py"),
        "--records-list",
        str(args.records_list),
        "--queries",
        str(max(1, int(args.queries))),
        "--top-k",
        str(max(1, int(args.top_k))),
        "--threshold-total-ms",
        str(float(args.threshold_total_ms)),
        "--threshold-fuse-ms",
        str(float(args.threshold_fuse_ms)),
        "--threshold-overlap",
        str(float(args.threshold_overlap)),
        "--json-out",
        str(matrix_json),
        "--csv-out",
        str(matrix_csv),
    ]
    if args.stop_on_fail:
        matrix_command.append("--stop-on-fail")

    started = time.time()
    matrix_exit_code = _run_command(matrix_command)

    regression_exit_code = None
    regression_enabled = bool(args.baseline_json)
    if matrix_exit_code == 0 and regression_enabled:
        regression_command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "check_search_benchmark_regression.py"),
            "--baseline-json",
            str(args.baseline_json),
            "--current-json",
            str(matrix_json),
            "--allow-total-p95-delta-ms",
            str(float(args.allow_total_p95_delta_ms)),
            "--allow-fuse-p95-delta-ms",
            str(float(args.allow_fuse_p95_delta_ms)),
            "--allow-overlap-drop",
            str(float(args.allow_overlap_drop)),
            "--json-out",
            str(regression_json),
        ]
        regression_exit_code = _run_command(regression_command)

    pipeline_passed = matrix_exit_code == 0 and (not regression_enabled or regression_exit_code == 0)
    elapsed_ms = (time.time() - started) * 1000.0

    summary_payload = {
        "tag": tag,
        "matrix_json": str(matrix_json),
        "matrix_csv": str(matrix_csv),
        "regression_json": str(regression_json) if regression_enabled else "",
        "baseline_json": str(args.baseline_json) if regression_enabled else "",
        "matrix_exit_code": matrix_exit_code,
        "regression_exit_code": regression_exit_code,
        "regression_enabled": regression_enabled,
        "passed": pipeline_passed,
        "elapsed_ms": elapsed_ms,
        "generated_at_unix": time.time(),
    }
    summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 88)
    print(f"[pipeline] matrix_json: {matrix_json}")
    print(f"[pipeline] matrix_csv : {matrix_csv}")
    if regression_enabled:
        print(f"[pipeline] regression_json: {regression_json}")
    print(f"[pipeline] summary_json: {summary_json}")
    print(f"[pipeline] result: {'PASS' if pipeline_passed else 'FAIL'}")
    print("=" * 88)

    return 0 if pipeline_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

