from __future__ import annotations

import json
import argparse
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests


OPENAPI_MODELS = "https://www.modelscope.cn/openapi/v1/models"
DETAIL_API = "https://www.modelscope.cn/api/v1/models/{model_id}"


KEYWORDS = [
    "SFX",
    "sound effect",
    "foley",
    "ambience",
    "text-to-audio",
    "audio generation",
    "music generation",
    "music",
    "audio",
]


@dataclass
class ModelCandidate:
    model_id: str
    display_name: str
    tasks: list[str]
    tags: list[str]
    downloads: int
    likes: int
    support_api_inference: bool
    support_inference: bool
    support_experience: bool
    support_deployment: bool
    source_keywords: list[str]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _is_audio_related(model_id: str, tasks: list[str], tags: list[str]) -> bool:
    text = " ".join([model_id, *tasks, *tags]).lower()
    hit_tokens = [
        "audio",
        "sound",
        "sfx",
        "foley",
        "ambience",
        "music",
        "tts",
        "text-to-audio",
        "speech",
        "voice",
        "音频",
        "音效",
        "语音",
        "音乐",
    ]
    return any(token in text for token in hit_tokens)


def fetch_search_results(keyword: str, page_number: int, page_size: int = 20) -> list[dict[str, Any]]:
    response = requests.get(
        OPENAPI_MODELS,
        params={
            "page_number": page_number,
            "page_size": page_size,
            "search": keyword,
        },
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("success"):
        return []
    data = payload.get("data") or {}
    models = data.get("models") or []
    if isinstance(models, list):
        return [item for item in models if isinstance(item, dict)]
    return []


def fetch_model_detail(model_id: str) -> dict[str, Any]:
    response = requests.get(DETAIL_API.format(model_id=model_id), timeout=12)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    data = payload.get("Data")
    return data if isinstance(data, dict) else {}


def discover(max_pages_per_keyword: int = 2) -> tuple[list[ModelCandidate], list[ModelCandidate]]:
    collected: dict[str, dict[str, Any]] = {}

    for keyword in KEYWORDS:
        for page in range(1, max_pages_per_keyword + 1):
            try:
                models = fetch_search_results(keyword, page)
            except Exception:
                break
            if not models:
                break

            for item in models:
                model_id = str(item.get("id") or "").strip()
                if not model_id:
                    continue
                if model_id not in collected:
                    collected[model_id] = {
                        "search_item": item,
                        "source_keywords": set([keyword]),
                    }
                else:
                    collected[model_id]["source_keywords"].add(keyword)

            if len(models) < 20:
                break

    candidates: list[ModelCandidate] = []
    non_api_candidates: list[ModelCandidate] = []

    for model_id, data in collected.items():
        search_item = data["search_item"]
        tasks = [str(x) for x in (search_item.get("tasks") or [])]
        tags = [str(x) for x in (search_item.get("tags") or [])]

        if not _is_audio_related(model_id, tasks, tags):
            continue

        detail = {}
        try:
            detail = fetch_model_detail(model_id)
        except Exception:
            pass

        candidate = ModelCandidate(
            model_id=model_id,
            display_name=str(search_item.get("display_name") or model_id),
            tasks=tasks,
            tags=tags,
            downloads=_safe_int(search_item.get("downloads")),
            likes=_safe_int(search_item.get("likes")),
            support_api_inference=bool(detail.get("SupportApiInference")),
            support_inference=bool(detail.get("SupportInference")),
            support_experience=bool(detail.get("SupportExperience")),
            support_deployment=bool(detail.get("SupportDeployment")),
            source_keywords=sorted(list(data["source_keywords"])),
        )

        if candidate.support_api_inference:
            candidates.append(candidate)
        else:
            non_api_candidates.append(candidate)

        time.sleep(0.06)

    sort_key = lambda c: (c.downloads, c.likes)
    candidates.sort(key=sort_key, reverse=True)
    non_api_candidates.sort(key=sort_key, reverse=True)
    return candidates, non_api_candidates


def write_reports(api_candidates: list[ModelCandidate], non_api_candidates: list[ModelCandidate]) -> None:
    report_dir = Path("docs/reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / "modelscope_audio_inference_candidates.json"
    md_path = report_dir / "modelscope_audio_inference_candidates.md"

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "api_inference_candidates": [asdict(item) for item in api_candidates],
        "audio_related_but_not_api_inference": [asdict(item) for item in non_api_candidates],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# ModelScope 音频/音效模型 API-Inference 候选清单")
    lines.append("")
    lines.append(f"- 生成时间：{payload['generated_at']}")
    lines.append(f"- API-Inference 候选数：{len(api_candidates)}")
    lines.append(f"- 音频相关但不支持 API-Inference：{len(non_api_candidates)}")
    lines.append("")

    lines.append("## 支持 API-Inference 的音频候选")
    lines.append("")
    lines.append("| 模型ID | 任务 | 下载 | 点赞 | 推理能力 | 命中关键词 |")
    lines.append("|---|---|---:|---:|---|---|")
    if api_candidates:
        for item in api_candidates[:80]:
            infer_flags = []
            if item.support_api_inference:
                infer_flags.append("API")
            if item.support_inference:
                infer_flags.append("Inference")
            if item.support_experience:
                infer_flags.append("Demo")
            if item.support_deployment:
                infer_flags.append("Deployment")
            lines.append(
                f"| `{item.model_id}` | {', '.join(item.tasks[:4]) or '-'} | {item.downloads} | {item.likes} | {'/'.join(infer_flags) or '-'} | {', '.join(item.source_keywords[:4])} |"
            )
    else:
        lines.append("| - | - | - | - | - | - |")

    lines.append("")
    lines.append("## 音频相关但当前不支持 API-Inference（前 40）")
    lines.append("")
    lines.append("| 模型ID | 任务 | 下载 | 点赞 | 命中关键词 |")
    lines.append("|---|---|---:|---:|---|")
    for item in non_api_candidates[:40]:
        lines.append(
            f"| `{item.model_id}` | {', '.join(item.tasks[:4]) or '-'} | {item.downloads} | {item.likes} | {', '.join(item.source_keywords[:4])} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover ModelScope audio models with API inference support")
    parser.add_argument("--pages", type=int, default=2, help="Max pages per keyword to scan")
    args = parser.parse_args()

    api_candidates, non_api_candidates = discover(max_pages_per_keyword=max(1, args.pages))
    write_reports(api_candidates, non_api_candidates)
    print(f"API-Inference candidates: {len(api_candidates)}")
    print(f"Audio-related non-API candidates: {len(non_api_candidates)}")
    print("Report written to docs/reports/modelscope_audio_inference_candidates.md")


if __name__ == "__main__":
    main()
