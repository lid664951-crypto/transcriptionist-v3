#!/usr/bin/env python3
"""M5 stage-5 release gate wrapper for search benchmark pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ProfilePreset:
    records_list: str
    queries: int
    top_k: int
    threshold_total_ms: float
    threshold_fuse_ms: float
    threshold_overlap: float
    allow_total_p95_delta_ms: float
    allow_fuse_p95_delta_ms: float
    allow_overlap_drop: float


PROFILE_PRESETS: dict[str, ProfilePreset] = {
    "ci": ProfilePreset(
        records_list="10000,20000",
        queries=10,
        top_k=100,
        threshold_total_ms=220.0,
        threshold_fuse_ms=60.0,
        threshold_overlap=0.45,
        allow_total_p95_delta_ms=15.0,
        allow_fuse_p95_delta_ms=10.0,
        allow_overlap_drop=0.05,
    ),
    "standard": ProfilePreset(
        records_list="100000,500000,1000000",
        queries=50,
        top_k=200,
        threshold_total_ms=220.0,
        threshold_fuse_ms=60.0,
        threshold_overlap=0.45,
        allow_total_p95_delta_ms=15.0,
        allow_fuse_p95_delta_ms=10.0,
        allow_overlap_drop=0.05,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run search benchmark release gate (M5-stage5)")
    parser.add_argument("--mode", choices=("baseline", "gate"), default="gate")
    parser.add_argument("--profile", choices=tuple(PROFILE_PRESETS.keys()), default="standard")
    parser.add_argument("--records-list", default="", help="Optional override records list")
    parser.add_argument("--queries", type=int, default=0, help="Optional override queries")
    parser.add_argument("--top-k", type=int, default=0, help="Optional override top-k")
    parser.add_argument("--threshold-total-ms", type=float, default=-1.0)
    parser.add_argument("--threshold-fuse-ms", type=float, default=-1.0)
    parser.add_argument("--threshold-overlap", type=float, default=-1.0)
    parser.add_argument("--allow-total-p95-delta-ms", type=float, default=-1.0)
    parser.add_argument("--allow-fuse-p95-delta-ms", type=float, default=-1.0)
    parser.add_argument("--allow-overlap-drop", type=float, default=-1.0)
    parser.add_argument("--reports-dir", default="docs/reports")
    parser.add_argument("--baseline-json", default="", help="Optional baseline json path")
    parser.add_argument("--tag", default="")
    parser.add_argument("--stop-on-fail", action="store_true")
    parser.add_argument(
        "--promote-baseline",
        action="store_true",
        help="In baseline mode, copy matrix output as latest baseline",
    )
    return parser.parse_args()


def _pick_str(override: str, default: str) -> str:
    return override.strip() if override and override.strip() else default


def _pick_int(override: int, default: int) -> int:
    return max(1, int(override)) if int(override) > 0 else default


def _pick_float(override: float, default: float) -> float:
    return float(override) if float(override) >= 0 else default


def _default_baseline_path(reports_dir: Path, profile: str) -> Path:
    return reports_dir / "baseline" / f"search_benchmark_matrix_baseline_{profile}.json"


def _build_tag(raw_tag: str, mode: str, profile: str) -> str:
    if raw_tag and raw_tag.strip():
        return raw_tag.strip()
    return f"{mode}_{profile}_{time.strftime('%Y%m%d_%H%M%S')}"


def _run_command(command: list[str]) -> int:
    print("[release-gate] running:", " ".join(command))
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    return int(completed.returncode)


def _load_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _promote_baseline(summary_path: Path, baseline_path: Path, profile: str, tag: str) -> None:
    summary_payload = _load_summary(summary_path)
    matrix_json = Path(summary_payload["matrix_json"])
    if not matrix_json.exists():
        raise FileNotFoundError(f"matrix json not found: {matrix_json}")

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(matrix_json, baseline_path)

    manifest_path = baseline_path.parent / "search_benchmark_baseline_manifest.json"
    manifest_payload = {}
    if manifest_path.exists():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest_payload = {}

    profiles = manifest_payload.get("profiles", {}) if isinstance(manifest_payload, dict) else {}
    profiles[profile] = {
        "baseline_json": str(baseline_path),
        "source_matrix_json": str(matrix_json),
        "source_tag": tag,
        "updated_at_unix": time.time(),
    }

    new_payload = {
        "profiles": profiles,
        "updated_at_unix": time.time(),
    }
    manifest_path.write_text(json.dumps(new_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[release-gate] baseline promoted: {baseline_path}")
    print(f"[release-gate] manifest updated: {manifest_path}")


def main() -> int:
    args = parse_args()
    preset = PROFILE_PRESETS[args.profile]

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = Path(args.baseline_json) if args.baseline_json else _default_baseline_path(reports_dir, args.profile)
    tag = _build_tag(args.tag, args.mode, args.profile)

    records_list = _pick_str(args.records_list, preset.records_list)
    queries = _pick_int(args.queries, preset.queries)
    top_k = _pick_int(args.top_k, preset.top_k)
    threshold_total_ms = _pick_float(args.threshold_total_ms, preset.threshold_total_ms)
    threshold_fuse_ms = _pick_float(args.threshold_fuse_ms, preset.threshold_fuse_ms)
    threshold_overlap = _pick_float(args.threshold_overlap, preset.threshold_overlap)
    allow_total = _pick_float(args.allow_total_p95_delta_ms, preset.allow_total_p95_delta_ms)
    allow_fuse = _pick_float(args.allow_fuse_p95_delta_ms, preset.allow_fuse_p95_delta_ms)
    allow_overlap_drop = _pick_float(args.allow_overlap_drop, preset.allow_overlap_drop)

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_search_benchmark_pipeline.py"),
        "--records-list",
        records_list,
        "--queries",
        str(queries),
        "--top-k",
        str(top_k),
        "--threshold-total-ms",
        str(threshold_total_ms),
        "--threshold-fuse-ms",
        str(threshold_fuse_ms),
        "--threshold-overlap",
        str(threshold_overlap),
        "--allow-total-p95-delta-ms",
        str(allow_total),
        "--allow-fuse-p95-delta-ms",
        str(allow_fuse),
        "--allow-overlap-drop",
        str(allow_overlap_drop),
        "--reports-dir",
        str(reports_dir),
        "--tag",
        tag,
    ]
    if args.stop_on_fail:
        command.append("--stop-on-fail")
    if args.mode == "gate":
        command.extend(["--baseline-json", str(baseline_path)])

    exit_code = _run_command(command)
    summary_path = reports_dir / f"search_benchmark_pipeline_summary_{tag}.json"

    if exit_code == 0 and args.mode == "baseline" and args.promote_baseline:
        _promote_baseline(summary_path=summary_path, baseline_path=baseline_path, profile=args.profile, tag=tag)

    print("=" * 88)
    print(f"[release-gate] mode={args.mode}, profile={args.profile}")
    print(f"[release-gate] summary={summary_path}")
    print(f"[release-gate] baseline={baseline_path}")
    print(f"[release-gate] result={'PASS' if exit_code == 0 else 'FAIL'}")
    print("=" * 88)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

