"""
Chunked index writer for CLAP embeddings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np


class ChunkedIndexWriter:
    """增量写入分片索引（manifest + chunk 文件）。"""

    def __init__(self, index_dir: Path, base_name: str = "clap_embeddings", chunk_size: int = 2000):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.base_name = base_name
        self.chunk_size = max(1, int(chunk_size))
        self.meta_path = self.index_dir / f"{self.base_name}_meta.npy"
        self._meta = {"version": 1, "chunk_files": [], "total_count": 0}
        self._load_meta()

    @property
    def meta(self) -> dict:
        return self._meta

    def _load_meta(self) -> None:
        if not self.meta_path.exists():
            return
        try:
            data = np.load(str(self.meta_path), allow_pickle=True)
            meta = data.item() if data.ndim == 0 else {}
            if isinstance(meta, dict) and "chunk_files" in meta:
                self._meta = meta
        except Exception:
            # 若 manifest 损坏则重新开始
            self._meta = {"version": 1, "chunk_files": [], "total_count": 0}

    def append(self, embeddings: Dict[str, np.ndarray]) -> str:
        """追加一个分片并更新 manifest，返回分片路径。"""
        if not embeddings:
            return ""
        chunk_idx = len(self._meta.get("chunk_files", []))
        chunk_path = self.index_dir / f"{self.base_name}_{chunk_idx}.npy"
        np.save(str(chunk_path), embeddings)
        self._meta.setdefault("chunk_files", []).append(chunk_path.name)
        self._meta["total_count"] = int(self._meta.get("total_count", 0)) + len(embeddings)
        np.save(str(self.meta_path), self._meta)
        return str(chunk_path)
