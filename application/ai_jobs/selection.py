"""
Selection helpers for AI jobs and search filtering.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, List

from sqlalchemy import or_, false, select, union_all

from transcriptionist_v3.infrastructure.database.models import AudioFile


SQLITE_IN_SAFE_BATCH = 500
SQLITE_OR_SAFE_CHUNK = 100


def normalize_path(path: str) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(path))


def _normalize_paths(paths: Iterable[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        n = normalize_path(p)
        if n:
            out.append(n)
    return out


def _folder_prefixes(folders: Iterable[str]) -> List[str]:
    prefixes: List[str] = []
    for folder in folders:
        p = normalize_path(folder)
        if not p:
            continue
        if not p.endswith(os.sep):
            p += os.sep
        prefixes.append(p)
    return prefixes


def _chunked(values: List[str], size: int) -> List[List[str]]:
    if size <= 0:
        return [values]
    return [values[i : i + size] for i in range(0, len(values), size)]


def _compress_prefixes(prefixes: Iterable[str]) -> List[str]:
    """压缩前缀集合：若子路径已被父路径覆盖则移除子路径。"""
    unique = sorted(set(p for p in prefixes if p), key=lambda x: (len(x), x))
    if not unique:
        return []

    kept: List[str] = []
    for current in unique:
        covered = False
        for parent in kept:
            if current.startswith(parent):
                covered = True
                break
        if not covered:
            kept.append(current)
    return kept


def _build_or_in_filter(values: List[str]):
    chunks = _chunked(values, SQLITE_IN_SAFE_BATCH)
    clauses = [AudioFile.file_path.in_(chunk) for chunk in chunks if chunk]
    if not clauses:
        return false()
    if len(clauses) == 1:
        return clauses[0]
    return or_(*clauses)


def _build_like_filter(patterns: List[str]):
    """
    构建 LIKE 过滤。
    - 小规模直接 OR。
    - 大规模使用分块 UNION，规避 SQLite expression tree 深度限制。
    """
    chunk_clauses = []
    for chunk in _chunked(patterns, SQLITE_OR_SAFE_CHUNK):
        if not chunk:
            continue
        chunk_clauses.append(or_(*[AudioFile.file_path.like(pattern) for pattern in chunk]))

    if not chunk_clauses:
        return false()
    if len(chunk_clauses) == 1:
        return chunk_clauses[0]

    # 分块子查询后 UNION，避免超长 OR 树
    selects = [select(AudioFile.id).where(clause) for clause in chunk_clauses]
    id_union = union_all(*selects).subquery()
    return AudioFile.id.in_(select(id_union.c.id))


class SelectionFilter:
    """基于 selection dict 的快速匹配器。"""

    def __init__(self, selection: dict | None):
        selection = selection or {}
        self.mode = selection.get("mode") or "none"
        self._file_set = set()
        self._prefixes: List[str] = []

        if self.mode == "files":
            files = _normalize_paths(selection.get("files") or [])
            self._file_set = set(files)
        elif self.mode == "folders":
            self._prefixes = _folder_prefixes(selection.get("folders") or [])

    def matches(self, path_str: str) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "files":
            return normalize_path(path_str) in self._file_set
        if self.mode == "folders":
            norm = normalize_path(path_str)
            for prefix in self._prefixes:
                if norm.startswith(prefix):
                    return True
            return False
        return False


def apply_selection_filters(query, selection: dict | None):
    """将 selection 规则转为 SQLAlchemy 过滤条件。"""
    selection = selection or {}
    mode = selection.get("mode") or "none"

    if mode == "all":
        return query

    if mode == "folders":
        folders = selection.get("folders") or []
        prefixes: List[str] = []
        for folder in folders:
            p = normalize_path(folder)
            if not p:
                continue
            if not p.endswith(os.sep):
                p += os.sep
            prefixes.append(p)
            posix = p.replace("\\", "/")
            if posix != p:
                prefixes.append(posix)
        prefixes = _compress_prefixes(prefixes)
        patterns = [prefix + "%" for prefix in prefixes]
        if not patterns:
            return query.filter(false())
        return query.filter(_build_like_filter(patterns))

    if mode == "files":
        files = selection.get("files") or []
        if not files:
            return query.filter(false())
        normalized = set()
        for f in files:
            n = normalize_path(f)
            if not n:
                continue
            normalized.add(n)
            posix = n.replace("\\", "/")
            normalized.add(posix)
        return query.filter(_build_or_in_filter(list(normalized)))

    return query.filter(false())
