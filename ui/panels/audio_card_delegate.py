from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QEvent, QMargins, QPoint, QRect, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from transcriptionist_v3.core.config import AppConfig
from transcriptionist_v3.ui.themes.theme_tokens import ThemeTokens


class AudioCardDelegate(QStyledItemDelegate):
    """Card delegate for audio rows in QTreeView."""

    DENSITY_COMPACT = "compact"
    DENSITY_STANDARD = "standard"

    STATUS_TEXTS = {
        "translation": {1: "已翻译", 2: "翻译失败"},
    }

    quick_action_requested = Signal(str, str)
    WAVEFORM_POINTS = 192
    WAVEFORM_CACHE_LIMIT = 800
    WAVEFORM_MAX_PENDING = 48
    WAVEFORM_PREFETCH_BATCH = 20
    _WAVEFORM_MISSING = object()

    def __init__(self, tokens: ThemeTokens, parent=None):
        super().__init__(parent)
        self._tokens = tokens
        self._density = self.DENSITY_STANDARD
        self._card_margins = QMargins(12, 7, 12, 7)
        self._radius = 13
        self._hovered_row: int = -1

        self._title_font = QFont()
        self._title_font.setPointSize(11)
        self._title_font.setBold(True)

        self._meta_font = QFont()
        self._meta_font.setPointSize(9)

        self._subtitle_font = QFont(self._meta_font)
        self._subtitle_font.setPointSize(10)

        self._badge_font = QFont()
        self._badge_font.setPointSize(8)

        # 卡片波形：异步缩略图缓存（避免阻塞 UI）
        self._waveform_cache: OrderedDict[str, list[float] | None] = OrderedDict()
        self._waveform_pending: dict[Future, str] = {}
        self._waveform_pending_paths: set[str] = set()
        self._waveform_workers = self._resolve_waveform_workers()
        self._waveform_executor = ThreadPoolExecutor(
            max_workers=self._waveform_workers,
            thread_name_prefix="card-waveform",
        )
        self._waveform_poll_timer = QTimer(self)
        self._waveform_poll_timer.setInterval(80)
        self._waveform_poll_timer.timeout.connect(self._drain_waveform_futures)
        self._waveform_poll_timer.start()

    def _resolve_waveform_workers(self) -> int:
        """读取并规整波形线程数配置。"""
        raw_value = AppConfig.get("performance.waveform_workers", 4)
        try:
            workers = int(raw_value)
        except Exception:
            workers = 4
        return max(1, min(16, workers))

    def update_waveform_workers(self, workers: int | None = None) -> int:
        """运行时更新波形线程数。"""
        if workers is None:
            workers = self._resolve_waveform_workers()
        else:
            workers = max(1, min(16, int(workers)))

        if workers == getattr(self, "_waveform_workers", None):
            return workers

        old_executor = getattr(self, "_waveform_executor", None)
        try:
            if old_executor is not None:
                old_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        self._waveform_pending.clear()
        self._waveform_pending_paths.clear()
        self._waveform_workers = workers
        self._waveform_executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="card-waveform",
        )
        self._refresh_viewport()
        return workers

    def update_tokens(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens

    def set_density(self, density: str) -> None:
        normalized = (density or "").strip().lower()
        if normalized not in {self.DENSITY_COMPACT, self.DENSITY_STANDARD}:
            normalized = self.DENSITY_STANDARD
        self._density = normalized

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        min_height = 78 if self._density == self.DENSITY_COMPACT else 122
        return QSize(base.width(), max(base.height(), min_height))

    def paint(self, painter: QPainter, option, index):
        file_info = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(file_info, dict):
            super().paint(painter, option, index)
            return

        card_rect = option.rect.marginsRemoved(self._card_margins)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if is_selected:
            bg_color = QColor(self._tokens.card_selected)
        elif is_hovered:
            bg_color = QColor(self._tokens.card_hover)
        else:
            bg_color = QColor(self._tokens.card_bg)

        border_color = QColor(self._tokens.card_border)
        if is_selected:
            border_color = QColor(self._with_alpha(self._tokens.accent, 0.72))
        elif is_hovered:
            border_color = QColor(self._with_alpha(self._tokens.accent, 0.42))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        shadow_rect = card_rect.adjusted(0, 1, 0, 1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._with_alpha("#000000", 0.18 if is_selected else 0.10)))
        painter.drawRoundedRect(shadow_rect, self._radius, self._radius)

        painter.setPen(QPen(border_color, 1.2 if (is_selected or is_hovered) else 1))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(card_rect, self._radius, self._radius)

        if is_selected or is_hovered:
            accent = self._with_alpha(self._tokens.accent, 0.75 if is_selected else 0.45)
            marker_rect = QRect(card_rect.left() + 2, card_rect.top() + 8, 3, max(16, card_rect.height() - 16))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(accent))
            painter.drawRoundedRect(marker_rect, 2, 2)

            top_glow = QRect(card_rect.left() + 8, card_rect.top() + 1, max(16, card_rect.width() - 16), 2)
            painter.setBrush(QColor(self._with_alpha(self._tokens.accent, 0.22 if is_selected else 0.12)))
            painter.drawRoundedRect(top_glow, 1, 1)

        if file_info.get("__skeleton__"):
            self._paint_skeleton(painter, card_rect)
        elif self._density == self.DENSITY_COMPACT:
            self._paint_compact(painter, card_rect, index, file_info, is_selected)
        else:
            self._paint_standard(painter, card_rect, index, file_info, is_selected)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event is None:
            return super().editorEvent(event, model, option, index)
        if event.type() != QEvent.Type.MouseButtonRelease:
            return super().editorEvent(event, model, option, index)
        if getattr(event, "button", lambda: Qt.MouseButton.NoButton)() != Qt.MouseButton.LeftButton:
            return super().editorEvent(event, model, option, index)

        file_info = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(file_info, dict):
            return super().editorEvent(event, model, option, index)
        if file_info.get("__skeleton__"):
            return super().editorEvent(event, model, option, index)

        file_path = str(file_info.get("file_path") or "").strip()
        if not file_path:
            return super().editorEvent(event, model, option, index)

        click_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        content = self._content_rect(option.rect.marginsRemoved(self._card_margins))
        compact = self._density == self.DENSITY_COMPACT

        preview_rect = self._build_preview_icon_rect(content, compact)
        if self._hovered_row == index.row() and preview_rect.contains(click_pos):
            self.quick_action_requested.emit("play", file_path)
            return True

        return super().editorEvent(event, model, option, index)

    def _paint_standard(self, painter: QPainter, rect: QRect, index, file_info: dict, is_selected: bool):
        content = self._content_rect(rect)
        icon_slot_width = 28
        text_left = content.left() + icon_slot_width

        right_panel_width = min(220, int(content.width() * 0.34))
        text_width = max(146, content.width() - right_panel_width - icon_slot_width - 16)

        title_rect = QRect(text_left, content.top(), text_width, 24)
        subtitle_rect = QRect(text_left, content.top() + 26, text_width, 18)
        waveform_rect = QRect(text_left, content.top() + 46, text_width, 24)
        tag_rect = QRect(text_left, content.top() + 72, text_width, 16)
        right_meta_rect = QRect(content.right() - right_panel_width, content.top() + 49, right_panel_width, 18)

        filename = file_info.get("filename") or Path(file_info.get("file_path", "")).name
        translated_name = file_info.get("translated_name") or ""
        tags = file_info.get("tags") or []
        duration = index.siblingAtColumn(3).data(Qt.ItemDataRole.DisplayRole) or "-"
        fmt = index.siblingAtColumn(5).data(Qt.ItemDataRole.DisplayRole) or "-"

        title_text = translated_name or filename
        subtitle_text = self._build_subtitle_text(file_info)
        tags_text = self._build_tags_text(tags, 3)
        right_text = f"{duration} · {fmt}"

        painter.setFont(self._title_font)
        title_metrics = painter.fontMetrics()
        title_elided = title_metrics.elidedText(str(title_text), Qt.TextElideMode.ElideRight, title_rect.width())
        painter.setPen(QColor(self._tokens.text_primary))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title_elided)

        painter.setFont(self._subtitle_font)
        meta_metrics = painter.fontMetrics()
        subtitle_elided = meta_metrics.elidedText(subtitle_text, Qt.TextElideMode.ElideMiddle, subtitle_rect.width())
        painter.setPen(QColor(self._with_alpha(self._tokens.text_secondary, 0.92)))
        painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, subtitle_elided)

        divider_y = subtitle_rect.bottom() + 4
        painter.setPen(QPen(QColor(self._with_alpha(self._tokens.border, 0.62)), 1))
        painter.drawLine(text_left, divider_y, content.right() - 6, divider_y)

        self._paint_waveform_strip(painter, waveform_rect, file_info)

        painter.setFont(self._meta_font)
        meta_metrics = painter.fontMetrics()
        tags_elided = meta_metrics.elidedText(f"标签: {tags_text}", Qt.TextElideMode.ElideRight, tag_rect.width())
        tag_color = self._tokens.text_secondary if tags else self._tokens.text_muted
        painter.setPen(QColor(tag_color))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tags_elided)

        right_elided = meta_metrics.elidedText(right_text, Qt.TextElideMode.ElideLeft, right_meta_rect.width() - 6)
        self._draw_meta_chip(painter, right_meta_rect, right_elided)

        self._paint_status_badges(painter, content, file_info, compact=False)
        self._paint_preview_icon(painter, content, index.row(), compact=False)

    def _paint_compact(self, painter: QPainter, rect: QRect, index, file_info: dict, is_selected: bool):
        content = self._content_rect(rect)
        icon_slot_width = 24
        text_left = content.left() + icon_slot_width

        right_panel_width = min(176, int(content.width() * 0.32))
        text_width = max(120, content.width() - right_panel_width - icon_slot_width - 12)

        title_rect = QRect(text_left, content.top(), text_width, 18)
        waveform_rect = QRect(text_left, content.top() + 20, text_width, 14)
        tag_rect = QRect(text_left, content.top() + 36, text_width, 12)
        right_meta_rect = QRect(content.right() - right_panel_width, content.top() + 11, right_panel_width, 16)

        filename = file_info.get("filename") or Path(file_info.get("file_path", "")).name
        translated_name = file_info.get("translated_name") or ""
        tags = file_info.get("tags") or []
        duration = index.siblingAtColumn(3).data(Qt.ItemDataRole.DisplayRole) or "-"
        fmt = index.siblingAtColumn(5).data(Qt.ItemDataRole.DisplayRole) or "-"

        title_text = translated_name or filename
        tags_text = self._build_tags_text(tags, 2)
        right_text = f"{duration} · {fmt}"

        painter.setFont(self._title_font)
        title_metrics = painter.fontMetrics()
        title_elided = title_metrics.elidedText(str(title_text), Qt.TextElideMode.ElideRight, title_rect.width())
        painter.setPen(QColor(self._tokens.text_primary))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title_elided)

        painter.setFont(self._meta_font)
        meta_metrics = painter.fontMetrics()
        self._paint_waveform_strip(painter, waveform_rect, file_info, compact=True)
        tags_elided = meta_metrics.elidedText(f"标签: {tags_text}", Qt.TextElideMode.ElideRight, tag_rect.width())
        tag_color = self._tokens.text_secondary if tags else self._tokens.text_muted
        painter.setPen(QColor(tag_color))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tags_elided)

        right_elided = meta_metrics.elidedText(right_text, Qt.TextElideMode.ElideLeft, right_meta_rect.width() - 6)
        self._draw_meta_chip(painter, right_meta_rect, right_elided)

        self._paint_status_badges(painter, content, file_info, compact=True)
        self._paint_preview_icon(painter, content, index.row(), compact=True)

    def _paint_preview_icon(self, painter: QPainter, content: QRect, row: int, compact: bool):
        if row != self._hovered_row:
            return

        icon_rect = self._build_preview_icon_rect(content, compact)
        icon_size = icon_rect.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._with_alpha(self._tokens.accent, 0.26)))
        painter.drawEllipse(icon_rect)

        p1 = QPoint(icon_rect.left() + icon_size // 3, icon_rect.top() + icon_size // 4)
        p2 = QPoint(icon_rect.left() + icon_size // 3, icon_rect.bottom() - icon_size // 4)
        p3 = QPoint(icon_rect.right() - icon_size // 4, icon_rect.center().y())
        painter.setBrush(QColor(self._tokens.accent))
        painter.drawPolygon(QPolygon([p1, p2, p3]))

    def _paint_waveform_strip(self, painter: QPainter, rect: QRect, file_info: dict, compact: bool = False):
        path_value = str(file_info.get("file_path") or "").strip()
        if not path_value:
            return

        peaks = self._get_waveform_peaks(path_value)
        strip_rect = rect.adjusted(0, 0, 0, 0)
        if strip_rect.width() <= 2 or strip_rect.height() <= 2:
            return

        baseline = strip_rect.center().y()
        painter.setPen(QPen(QColor(self._with_alpha(self._tokens.border, 0.30)), 1))
        painter.drawLine(strip_rect.left(), baseline, strip_rect.right(), baseline)

        if peaks is self._WAVEFORM_MISSING:
            self._request_waveform(path_value)
            painter.setPen(QPen(QColor(self._with_alpha(self._tokens.text_muted, 0.40)), 1))
            dots = max(8, min(24, strip_rect.width() // 12))
            step = max(4, strip_rect.width() // max(1, dots))
            for idx in range(dots):
                x = strip_rect.left() + idx * step
                painter.drawPoint(x, baseline)
            return

        if peaks is None:
            return

        if len(peaks) <= 0:
            return

        profile: list[tuple[float, float]] = []
        first_value = peaks[0]
        if isinstance(first_value, tuple) and len(first_value) >= 2:
            profile = [(max(0.0, min(1.0, float(a))), max(0.0, min(1.0, float(b)))) for a, b in peaks]  # type: ignore[misc]
        else:
            profile = [(max(0.0, min(1.0, float(v))), 0.5) for v in peaks]  # type: ignore[arg-type]

        render_points = max(72, min(360, strip_rect.width() // (2 if compact else 2)))
        if len(profile) == render_points:
            sampled = [(item[0], item[0], item[1]) for item in profile]
        else:
            sampled: list[tuple[float, float, float]] = []
            step = len(profile) / float(render_points)
            for idx in range(render_points):
                start = int(idx * step)
                end = int((idx + 1) * step)
                if end <= start:
                    end = start + 1
                segment = profile[start:end]
                if not segment:
                    sampled.append((0.0, 0.0, 0.5))
                    continue
                amp_value = max(item[0] for item in segment)
                amp_floor = min(item[0] for item in segment)
                bias_value = sum(item[1] for item in segment) / float(len(segment))
                sampled.append((amp_value, amp_floor, max(0.0, min(1.0, bias_value))))

        amplitude = max(3.0, (strip_rect.height() - 1) / 2.0)
        x_step = strip_rect.width() / max(1, len(sampled) - 1)

        if len(sampled) < 2:
            return

        painter.setBrush(Qt.BrushStyle.NoBrush)
        body_color = QColor(self._with_alpha(self._tokens.accent, 0.30))
        crest_color = QColor(self._with_alpha(self._tokens.accent, 0.92))

        for idx, (peak, floor, band_bias) in enumerate(sampled):
            x = strip_rect.left() + int(idx * x_step)
            value = max(0.0, min(1.0, float(peak)))
            low_weight = max(0.0, (band_bias - 0.5) * 2.0)
            high_weight = max(0.0, (0.5 - band_bias) * 2.0)
            h = max(1.0, value * amplitude * (1.00 + low_weight * 0.05 - high_weight * 0.03))
            floor_value = max(0.0, min(value, float(floor)))
            floor_h = max(0.5, floor_value * amplitude)

            y_top = int(baseline - h)
            y_bottom = int(baseline + h)
            body_top = int(baseline - floor_h)
            body_bottom = int(baseline + floor_h)

            if body_bottom > body_top:
                painter.setPen(QPen(body_color, 1))
                painter.drawLine(x, body_top, x, body_bottom)

            local_width = 2 if (not compact and low_weight > 0.42) else 1
            painter.setPen(QPen(crest_color, local_width))
            painter.drawLine(x, y_top, x, y_bottom)

        painter.setPen(QPen(QColor(self._with_alpha(self._tokens.border, 0.38)), 1))
        painter.drawLine(strip_rect.left(), baseline, strip_rect.right(), baseline)

    def _paint_skeleton(self, painter: QPainter, rect: QRect):
        content = self._content_rect(rect)
        painter.setPen(Qt.PenStyle.NoPen)

        base = QColor(self._with_alpha(self._tokens.text_secondary, 0.18))
        short = QColor(self._with_alpha(self._tokens.text_secondary, 0.10))
        painter.setBrush(base)
        painter.drawRoundedRect(QRect(content.left(), content.top() + 2, min(content.width() - 40, 340), 14), 6, 6)
        painter.drawRoundedRect(QRect(content.left(), content.top() + 22, min(content.width() - 120, 260), 12), 6, 6)
        painter.setBrush(short)
        painter.drawRoundedRect(QRect(content.left(), content.top() + 42, min(content.width() - 80, 300), 10), 5, 5)

    def _get_waveform_peaks(self, file_path: str):
        if not hasattr(self, "_waveform_cache"):
            self._waveform_cache = OrderedDict()
        cached = self._waveform_cache.get(file_path, self._WAVEFORM_MISSING)
        if cached is not self._WAVEFORM_MISSING:
            self._waveform_cache.move_to_end(file_path, last=True)
        return cached

    def _request_waveform(self, file_path: str) -> None:
        if not hasattr(self, "_waveform_pending_paths"):
            self._waveform_pending_paths = set()
        if not hasattr(self, "_waveform_pending"):
            self._waveform_pending = {}
        if not hasattr(self, "_waveform_executor"):
            workers = self._resolve_waveform_workers()
            self._waveform_workers = workers
            self._waveform_executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="card-waveform")

        if file_path in self._waveform_pending_paths:
            return
        if len(self._waveform_pending_paths) >= self.WAVEFORM_MAX_PENDING:
            return
        self._waveform_pending_paths.add(file_path)
        future = self._waveform_executor.submit(self._extract_waveform_peaks, file_path, self.WAVEFORM_POINTS)
        self._waveform_pending[future] = file_path

    def prefetch_waveforms(self, file_paths: list[str], limit: int | None = None) -> None:
        # Prefetch waveform cache for visible rows.
        if not file_paths:
            return

        remaining = self.WAVEFORM_MAX_PENDING - len(self._waveform_pending_paths)
        if remaining <= 0:
            return

        batch_limit = self.WAVEFORM_PREFETCH_BATCH if limit is None else max(1, int(limit))
        request_limit = min(batch_limit, remaining)
        if request_limit <= 0:
            return

        seen: set[str] = set()
        requested = 0
        for raw_path in file_paths:
            path_value = str(raw_path or "").strip()
            if not path_value or path_value in seen:
                continue
            seen.add(path_value)

            cached = self._waveform_cache.get(path_value, self._WAVEFORM_MISSING)
            if cached is not self._WAVEFORM_MISSING:
                self._waveform_cache.move_to_end(path_value, last=True)
                continue
            if path_value in self._waveform_pending_paths:
                continue

            self._request_waveform(path_value)
            requested += 1
            if requested >= request_limit:
                break

    def _drain_waveform_futures(self) -> None:
        if not self._waveform_pending:
            return
        done = [future for future in list(self._waveform_pending.keys()) if future.done()]
        if not done:
            return

        updated_paths: set[str] = set()

        for future in done:
            file_path = self._waveform_pending.pop(future, "")
            if file_path:
                self._waveform_pending_paths.discard(file_path)
            try:
                peaks = future.result()
            except Exception:
                peaks = None

            if file_path:
                self._waveform_cache[file_path] = peaks
                if len(self._waveform_cache) > self.WAVEFORM_CACHE_LIMIT:
                    self._waveform_cache.popitem(last=False)
                updated_paths.add(file_path)

        self._refresh_viewport(updated_paths)

    def _refresh_viewport(self, updated_paths: set[str] | None = None) -> None:
        parent = self.parent()
        try:
            if parent is not None and hasattr(parent, "file_view"):
                if updated_paths:
                    self._refresh_visible_rows_for_paths(parent.file_view, updated_paths)
                    return
                parent.file_view.viewport().update()
                return
            if parent is not None and hasattr(parent, "viewport"):
                parent.viewport().update()
        except Exception:
            return

    def _refresh_visible_rows_for_paths(self, file_view, updated_paths: set[str]) -> None:
        viewport = file_view.viewport()
        model = file_view.model()
        if model is None:
            viewport.update()
            return

        row_count = model.rowCount()
        if row_count <= 0:
            return

        probe_x = min(max(6, viewport.width() // 4), max(6, viewport.width() - 6))
        top_index = file_view.indexAt(QPoint(probe_x, 6))
        bottom_index = file_view.indexAt(QPoint(probe_x, max(6, viewport.height() - 6)))

        start_row = top_index.row() if top_index.isValid() else 0
        end_row = bottom_index.row() if bottom_index.isValid() else min(row_count - 1, start_row + 24)
        if end_row < start_row:
            start_row, end_row = end_row, start_row

        refreshed = False
        refresh_count = 0
        for row in range(start_row, end_row + 1):
            index = model.index(row, 0)
            if not index.isValid():
                continue

            file_info = model.data(index, Qt.ItemDataRole.UserRole)
            if not isinstance(file_info, dict):
                continue
            file_path = str(file_info.get("file_path") or "").strip()
            if not file_path or file_path not in updated_paths:
                continue

            rect = file_view.visualRect(index)
            if rect.isValid():
                viewport.update(rect.adjusted(-2, -1, 2, 1))
            else:
                viewport.update()
            refreshed = True
            refresh_count += 1
            if refresh_count >= 8:
                viewport.update()
                return

        if not refreshed:
            viewport.update()

    @staticmethod
    def _extract_waveform_peaks(file_path: str, points: int) -> list[tuple[float, float]] | None:
        """Extract waveform peaks in background thread."""
        try:
            path_obj = Path(file_path)
            if not path_obj.exists() or not path_obj.is_file():
                return None

            peaks: list[tuple[float, float]] = []

            try:
                import soundfile as sf  # type: ignore
                import numpy as np  # type: ignore

                with sf.SoundFile(str(path_obj)) as sound_file:
                    total_frames = int(len(sound_file))
                    if total_frames <= 0:
                        return None
                    block_size = max(1024, total_frames // max(points, 1))
                    for block in sound_file.blocks(blocksize=block_size, dtype="float32", always_2d=True):
                        if block is None or len(block) == 0:
                            continue
                        mono = block.mean(axis=1)
                        abs_mono = np.abs(mono)
                        peak = float(np.max(abs_mono))
                        rms = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) else 0.0

                        spectrum = np.fft.rfft(mono)
                        mag = np.abs(spectrum)
                        if mag.size > 0:
                            split1 = max(1, int(mag.size * 0.18))
                            split2 = max(split1 + 1, int(mag.size * 0.62))
                            low_energy = float(np.mean(mag[:split1])) if split1 > 0 else 0.0
                            mid_energy = float(np.mean(mag[split1:split2])) if split2 > split1 else 0.0
                            high_energy = float(np.mean(mag[split2:])) if mag.size > split2 else 0.0
                            freq_total = low_energy + mid_energy + high_energy + 1e-9
                            low_ratio = low_energy / freq_total
                            high_ratio = high_energy / freq_total
                            band_bias = 0.5 + (low_ratio - high_ratio) * 0.5
                            band_bias = max(0.0, min(1.0, band_bias))
                        else:
                            band_bias = 0.5

                        mixed = (peak * 0.56) + (rms * 0.34) + (abs(peak - rms) * 0.10)
                        peaks.append((mixed, band_bias))
                if peaks:
                    return AudioCardDelegate._normalize_peaks(peaks, points)
            except Exception:
                pass

            # 兜底：仅 WAV（标准库）
            if path_obj.suffix.lower() != ".wav":
                return None
            try:
                import wave
                import struct

                with wave.open(str(path_obj), "rb") as wav:
                    channels = wav.getnchannels()
                    sample_width = wav.getsampwidth()
                    total_frames = wav.getnframes()
                    if total_frames <= 0 or channels <= 0:
                        return None

                    frames_per_chunk = max(1024, total_frames // max(points, 1))
                    while True:
                        raw = wav.readframes(frames_per_chunk)
                        if not raw:
                            break
                        if sample_width == 1:
                            fmt = f"{len(raw)}B"
                            values = struct.unpack(fmt, raw)
                            # uint8 -> centered int
                            mono = [abs(v - 128) for v in values[::channels]]
                        elif sample_width == 2:
                            fmt = f"{len(raw) // 2}h"
                            values = struct.unpack(fmt, raw)
                            mono = [abs(v) for v in values[::channels]]
                        else:
                            return None
                        if mono:
                            peak = float(max(mono))
                            avg = float(sum(mono) / len(mono)) if mono else 0.0
                            mixed = (peak * 0.72) + (avg * 0.28)
                            peaks.append((mixed, 0.5))
                if peaks:
                    return AudioCardDelegate._normalize_peaks(peaks, points)
            except Exception:
                return None
        except Exception:
            return None
        return None

    @staticmethod
    def _normalize_peaks(peaks: list[tuple[float, float]], points: int) -> list[tuple[float, float]]:
        if not peaks:
            return []

        amplitudes = [float(max(0.0, value[0])) for value in peaks]
        biases = [max(0.0, min(1.0, float(value[1]))) for value in peaks]

        sorted_peaks = sorted(amplitudes)
        peak_p95 = sorted_peaks[int((len(sorted_peaks) - 1) * 0.95)] if sorted_peaks else 0.0
        peak_scale = peak_p95 if peak_p95 > 0 else (max(sorted_peaks) if sorted_peaks else 0.0)

        if peak_scale > 0:
            amplitudes = [min(1.0, max(0.0, float(value)) / peak_scale) for value in amplitudes]
        else:
            amplitudes = [0.0 for _ in amplitudes]

        paired = list(zip(amplitudes, biases))

        if len(paired) <= points:
            sampled = list(paired)
        else:
            sampled: list[tuple[float, float]] = []
            step = len(paired) / float(points)
            for idx in range(points):
                start = int(idx * step)
                end = int((idx + 1) * step)
                if end <= start:
                    end = start + 1
                segment = paired[start:end]
                if not segment:
                    sampled.append((0.0, 0.5))
                    continue
                amp = max(item[0] for item in segment)
                bias = sum(item[1] for item in segment) / float(len(segment))
                sampled.append((amp, bias))

        if len(sampled) <= 2:
            return sampled

        smoothed: list[tuple[float, float]] = []
        for idx, (amp, bias) in enumerate(sampled):
            prev_amp, prev_bias = sampled[idx - 1] if idx > 0 else (amp, bias)
            next_amp, next_bias = sampled[idx + 1] if idx < len(sampled) - 1 else (amp, bias)

            amp_smoothed = (prev_amp * 0.10) + (amp * 0.80) + (next_amp * 0.10)
            bias_smoothed = (prev_bias * 0.18) + (bias * 0.64) + (next_bias * 0.18)
            amp_out = max(0.0, min(1.0, amp_smoothed))
            smoothed.append((amp_out, max(0.0, min(1.0, bias_smoothed))))

        return smoothed

    def _build_preview_icon_rect(self, content: QRect, compact: bool) -> QRect:
        icon_size = 16 if compact else 18
        x = content.left() + (20 - icon_size) // 2
        return QRect(x, content.center().y() - icon_size // 2, icon_size, icon_size)

    def set_hovered_row(self, row: int):
        self._hovered_row = row

    def _paint_status_badges(self, painter: QPainter, content: QRect, file_info: dict, compact: bool):
        badges = self._build_badges(file_info)
        if not badges:
            return

        painter.setFont(self._badge_font)
        metrics = painter.fontMetrics()
        badge_height = 16 if compact else 18
        spacing = 6
        x = content.right() - 2
        y = content.top() + (0 if compact else 1)

        for text_value, fg, bg in reversed(badges):
            text_width = metrics.horizontalAdvance(text_value)
            badge_width = text_width + (12 if compact else 14)
            x -= badge_width
            badge_rect = QRect(x, y, badge_width, badge_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(badge_rect, badge_height // 2, badge_height // 2)
            painter.setPen(QColor(fg))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text_value)
            x -= spacing

    def _build_badges(self, file_info: dict):
        badges = []
        translation_badge = self._build_translation_badge(file_info)
        if translation_badge is not None:
            badges.append(translation_badge)

        tags = file_info.get("tags") or []
        if tags:
            badges.append(("已打标", self._tokens.success, self._with_alpha(self._tokens.success, 0.12)))
        return badges

    def _build_translation_badge(self, file_info: dict):
        raw_value = file_info.get("translation_status")
        try:
            value = int(raw_value)
        except Exception:
            value = 0

        text_value = self.STATUS_TEXTS.get("translation", {}).get(value)
        if text_value is None:
            return None
        if value == 1:
            return text_value, self._tokens.success, self._with_alpha(self._tokens.success, 0.12)
        if value == 2:
            return text_value, self._tokens.danger, self._with_alpha(self._tokens.danger, 0.12)
        return None

    def _draw_meta_chip(self, painter: QPainter, rect: QRect, text_value: str):
        text_width = painter.fontMetrics().horizontalAdvance(text_value)
        chip_width = min(rect.width(), text_width + 18)
        chip_rect = QRect(rect.right() - chip_width, rect.top(), chip_width, rect.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._with_alpha(self._tokens.surface_1, 0.92)))
        painter.drawRoundedRect(chip_rect, chip_rect.height() // 2, chip_rect.height() // 2)
        painter.setPen(QColor(self._tokens.text_secondary))
        painter.drawText(chip_rect.adjusted(0, 0, -1, 0), Qt.AlignmentFlag.AlignCenter, text_value)

    def _content_rect(self, card_rect: QRect) -> QRect:
        if self._density == self.DENSITY_COMPACT:
            return card_rect.adjusted(14, 10, -14, -10)
        return card_rect.adjusted(14, 11, -14, -11)

    @staticmethod
    def _build_subtitle_text(file_info: dict) -> str:
        file_path = str(file_info.get("file_path") or "").strip()
        if not file_path:
            return "-"
        path_obj = Path(file_path)
        parent = str(path_obj.parent)
        return parent if parent else file_path

    @staticmethod
    def _build_tags_text(tags, limit: int) -> str:
        if not tags:
            return "未打标签"
        values = [str(tag) for tag in tags[:limit]]
        text_value = " · ".join(values)
        if len(tags) > limit:
            text_value = f"{text_value} +{len(tags) - limit}"
        return text_value

    @staticmethod
    def _with_alpha(hex_color: str, alpha: float) -> str:
        alpha_int = max(0, min(255, int(alpha * 255)))
        return f"{hex_color}{alpha_int:02X}"

    def __del__(self):
        try:
            self._waveform_poll_timer.stop()
        except Exception:
            pass
        try:
            self._waveform_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

