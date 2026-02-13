"""Search benchmark gate status loader for UI display."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkGateSnapshot:
    status: str
    summary: str
    detail_lines: list[str]
    summary_path: str


class BenchmarkGateStatusService:
    """Load latest benchmark pipeline report from docs/reports."""

    def __init__(self, reports_dir: Path | None = None):
        if reports_dir is None:
            project_root = Path(__file__).resolve().parents[2]
            reports_dir = project_root / "docs" / "reports"
        self._reports_dir = Path(reports_dir)

    def load_latest_snapshot(self) -> BenchmarkGateSnapshot:
        latest_summary = self._find_latest_summary_file()
        if latest_summary is None:
            return BenchmarkGateSnapshot(
                status="unknown",
                summary="性能闸门：暂无报告",
                detail_lines=["未找到 search_benchmark_pipeline_summary_*.json"],
                summary_path="",
            )

        payload = self._load_json_file(latest_summary)
        if payload is None:
            return BenchmarkGateSnapshot(
                status="error",
                summary="性能闸门：报告读取失败",
                detail_lines=[f"报告文件损坏或无法解析：{latest_summary}"],
                summary_path=str(latest_summary),
            )

        status = "pass" if bool(payload.get("passed")) else "fail"
        mode = "gate" if payload.get("regression_enabled") else "baseline"
        tag = str(payload.get("tag") or "-")
        elapsed_ms = float(payload.get("elapsed_ms") or 0.0)

        detail_lines = [
            f"结果：{'PASS' if status == 'pass' else 'FAIL'}",
            f"模式：{mode}",
            f"标签：{tag}",
            f"耗时：{elapsed_ms:.2f} ms",
            f"summary：{latest_summary}",
        ]

        matrix_json = payload.get("matrix_json")
        if matrix_json:
            matrix_path = Path(str(matrix_json))
            detail_lines.append(f"matrix：{matrix_path}")
            matrix_payload = self._load_json_file(matrix_path)
            if isinstance(matrix_payload, dict):
                failed_records = matrix_payload.get("failed_records") or []
                records_list = matrix_payload.get("records_list") or []
                detail_lines.append(f"records：{records_list}")
                if failed_records:
                    detail_lines.append(f"matrix failed records：{failed_records}")

        regression_json = payload.get("regression_json")
        if payload.get("regression_enabled") and regression_json:
            regression_path = Path(str(regression_json))
            detail_lines.append(f"regression：{regression_path}")
            regression_payload = self._load_json_file(regression_path)
            if isinstance(regression_payload, dict):
                if "passed" in regression_payload:
                    detail_lines.append(
                        f"regression result：{'PASS' if regression_payload.get('passed') else 'FAIL'}"
                    )
                diffs = regression_payload.get("diffs")
                if isinstance(diffs, list):
                    failed_diffs = [item.get("records") for item in diffs if not item.get("passed")]
                    if failed_diffs:
                        detail_lines.append(f"regression failed records：{failed_diffs}")

        summary = f"性能闸门：{'通过' if status == 'pass' else '失败'}（{mode}）"
        return BenchmarkGateSnapshot(
            status=status,
            summary=summary,
            detail_lines=detail_lines,
            summary_path=str(latest_summary),
        )

    def _find_latest_summary_file(self) -> Path | None:
        if not self._reports_dir.exists():
            return None
        files = list(self._reports_dir.glob("search_benchmark_pipeline_summary_*.json"))
        if not files:
            return None
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return files[0]

    @staticmethod
    def _load_json_file(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

