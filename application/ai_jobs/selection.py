"""
Selection helpers for AI jobs and search filtering.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, List

from sqlalchemy import or_, false

from transcriptionist_v3.infrastructure.database.models import AudioFile


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
        patterns: List[str] = []
        for folder in folders:
            p = normalize_path(folder)
            if not p:
                continue
            if not p.endswith(os.sep):
                p += os.sep
            patterns.append(p + "%")
            posix = p.replace("\\", "/")
            if posix != p:
                patterns.append(posix + "%")
        if not patterns:
            return query.filter(false())
        return query.filter(or_(*[AudioFile.file_path.like(p) for p in patterns]))

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
        return query.filter(AudioFile.file_path.in_(list(normalized)))

    return query.filter(false())
