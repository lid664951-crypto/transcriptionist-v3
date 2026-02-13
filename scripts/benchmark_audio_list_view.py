#!/usr/bin/env python3
"""AudioFilesPanel 1万条列表微压测脚本。"""

from __future__ import annotations

import random
import string
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from transcriptionist_v3.ui.panels.audio_files_panel import AudioFilesPanel


def _random_word(length: int = 8) -> str:
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for _ in range(length))


def _build_fake_dataset(count: int) -> list[dict]:
    dataset: list[dict] = []
    formats = ["wav", "mp3", "flac", "ogg"]
    for index in range(count):
        filename = f"sfx_{index:05d}_{_random_word(6)}.{random.choice(formats)}"
        translated = f"音效_{index:05d}" if index % 3 == 0 else ""
        tags = [f"tag{index % 11}", f"scene{index % 7}"] if index % 4 != 0 else []
        dataset.append(
            {
                "file_path": str(Path("D:/benchmark/audio") / filename),
                "filename": filename,
                "translated_name": translated,
                "original_filename": filename,
                "tags": tags,
                "duration": round(random.uniform(0.1, 12.0), 2),
                "file_size": random.randint(30_000, 40_000_000),
                "format": filename.split(".")[-1],
                "index_status": index % 3,
                "tag_status": (index + 1) % 3,
                "translation_status": (index + 2) % 3,
            }
        )
    return dataset


def run_benchmark(record_count: int = 10_000):
    random.seed(42)
    app = QApplication.instance() or QApplication(sys.argv)

    dataset = _build_fake_dataset(record_count)
    indices = list(range(record_count))

    panel = AudioFilesPanel()
    panel.set_data_provider(lambda i: dataset[i])

    t0 = time.perf_counter()
    panel.set_folder_indices("D:/benchmark/audio", indices)
    t1 = time.perf_counter()

    panel.resize(1280, 720)
    panel.show()
    app.processEvents()
    t2 = time.perf_counter()

    print("=" * 60)
    print("AudioFilesPanel 微压测（10k）")
    print("=" * 60)
    print(f"数据构造条数: {record_count}")
    print(f"set_folder_indices 耗时: {(t1 - t0) * 1000:.2f} ms")
    print(f"首次渲染总耗时: {(t2 - t0) * 1000:.2f} ms")
    print(f"首次渲染阶段耗时: {(t2 - t1) * 1000:.2f} ms")
    print("说明: 仅用于开发期趋势观察，不代表最终发布性能。")
    print("=" * 60)

    panel.close()
    app.processEvents()


if __name__ == "__main__":
    run_benchmark(10_000)
