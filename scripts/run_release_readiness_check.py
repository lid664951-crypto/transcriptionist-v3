#!/usr/bin/env python3
"""R1: one-command release readiness check for v1.2.0."""

from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run release readiness checks for v1.2.0")
    parser.add_argument("--profile", choices=("ci", "standard"), default="ci")
    parser.add_argument("--mode", choices=("gate", "baseline"), default="gate")
    parser.add_argument("--tag", default="")
    parser.add_argument("--reports-dir", default="docs/reports")
    parser.add_argument("--skip-gate", action="store_true")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def _build_tag(raw_tag: str) -> str:
    if raw_tag and raw_tag.strip():
        return raw_tag.strip()
    return f"release_ready_{time.strftime('%Y%m%d_%H%M%S')}"


def _check_files_exist(paths: list[Path]) -> tuple[bool, list[str]]:
    missing = [str(path) for path in paths if not path.exists()]
    return len(missing) == 0, missing


def _check_py_compile(paths: list[Path]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for path in paths:
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return len(errors) == 0, errors


def _run_release_gate(mode: str, profile: str, tag: str, reports_dir: Path) -> tuple[int, str]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_search_benchmark_release_gate.py"),
        "--mode",
        mode,
        "--profile",
        profile,
        "--tag",
        tag,
        "--reports-dir",
        str(reports_dir),
        "--stop-on-fail",
    ]
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    return int(completed.returncode), " ".join(command)


def _check_pipeline_summary(reports_dir: Path, tag: str) -> tuple[bool, str, bool | None]:
    summary_path = reports_dir / f"search_benchmark_pipeline_summary_{tag}.json"
    if not summary_path.exists():
        return False, str(summary_path), None

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        return True, str(summary_path), bool(payload.get("passed"))
    except Exception:
        return False, str(summary_path), None


def main() -> int:
    args = parse_args()
    started = time.time()
    tag = _build_tag(args.tag)
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    required_files = [
        PROJECT_ROOT / "scripts" / "run_search_benchmark_release_gate.py",
        PROJECT_ROOT / "scripts" / "run_search_benchmark_pipeline.py",
        PROJECT_ROOT / "scripts" / "run_search_benchmark_matrix.py",
        PROJECT_ROOT / "scripts" / "check_search_benchmark_regression.py",
        PROJECT_ROOT / "application" / "search_engine" / "benchmark_gate_status.py",
        PROJECT_ROOT / "ui" / "main_window.py",
    ]

    compile_targets = [
        PROJECT_ROOT / "scripts" / "run_release_readiness_check.py",
        PROJECT_ROOT / "scripts" / "run_search_benchmark_release_gate.py",
        PROJECT_ROOT / "scripts" / "run_search_benchmark_pipeline.py",
        PROJECT_ROOT / "scripts" / "run_search_benchmark_matrix.py",
        PROJECT_ROOT / "scripts" / "check_search_benchmark_regression.py",
        PROJECT_ROOT / "application" / "search_engine" / "benchmark_gate_status.py",
        PROJECT_ROOT / "application" / "search_engine" / "__init__.py",
        PROJECT_ROOT / "ui" / "main_window.py",
    ]

    checks: list[dict] = []

    files_ok, missing_files = _check_files_exist(required_files)
    checks.append(
        {
            "name": "required_files",
            "passed": files_ok,
            "missing": missing_files,
        }
    )

    compile_ok, compile_errors = _check_py_compile(compile_targets)
    checks.append(
        {
            "name": "py_compile",
            "passed": compile_ok,
            "errors": compile_errors,
        }
    )

    gate_exit_code = None
    gate_command = ""
    if not args.skip_gate:
        gate_exit_code, gate_command = _run_release_gate(
            mode=args.mode,
            profile=args.profile,
            tag=tag,
            reports_dir=reports_dir,
        )
        checks.append(
            {
                "name": "release_gate",
                "passed": gate_exit_code == 0,
                "exit_code": gate_exit_code,
                "command": gate_command,
            }
        )

        summary_exists, summary_path, summary_passed = _check_pipeline_summary(reports_dir=reports_dir, tag=tag)
        checks.append(
            {
                "name": "pipeline_summary",
                "passed": summary_exists and (summary_passed is True),
                "summary_exists": summary_exists,
                "summary_passed": summary_passed,
                "summary_path": summary_path,
            }
        )

    all_passed = all(bool(item.get("passed")) for item in checks)
    elapsed_ms = (time.time() - started) * 1000.0

    output_payload = {
        "tag": tag,
        "profile": args.profile,
        "mode": args.mode,
        "skip_gate": bool(args.skip_gate),
        "checks": checks,
        "passed": all_passed,
        "elapsed_ms": elapsed_ms,
        "generated_at_unix": time.time(),
    }

    if args.json_out:
        out_path = Path(args.json_out)
    else:
        out_path = reports_dir / f"release_readiness_{tag}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 88)
    print("R1 发布就绪检查")
    print("=" * 88)
    for item in checks:
        result = "PASS" if item.get("passed") else "FAIL"
        print(f"- {item.get('name')}: {result}")
    print(f"- report: {out_path}")
    print(f"- elapsed: {elapsed_ms:.2f} ms")
    print(f"- final: {'PASS' if all_passed else 'FAIL'}")
    print("=" * 88)

    return 0 if all_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

