"""
在线资源页面 - Freesound等在线音效资源
连接到后端 FreesoundClient 和 FreesoundSearchService
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote_plus
import requests
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QThread, QUrl, QTimer, QRect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout,
    QSizePolicy, QFrame
)
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QPainter, QColor, QPen
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from qfluentwidgets import (
    ScrollArea, PrimaryPushButton, PushButton, SearchLineEdit, LineEdit,
    FluentIcon, CardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, CaptionLabel, IconWidget, ElevatedCardWidget,
    TransparentToolButton, InfoBar, InfoBarPosition,
    ProgressBar, ComboBox, SpinBox, ToolButton, FlowLayout, isDarkTheme
)

from transcriptionist_v3.ui.themes.theme_tokens import get_theme_tokens

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundClient, FreesoundSearchService, FreesoundSettings,
    FreesoundSound, FreesoundSearchResult, FreesoundSearchOptions,
    FreesoundError, FreesoundAuthError
)

logger = logging.getLogger(__name__)


class SearchWorker(QThread):
    """后台搜索线程"""
    finished = Signal(object)  # FreesoundSearchResult or Exception
    
    def __init__(
        self,
        api_key: str,
        query: str,
        page: int = 1,
        page_size: int = 15,
        group_by_pack: bool = False,
        search_mode: str = "text",
        source_sound_id: Optional[int] = None,
        source_pack_id: Optional[int] = None,
    ):
        super().__init__()
        self.api_key = api_key
        self.query = query
        self.page = page
        self.page_size = page_size
        self.group_by_pack = group_by_pack
        self.search_mode = search_mode
        self.source_sound_id = source_sound_id
        self.source_pack_id = source_pack_id
    
    def _build_translate_func(self):
        """构建翻译函数（统一走同步实现）。"""
        return self._build_translate_func_sync()

    def _build_translate_func_sync(self):
        """构建线程内同步翻译函数，避免事件循环嵌套。"""
        from transcriptionist_v3.core.config import AppConfig as _AppConfig

        model_configs = {
            0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
            1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        }

        def _extract_text(payload: Dict[str, Any]) -> str:
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not isinstance(choices, list) or not choices:
                return ""
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if not isinstance(message, dict):
                return ""
            content = message.get("content", "")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                chunks: List[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text_part = item.get("text")
                        if isinstance(text_part, str) and text_part.strip():
                            chunks.append(text_part.strip())
                return "\n".join(chunks).strip()
            return ""

        def translate(text: str) -> str:
            if not text:
                return text

            api_key = str(_AppConfig.get("ai.api_key", "") or "").strip()
            if not api_key:
                return text

            model_idx = int(_AppConfig.get("ai.model_index", 0) or 0)
            config = model_configs.get(model_idx, model_configs[0])
            has_zh = bool(re.search(r"[\u4e00-\u9fff]", text))
            target_lang = "en" if has_zh else "zh"

            if target_lang == "en":
                system_prompt = (
                    "You are a translator for Freesound search. "
                    "Translate each input line from Chinese to concise English keywords. "
                    "Keep line order and output only translated lines."
                )
            else:
                system_prompt = (
                    "你是专业音效名称翻译助手。"
                    "将英文音效名称或短描述翻译为简洁自然的简体中文。"
                    "逐行翻译，保持行数和顺序，不要添加解释。"
                )

            endpoint = f"{str(config['base_url']).rstrip('/')}/chat/completions"
            payload = {
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.2,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=(6, 25))
                resp.raise_for_status()
                translated = _extract_text(resp.json())
                return translated or text
            except Exception as exc:
                logger.error(f"General model translate failed in Freesound search: {exc}")
                return text

        return translate
    
    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._search())
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"Search error: {e}")
            self.finished.emit(e)
    
    async def _search(self):
        """
        使用 FreesoundSearchService 进行搜索，并接入统一翻译逻辑：
        - 中文查询自动翻译为英文再搜索（HY-MT 优先）
        - 英文结果名称自动翻译为中文展示（HY-MT 优先）
        """
        # 构建简单的 FreesoundSettings（后续如有更多设置可从 AppConfig 扩展）
        settings = FreesoundSettings(
            api_token=self.api_key,
            download_path="",
            auto_add_to_library=True,
            auto_translate_and_rename=False,
            keep_original_name=False,
            show_license_confirm=True,
            auto_translate_search=True,
            auto_translate_results=True,
            page_size=self.page_size,
            max_concurrent_downloads=3,
        )
        
        # 构建统一翻译函数（优先 HY-MT1.5）
        translate_func = self._build_translate_func_sync()
        
        async with FreesoundClient(self.api_key) as client:
            service = FreesoundSearchService(
                client=client,
                settings=settings,
                translate_func=translate_func,
            )
            if self.search_mode == "similar":
                if not self.source_sound_id:
                    raise FreesoundError("缺少相似搜索的 sound_id")
                sounds = await service.get_similar(self.source_sound_id, limit=self.page_size)
                return FreesoundSearchResult(
                    count=len(sounds),
                    results=sounds,
                    next_page=None,
                    previous_page=None,
                    current_page=1,
                    total_pages=1,
                )

            if self.search_mode == "pack":
                if not self.source_pack_id:
                    raise FreesoundError("缺少合集搜索的 pack_id")
                result = await client.get_pack_sounds(
                    self.source_pack_id,
                    page=self.page,
                    page_size=self.page_size,
                )
                if result.results:
                    result.results = await service._translate_results(result.results)
                return result

            # 使用高级搜索服务（带翻译与缓存）
            return await service.search(
                self.query,
                page=self.page,
                group_by_pack=self.group_by_pack,
            )


class FeaturedPacksWorker(QThread):
    """后台拉取热门合集线程。"""

    finished = Signal(object)  # List[Dict[str, Any]] or Exception

    def __init__(self, api_key: str, limit: int = 8):
        super().__init__()
        self.api_key = api_key
        self.limit = max(1, int(limit))

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._load())
            loop.close()
            self.finished.emit(result)
        except Exception as exc:
            logger.error(f"Featured packs load error: {exc}")
            self.finished.emit(exc)

    async def _load(self):
        async with FreesoundClient(self.api_key) as client:
            return await client.get_trending_packs(limit=self.limit)


class PackTranslationWorker(QThread):
    """后台翻译热门合集标题和描述。"""

    finished = Signal(object)  # List[Dict[str, Any]]

    def __init__(self, packs: List[Dict[str, Any]], translate_func):
        super().__init__()
        self.packs = packs
        self.translate_func = translate_func

    def run(self):
        if not self.translate_func:
            self.finished.emit(self.packs)
            return

        translated: List[Dict[str, Any]] = []
        for item in self.packs:
            current = dict(item)
            try:
                title = str(current.get('title', '') or '').strip()
                desc = str(current.get('desc', '') or '').strip()
                if title and not re.search(r'[\u4e00-\u9fff]', title):
                    current['title'] = self.translate_func(title)
                if desc and not re.search(r'[\u4e00-\u9fff]', desc):
                    current['desc'] = self.translate_func(desc)
            except Exception as exc:
                logger.debug(f"pack translation failed: {exc}")
            translated.append(current)
        self.finished.emit(translated)


class SoundCard(ElevatedCardWidget):
    """音效卡片 - 显示单个搜索结果（支持响应式密度）"""

    play_clicked = Signal(str)
    download_clicked = Signal(object)
    send_to_translate = Signal(object)
    find_similar = Signal(object)
    open_pack = Signal(int)

    def __init__(self, sound: FreesoundSound, parent=None):
        super().__init__(parent)
        self.sound = sound
        self._compact_mode = False
        self._narrow_mode = False
        self._waveform_reply = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._init_ui()
        self.set_compact_mode(False, False)

    def _init_ui(self):
        self.card_layout = QHBoxLayout(self)
        self.card_layout.setContentsMargins(12, 8, 12, 8)
        self.card_layout.setSpacing(10)

        self.play_btn = ToolButton(FluentIcon.PLAY)
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self._on_play)
        self.card_layout.addWidget(self.play_btn)

        self.waveform_label = CaptionLabel("")
        self.waveform_label.setFixedSize(140, 40)
        self.waveform_label.setObjectName("freesoundWaveformLabel")
        self.waveform_label.setStyleSheet("background: transparent;")
        self._render_waveform_placeholder()
        self.card_layout.addWidget(self.waveform_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.name_label = SubtitleLabel(self._short_name(52))
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setToolTip(self.sound.name)
        self.name_label.setStyleSheet("background: transparent;")
        title_row.addWidget(self.name_label)
        title_row.addStretch()

        license_info = self.sound.license_info
        self.license_label = CaptionLabel(license_info.get("name_zh", self.sound.license[:20]))
        self.license_label.setStyleSheet(f"color: {license_info.get('color', '#666')};")
        title_row.addWidget(self.license_label)
        info_layout.addLayout(title_row)

        self.desc_label = CaptionLabel(self._short_desc(120))
        self.desc_label.setTextFormat(Qt.TextFormat.PlainText)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #666;")
        self.desc_label.setMaximumHeight(36)
        self.desc_label.setToolTip(self.sound.description[:500])
        info_layout.addWidget(self.desc_label)

        self.meta_row = QHBoxLayout()
        self.meta_row.setSpacing(16)
        self.duration_label = CaptionLabel(f"时长 {self.sound.duration_formatted}")
        self.duration_label.setStyleSheet("background: transparent;")
        self.meta_row.addWidget(self.duration_label)

        self.format_label = CaptionLabel(f"格式 {self.sound.type.upper()}")
        self.format_label.setStyleSheet("background: transparent;")
        self.meta_row.addWidget(self.format_label)

        self.size_label = CaptionLabel(f"大小 {self.sound.filesize_formatted}")
        self.size_label.setStyleSheet("background: transparent;")
        self.meta_row.addWidget(self.size_label)

        self.author_label = CaptionLabel(f"作者 {self.sound.username}")
        self.author_label.setStyleSheet("background: transparent;")
        self.meta_row.addWidget(self.author_label)

        self.downloads_label = CaptionLabel(f"下载 {self.sound.num_downloads}")
        self.downloads_label.setStyleSheet("background: transparent;")
        self.meta_row.addWidget(self.downloads_label)

        self.pack_label = CaptionLabel("")
        self.pack_label.setStyleSheet("background: transparent;")
        if self.sound.n_from_same_pack:
            self.pack_label.setText(f"合集 +{self.sound.n_from_same_pack}")
            self.meta_row.addWidget(self.pack_label)

        self.meta_row.addStretch()
        info_layout.addLayout(self.meta_row)

        self.card_layout.addLayout(info_layout, 1)

        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "下载")
        self.download_btn.clicked.connect(self._on_download)
        self.card_layout.addWidget(self.download_btn)
        self._load_waveform_preview()

    def _short_name(self, limit: int) -> str:
        return self.sound.name[:limit] + ("..." if len(self.sound.name) > limit else "")

    def _short_desc(self, limit: int) -> str:
        desc = re.sub(r"<[^>]+>", " ", self.sound.description or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        return desc[:limit] + ("..." if len(desc) > limit else "")

    def set_compact_mode(self, compact: bool, narrow: bool = False):
        self._compact_mode = compact
        self._narrow_mode = narrow

        if narrow:
            self.setFixedHeight(68)
            self.card_layout.setContentsMargins(10, 4, 10, 4)
            self.card_layout.setSpacing(8)
            self.play_btn.setFixedSize(32, 32)
            self.waveform_label.hide()
            self.name_label.setText(self._short_name(30))
            self.desc_label.hide()
            self.meta_row.setSpacing(10)
            self.format_label.hide()
            self.size_label.hide()
            self.author_label.hide()
            self.download_btn.setText("")
            self.download_btn.setFixedSize(36, 32)
            return

        if compact:
            self.setFixedHeight(84)
            self.card_layout.setContentsMargins(10, 6, 10, 6)
            self.card_layout.setSpacing(8)
            self.play_btn.setFixedSize(36, 36)
            self.waveform_label.show()
            self.waveform_label.setFixedSize(120, 34)
            self.name_label.setText(self._short_name(40))
            self.desc_label.hide()
            self.meta_row.setSpacing(12)
            self.format_label.show()
            self.size_label.hide()
            self.author_label.show()
            self.download_btn.setText("下载")
            self.download_btn.setFixedSize(72, 32)
            return

        self.setFixedHeight(102)
        self.card_layout.setContentsMargins(12, 8, 12, 8)
        self.card_layout.setSpacing(10)
        self.play_btn.setFixedSize(40, 40)
        self.waveform_label.show()
        self.waveform_label.setFixedSize(140, 40)
        self.name_label.setText(self._short_name(52))
        self.desc_label.show()
        self.meta_row.setSpacing(16)
        self.format_label.show()
        self.size_label.show()
        self.author_label.show()
        self.download_btn.setText("下载")
        self.download_btn.setFixedSize(80, 32)

    def _load_waveform_preview(self):
        image_url = self.sound.waveform_url or self.sound.spectral_url
        if not image_url:
            return

        try:
            manager = QNetworkAccessManager(self)
            request = QNetworkRequest(QUrl(image_url))
            reply = manager.get(request)
            self._waveform_reply = reply

            def _on_loaded(rep=reply):
                if rep.error() == QNetworkReply.NetworkError.NoError:
                    data = rep.readAll()
                    pix = QPixmap()
                    if pix.loadFromData(bytes(data)):
                        scaled = pix.scaled(
                            self.waveform_label.size(),
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self.waveform_label.setPixmap(scaled)
                rep.deleteLater()

            reply.finished.connect(_on_loaded)
        except Exception as exc:
            logger.debug(f"load waveform preview failed: {exc}")

    def _render_waveform_placeholder(self):
        width = max(64, self.waveform_label.width())
        height = max(20, self.waveform_label.height())
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 10, 12, 230))
        painter.drawRoundedRect(QRect(0, 0, width, height), 6, 6)

        center = height // 2
        painter.setPen(QPen(QColor(60, 255, 120, 110), 1))
        painter.drawLine(6, center, width - 6, center)

        bar_color = QColor(66, 255, 120, 220)
        painter.setBrush(bar_color)
        bar_count = 24
        bar_width = max(2, width // (bar_count * 2 + 2))
        x = bar_width
        levels = [2, 6, 11, 7, 4, 9, 13, 8, 5, 10, 14, 9, 4, 7, 12, 8, 5, 10, 14, 9, 6, 3, 5, 2]
        for level in levels:
            top = max(2, center - level)
            bar_h = min(height - 4, level * 2)
            painter.drawRoundedRect(QRect(x, top, bar_width, bar_h), 1, 1)
            x += bar_width * 2
            if x >= width - bar_width:
                break

        painter.end()
        self.waveform_label.setPixmap(pixmap)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_play()
        super().mouseDoubleClickEvent(event)

    def _on_play(self):
        if self.sound.previews and self.sound.previews.best_preview:
            self.play_clicked.emit(self.sound.previews.best_preview)

    def _on_download(self):
        self.download_clicked.emit(self.sound)

    def _show_context_menu(self, pos):
        from qfluentwidgets import RoundMenu, Action

        menu = RoundMenu(parent=self)
        download_action = Action(FluentIcon.DOWNLOAD, "下载音效")
        download_action.triggered.connect(lambda: self.download_clicked.emit(self.sound))
        menu.addAction(download_action)

        translate_action = Action(FluentIcon.SEND, "发送到 AI 翻译")
        translate_action.triggered.connect(lambda: self.send_to_translate.emit(self.sound))
        menu.addAction(translate_action)

        similar_action = Action(FluentIcon.SEARCH, "查找相似音效")
        similar_action.triggered.connect(lambda: self.find_similar.emit(self.sound))
        menu.addAction(similar_action)

        if self.sound.pack_id:
            pack_action = Action(FluentIcon.FOLDER, "查看同合集音效")
            pack_action.triggered.connect(lambda: self.open_pack.emit(self.sound.pack_id))
            menu.addAction(pack_action)
        menu.exec(self.mapToGlobal(pos))

    def set_playing(self, playing: bool):
        self.play_btn.setIcon(FluentIcon.PAUSE if playing else FluentIcon.PLAY)


class OnlineResourcesPage(QWidget):
    """在线资源页面"""
    play_clicked = Signal(str)  # 暴露给主窗口，使用全局播放器
    send_to_translate = Signal(str)  # 发送下载路径到翻译页面
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("onlineResourcesPage")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 状态
        self._current_results: Optional[FreesoundSearchResult] = None
        self._current_page = 1
        self._search_worker: Optional[SearchWorker] = None
        self._sound_cards: List[SoundCard] = []
        self._extra_result_widgets: List[QWidget] = []
        self._playing_card: Optional[SoundCard] = None
        
        # 移除内部播放器，改用信号
        self._media_player = None 
        
        self._download_workers = []  # Keep references to prevent GC
        self._layout_mode = ""
        self._compact_mode = False
        self._narrow_mode = False
        self._group_by_pack = False
        self._query_mode = "text"
        self._source_sound_id: Optional[int] = None
        self._source_pack_id: Optional[int] = None
        self._last_query = ""
        self._last_featured_tile_columns = 0
        self._featured_packs_cache_ts = 0.0
        self._featured_packs_loading = False
        self._featured_worker: Optional[FeaturedPacksWorker] = None
        self._pack_translate_worker: Optional[PackTranslationWorker] = None
        self._featured_cover_requests = []
        self._featured_packs = self._load_featured_packs()
        
        self._init_ui()

    def _default_featured_packs(self) -> List[dict]:
        return [
            {
                "title": "电影转场 / Whoosh 合集",
                "desc": "适合剪辑转场、镜头切换、UI 飞入飞出。",
                "query": "whoosh transition",
                "cover": "https://picsum.photos/seed/freesound-whoosh/640/360",
            },
            {
                "title": "冲击 / Hit & Impact 合集",
                "desc": "预告片重击、鼓点冲击、低频撞击。",
                "query": "impact hit trailer",
                "cover": "https://picsum.photos/seed/freesound-impact/640/360",
            },
            {
                "title": "脚步 / Footsteps 合集",
                "desc": "地面材质多样，适合游戏与影视拟音。",
                "query": "footsteps foley",
                "cover": "https://picsum.photos/seed/freesound-footsteps/640/360",
            },
            {
                "title": "环境氛围 / Ambience 合集",
                "desc": "城市、森林、室内、工业等长时氛围。",
                "query": "ambience atmosphere",
                "cover": "https://picsum.photos/seed/freesound-ambience/640/360",
            },
            {
                "title": "界面提示 / UI SFX 合集",
                "desc": "按钮、通知、确认、失败、弹窗提示音。",
                "query": "ui notification",
                "cover": "https://picsum.photos/seed/freesound-ui/640/360",
            },
            {
                "title": "科幻机械 / Sci-Fi 合集",
                "desc": "能量、激光、未来机械、系统提示。",
                "query": "sci-fi machine",
                "cover": "https://picsum.photos/seed/freesound-scifi/640/360",
            },
        ]

    def _load_featured_packs(self) -> List[dict]:
        config_path = Path(__file__).resolve().parents[2] / "config" / "featured_packs.json"
        if not config_path.exists():
            return self._default_featured_packs()

        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("featured_packs.json must be a list")

            normalized: List[dict] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                query = str(item.get("query", "")).strip()
                if not title or not query:
                    continue

                normalized.append(
                    {
                        "title": title,
                        "desc": str(item.get("desc", "")).strip(),
                        "query": query,
                        "cover": str(item.get("cover", "")).strip(),
                        "source_url": str(item.get("source_url", "")).strip(),
                    }
                )

            return normalized or self._default_featured_packs()
        except Exception as exc:
            logger.warning(f"load featured packs failed: {exc}")
            return self._default_featured_packs()

    def _begin_live_featured_packs_refresh(self):
        if self._featured_packs_loading:
            return

        api_key = self._effective_api_key()
        if not api_key:
            return

        # 10 分钟内复用缓存，避免频繁请求
        if (time.time() - float(self._featured_packs_cache_ts or 0.0)) < 600 and self._featured_packs:
            return

        self._featured_packs_loading = True
        self.page_info.setText("正在拉取 Freesound 热门合集…")
        self.page_info.show()

        worker = FeaturedPacksWorker(api_key=api_key, limit=8)
        self._featured_worker = worker
        worker.finished.connect(self._on_live_featured_packs_loaded)
        worker.start()

    def _on_live_featured_packs_loaded(self, payload):
        self._featured_packs_loading = False

        worker = self._featured_worker
        self._featured_worker = None
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:
                pass

        if isinstance(payload, Exception):
            logger.warning(f"live featured packs failed: {payload}")
            if self._query_mode == "featured":
                self.page_info.setText("热门合集加载失败，已使用本地推荐")
                self.page_info.show()
            return

        if not isinstance(payload, list) or not payload:
            if self._query_mode == "featured":
                self.page_info.setText("未获取到热门合集，已使用本地推荐")
                self.page_info.show()
            return

        self._start_pack_translation(payload)

    def _start_pack_translation(self, packs: List[Dict[str, Any]]):
        try:
            translate_func = SearchWorker(
                api_key="",
                query="",
                page=1,
            )._build_translate_func_sync()
        except Exception:
            translate_func = None

        if not translate_func:
            self._apply_translated_featured_packs(packs)
            return

        if self._pack_translate_worker is not None:
            try:
                self._pack_translate_worker.deleteLater()
            except Exception:
                pass
            self._pack_translate_worker = None

        worker = PackTranslationWorker(packs, translate_func)
        self._pack_translate_worker = worker
        worker.finished.connect(self._on_pack_translation_finished)
        worker.start()

    def _on_pack_translation_finished(self, packs):
        worker = self._pack_translate_worker
        self._pack_translate_worker = None
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:
                pass
        self._apply_translated_featured_packs(list(packs or []))

    def _apply_translated_featured_packs(self, packs: List[Dict[str, Any]]):
        if not isinstance(packs, list) or not packs:
            return

        self._featured_packs = packs
        self._featured_packs_cache_ts = time.time()

        if self._query_mode == "featured":
            self._update_featured_page_hint()
            self._render_featured_pack_tiles()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8) # Compact
        layout.setSpacing(8)
        
        # 标题 - Compact Mode: Hide
        # title = TitleLabel("在线资源")
        # layout.addWidget(title)
        
        # desc = CaptionLabel("搜索和下载 Freesound.org 免费音效资源")
        # desc.setStyleSheet("color: #666;")
        # layout.addWidget(desc)
        
        # 搜索区域
        search_card = CardWidget()
        self.search_card = search_card
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(12, 12, 12, 12) # Compact
        search_layout.setSpacing(10)

        from transcriptionist_v3.core.config import AppConfig
        saved_key = str(AppConfig.get("freesound.api_key", "") or "").strip()
        self._saved_api_key = saved_key
        self._api_key_editor_expanded = False

        self.api_status_row = QHBoxLayout()
        self.api_status_row.setContentsMargins(0, 0, 0, 0)
        self.api_status_row.setSpacing(8)
        self.api_status_label = CaptionLabel("API Key 未配置")
        self.api_status_label.setStyleSheet("background: transparent;")
        self.api_status_row.addWidget(self.api_status_label, 1)

        self.help_btn = TransparentToolButton(FluentIcon.QUESTION, self)
        self.help_btn.setToolTip("如何获取 API Key？")
        self.help_btn.setFixedSize(32, 32)
        self.help_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://freesound.org/apiv2/apply")))
        self.api_status_row.addWidget(self.help_btn)

        self.featured_link_btn = PushButton(FluentIcon.LINK, "合集")
        self.featured_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.featured_link_btn.setToolTip("推荐合集")
        self.featured_link_btn.setMinimumHeight(30)
        self.featured_link_btn.clicked.connect(self._on_show_featured_packs)
        self.api_status_row.addWidget(self.featured_link_btn)

        self.api_edit_btn = PushButton("编辑")
        self.api_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.api_edit_btn.setMinimumHeight(30)
        self.api_edit_btn.setFixedWidth(88)
        self.api_edit_btn.clicked.connect(self._on_toggle_api_key_editor)
        self.api_status_row.addWidget(self.api_edit_btn)
        search_layout.addLayout(self.api_status_row)

        self.api_editor_widget = QWidget()
        self.api_editor_widget.setStyleSheet("background: transparent;")

        # API Key 设置行
        api_row = QHBoxLayout(self.api_editor_widget)
        self.api_row = api_row
        api_row.setContentsMargins(0, 0, 0, 0)
        api_row.setSpacing(8)
        api_label = BodyLabel("API Key:")
        self.api_label = api_label
        api_label.setFixedWidth(70)
        api_label.setStyleSheet("background: transparent;")
        api_row.addWidget(api_label)
        
        self.api_key_edit = LineEdit()
        self.api_key_edit.setPlaceholderText("输入 Freesound API Key (从 freesound.org/apiv2/apply 获取)")
        self.api_key_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.api_key_edit.setMinimumHeight(36)
        
        if saved_key:
            self.api_key_edit.setPlaceholderText("API Key 已保存（留空继续使用，输入将覆盖）")
        self.api_key_edit.setEchoMode(LineEdit.EchoMode.PasswordEchoOnEdit)

        # Save on change
        self.api_key_edit.textChanged.connect(self._on_api_key_text_changed)
        
        api_row.addWidget(self.api_key_edit, 1)

        search_layout.addWidget(self.api_editor_widget)
        
        # 搜索框行
        search_row = QHBoxLayout()
        self.search_row = search_row
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索音效... (支持英文关键词，如: explosion, footsteps, rain)")
        self.search_edit.setMinimumHeight(36)
        self.search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_edit, 1)

        self.group_by_pack_combo = ComboBox()
        self.group_by_pack_combo.addItems(["单条音效", "按合集分组"])
        self.group_by_pack_combo.setToolTip("切换搜索结果展示模式")
        self.group_by_pack_combo.currentIndexChanged.connect(self._on_group_mode_changed)
        self.group_by_pack_combo.setMinimumHeight(36)
        self.group_by_pack_combo.setMinimumWidth(156)
        search_row.addWidget(self.group_by_pack_combo)

        self.search_btn = PrimaryPushButton(FluentIcon.SEARCH, "搜索")
        self.search_btn.setMinimumHeight(36)
        self.search_btn.setMinimumWidth(112)
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        
        search_layout.addLayout(search_row)
        layout.addWidget(search_card)
        self._sync_api_key_ui_state()
        
        # 搜索结果区域 - Flat Design NO CARD
        
        # 结果标题行
        results_header = QHBoxLayout()
        self.results_header = results_header
        results_header.setContentsMargins(4, 0, 4, 0)
        self.results_title = SubtitleLabel("搜索结果")
        self.results_title.setStyleSheet("background: transparent;")
        results_header.addWidget(self.results_title)
        self.back_to_search_btn = PushButton(FluentIcon.RETURN, "返回普通搜索")
        self.back_to_search_btn.clicked.connect(self._on_back_to_search)
        self.back_to_search_btn.hide()
        results_header.addWidget(self.back_to_search_btn)
        results_header.addStretch()
        
        # 分页信息
        self.page_info = CaptionLabel("")
        self.page_info.setStyleSheet("background: transparent;")
        results_header.addWidget(self.page_info)
        layout.addLayout(results_header)
        
        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 滚动区域
        self.scroll_area = ScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.results_container = QWidget()
        self.results_container.setStyleSheet("background: transparent;")
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(8)
        
        # 空状态
        self.empty_label = CaptionLabel("输入关键词搜索音效\n\n提示：需要先获取 Freesound API Key\n访问 freesound.org/apiv2/apply 申请")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; padding: 60px;")
        self.results_layout.addWidget(self.empty_label)
        self.results_layout.addStretch()
        
        self.scroll_area.setWidget(self.results_container)
        layout.addWidget(self.scroll_area, 1)
        
        # 分页控制
        pagination_row = QHBoxLayout()
        pagination_row.addStretch()
        
        self.prev_btn = PushButton(FluentIcon.LEFT_ARROW, "上一页")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._on_prev_page)
        pagination_row.addWidget(self.prev_btn)
        
        self.next_btn = PushButton("下一页")
        self.next_btn.setIcon(FluentIcon.RIGHT_ARROW)
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next_page)
        pagination_row.addWidget(self.next_btn)
        
        pagination_row.addStretch()
        layout.addLayout(pagination_row)

        self._apply_responsive_layout()
        QTimer.singleShot(0, self._apply_responsive_layout)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_responsive_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _detect_layout_mode(self) -> str:
        widths = [
            self.contentsRect().width(),
            self.width(),
        ]
        if hasattr(self, "search_card"):
            widths.append(self.search_card.width())
        if hasattr(self, "scroll_area"):
            widths.append(self.scroll_area.viewport().width())

        valid_widths = [int(width) for width in widths if int(width) > 0]
        width = min(valid_widths) if valid_widths else self.sizeHint().width()

        if width < 860:
            return "narrow"
        if width < 1240:
            return "compact"
        return "regular"

    def _apply_responsive_layout(self):
        mode = self._detect_layout_mode()
        mode_changed = mode != self._layout_mode
        if mode_changed:
            self._layout_mode = mode
            self._compact_mode = mode in {"compact", "narrow"}
            self._narrow_mode = mode == "narrow"

            self.api_row.setDirection(
                QBoxLayout.Direction.TopToBottom if self._narrow_mode else QBoxLayout.Direction.LeftToRight
            )
            self.search_row.setDirection(
                QBoxLayout.Direction.TopToBottom if self._narrow_mode else QBoxLayout.Direction.LeftToRight
            )

            if self._narrow_mode:
                self.api_label.setFixedWidth(0)
                self.api_label.show()
                self.search_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.group_by_pack_combo.setMinimumWidth(0)
                self.group_by_pack_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.help_btn.hide()
                self.empty_label.setStyleSheet("color: #888; padding: 28px 12px;")
            elif self._compact_mode:
                self.api_label.setFixedWidth(58)
                self.api_label.show()
                self.search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.search_btn.setMinimumWidth(100)
                self.group_by_pack_combo.setMinimumWidth(148)
                self.group_by_pack_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.help_btn.show()
                self.empty_label.setStyleSheet("color: #888; padding: 44px 20px;")
            else:
                self.api_label.setFixedWidth(70)
                self.api_label.show()
                self.search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.search_btn.setMinimumWidth(112)
                self.group_by_pack_combo.setMinimumWidth(168)
                self.group_by_pack_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.help_btn.show()
                self.empty_label.setStyleSheet("color: #888; padding: 60px;")

        self._apply_top_search_bar_metrics()
        self._sync_api_key_ui_state()

        for card in self._sound_cards:
            card.set_compact_mode(self._compact_mode, self._narrow_mode)

        if self._query_mode == "featured":
            self._update_featured_page_hint()
            current_columns = self._featured_tile_columns()
            if mode_changed or current_columns != self._last_featured_tile_columns:
                self._render_featured_pack_tiles()

    def _apply_top_search_bar_metrics(self):
        control_height = 38 if self._narrow_mode else 36
        icon_btn_size = max(30, control_height - 2)

        self.api_row.setSpacing(6 if self._narrow_mode else 8)
        self.search_row.setSpacing(6 if self._narrow_mode else 8)

        self.api_key_edit.setFixedHeight(control_height)
        self.search_edit.setFixedHeight(control_height)
        self.group_by_pack_combo.setFixedHeight(control_height)
        self.search_btn.setFixedHeight(control_height)

        self.help_btn.setFixedSize(icon_btn_size, icon_btn_size)
        self.featured_link_btn.setFixedHeight(max(30, control_height - 4))
        self.api_edit_btn.setFixedHeight(max(30, control_height - 4))
        if self._narrow_mode:
            self.featured_link_btn.setIcon(QIcon())
            self.featured_link_btn.setText("合集")
            self.featured_link_btn.setFixedWidth(62)
            self.api_edit_btn.setFixedWidth(62)
        else:
            self.featured_link_btn.setIcon(FluentIcon.LINK)
            self.featured_link_btn.setText("合集")
            self.featured_link_btn.setFixedWidth(72)
            self.api_edit_btn.setFixedWidth(72)

        if self._narrow_mode:
            self.search_btn.setMinimumWidth(0)
            self.search_btn.setMaximumWidth(16777215)
            self.group_by_pack_combo.setMinimumWidth(0)
            self.group_by_pack_combo.setMaximumWidth(16777215)
            self.api_row.setAlignment(self.api_key_edit, Qt.AlignmentFlag.AlignVCenter)
            self.search_row.setAlignment(self.search_edit, Qt.AlignmentFlag.AlignVCenter)
            return

        self.search_btn.setMaximumWidth(16777215)
        self.group_by_pack_combo.setMaximumWidth(16777215)

        self.api_row.setAlignment(self.api_label, Qt.AlignmentFlag.AlignVCenter)
        self.api_row.setAlignment(self.api_key_edit, Qt.AlignmentFlag.AlignVCenter)

        self.search_row.setAlignment(self.search_edit, Qt.AlignmentFlag.AlignVCenter)
        self.search_row.setAlignment(self.group_by_pack_combo, Qt.AlignmentFlag.AlignVCenter)
        self.search_row.setAlignment(self.search_btn, Qt.AlignmentFlag.AlignVCenter)

    def _effective_api_key(self) -> str:
        typed_key = str(self.api_key_edit.text() or "").strip()
        if typed_key:
            return typed_key
        return str(self._saved_api_key or "").strip()

    def _on_api_key_text_changed(self, text: str):
        value = str(text or "").strip()
        if value:
            self._saved_api_key = value
        from transcriptionist_v3.core.config import AppConfig
        AppConfig.set("freesound.api_key", value if value else self._saved_api_key)
        self._sync_api_key_ui_state()

    def _on_toggle_api_key_editor(self):
        self._api_key_editor_expanded = not self._api_key_editor_expanded
        if self._api_key_editor_expanded:
            self.api_key_edit.setFocus()
        self._sync_api_key_ui_state()

    def _sync_api_key_ui_state(self):
        has_key = bool(self._effective_api_key())
        editor_visible = self._api_key_editor_expanded or not has_key

        if has_key:
            self.api_status_label.setText("API Key 已配置")
            self.api_edit_btn.setText("修改")
        else:
            self.api_status_label.setText("API Key 未配置")
            self.api_edit_btn.setText("配置")

        if self._narrow_mode and has_key and not self._api_key_editor_expanded:
            editor_visible = False

        self.api_label.setVisible(editor_visible)
        self.api_key_edit.setVisible(editor_visible)
        self.api_editor_widget.setVisible(editor_visible)
        self.api_row.setEnabled(editor_visible)

    def _update_featured_page_hint(self):
        if self._narrow_mode:
            self.page_info.setText("点击卡片进入合集")
        elif self._compact_mode:
            self.page_info.setText("点击合集卡片即可检索 Freesound 对应合集")
        else:
            self.page_info.setText("点击“打开合集”可跳转到 Freesound 对应合集检索")

    def _on_group_mode_changed(self, index: int):
        self._group_by_pack = index == 1

    def _on_show_featured_packs(self):
        """展示可点击的推荐音效合集入口。"""
        self._query_mode = "featured"
        self._source_sound_id = None
        self._source_pack_id = None

        self._clear_results()
        self.empty_label.setVisible(False)
        self.results_title.setText("推荐音效合集")
        self._update_featured_page_hint()
        self.page_info.show()
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.back_to_search_btn.hide()

        self._render_featured_pack_tiles()
        self._begin_live_featured_packs_refresh()

    def _featured_tile_columns(self) -> int:
        """按当前可用宽度动态计算推荐合集列数。"""
        available_width = self.scroll_area.viewport().width()
        if available_width <= 0:
            available_width = self.width()

        if self._narrow_mode:
            return 1

        if self._compact_mode:
            return 1 if available_width < 760 else 2

        if available_width < 960:
            return 2
        if available_width < 1360:
            return 2
        return 3

    def _render_featured_pack_tiles(self):
        """渲染推荐合集平铺卡片（支持动态重排）。"""
        self._featured_cover_requests.clear()
        for widget in self._extra_result_widgets:
            widget.deleteLater()
        self._extra_result_widgets.clear()

        tokens = get_theme_tokens(isDarkTheme())
        card_qss = (
            f"CardWidget {{"
            f"background-color: {tokens.card_bg};"
            f"border: 1px solid {tokens.card_border};"
            f"border-radius: 12px;"
            f"}}"
            f"CardWidget:hover {{"
            f"background-color: {tokens.card_hover};"
            f"border: 1px solid {tokens.border};"
            f"}}"
        )

        tile_columns = self._featured_tile_columns()
        self._last_featured_tile_columns = tile_columns
        tile_container = QWidget()
        tile_grid = QGridLayout(tile_container)
        tile_grid.setContentsMargins(0, 0, 0, 0)
        tile_grid.setHorizontalSpacing(8 if self._compact_mode else 10)
        tile_grid.setVerticalSpacing(8 if self._compact_mode else 10)

        for index, item in enumerate(self._featured_packs):
            card = CardWidget()
            card.setStyleSheet(card_qss)
            if self._narrow_mode:
                card.setMinimumHeight(188)
            elif self._compact_mode:
                card.setMinimumHeight(206)
            else:
                card.setMinimumHeight(224)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(8 if self._compact_mode else 10)

            cover_label = CaptionLabel()
            cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cover_label.setObjectName("featuredPackCover")
            cover_height = 72 if self._narrow_mode else (88 if self._compact_mode else 100)
            cover_label.setFixedHeight(cover_height)
            cover_text = str(item.get("title", "合集")).split("/")[0].strip() or "精选合集"
            if len(cover_text) > 14:
                cover_text = cover_text[:14] + "…"

            cover_url = str(item.get("cover", "")).strip()
            gradient = (
                f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                f"stop:0 {tokens.surface_2}, stop:1 {tokens.surface_1})"
            )
            cover_label.setText(cover_text)
            cover_label.setStyleSheet(
                f"""
                QLabel#featuredPackCover {{
                    border-radius: 10px;
                    border: 1px solid {tokens.card_border};
                    background: {gradient};
                    color: {tokens.text_secondary};
                    font-size: 13px;
                    font-weight: 600;
                    letter-spacing: 0.3px;
                }}
                """
            )

            if cover_url and cover_url.lower().startswith("http"):
                try:
                    manager = QNetworkAccessManager(cover_label)
                    request = QNetworkRequest(QUrl(cover_url))
                    reply = manager.get(request)
                    self._featured_cover_requests.append((manager, reply))

                    def _on_cover_loaded(label=cover_label, rep=reply, fallback_text=cover_text):
                        if rep.error() == QNetworkReply.NetworkError.NoError:
                            data = rep.readAll()
                            pix = QPixmap()
                            if pix.loadFromData(bytes(data)):
                                scaled = pix.scaled(
                                    label.size(),
                                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                                label.setText("")
                                label.setPixmap(scaled)
                            else:
                                label.setText(fallback_text)
                        else:
                            label.setText(fallback_text)
                        rep.deleteLater()

                    reply.finished.connect(_on_cover_loaded)
                except Exception as exc:
                    logger.debug(f"load pack cover failed: {exc}")

            title_label = SubtitleLabel(item["title"])
            title_label.setWordWrap(True)
            title_label.setStyleSheet("background: transparent;")
            title_label.setText(str(item.get("title", "")).strip() or "精选合集")

            count_value = int(item.get("sounds_count") or 0)
            count_text = f"{count_value} sounds" if count_value > 0 else ""
            count_label = CaptionLabel(count_text)
            count_label.setVisible(bool(count_text))
            count_label.setStyleSheet(f"background: transparent; color: {tokens.text_secondary};")

            desc_label = CaptionLabel(item["desc"])
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"background: transparent; color: {tokens.text_muted};")
            desc_label.setMaximumHeight(36 if self._narrow_mode else 42)
            desc_label.setText(str(item.get("desc", "")).strip())

            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 0, 0, 0)
            action_row.setSpacing(8)

            open_btn = PrimaryPushButton("添加")
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setMinimumHeight(30)
            open_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            source_btn = PushButton("预览")
            source_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            source_btn.setMinimumHeight(30)
            source_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            # 防止重复连接导致一次点击打开多个窗口
            try:
                open_btn.clicked.disconnect()
            except Exception:
                pass
            try:
                source_btn.clicked.disconnect()
            except Exception:
                pass
            open_btn.clicked.connect(lambda _=False, q=item["query"]: self._on_open_featured_pack_query(q))
            source_url = str(item.get("source_url", "")).strip()
            if source_url:
                source_btn.clicked.connect(lambda _=False, url=source_url: QDesktopServices.openUrl(QUrl(url)))
            else:
                query = str(item.get("query", "")).strip()
                search_url = f"https://freesound.org/search/?q={quote_plus(query)}"
                source_btn.clicked.connect(lambda _=False, url=search_url: QDesktopServices.openUrl(QUrl(url)))

            action_row.addWidget(open_btn)
            action_row.addWidget(source_btn)

            card_layout.addWidget(cover_label)
            card_layout.addWidget(title_label)
            card_layout.addWidget(count_label)
            card_layout.addWidget(desc_label)
            card_layout.addStretch(1)
            card_layout.addLayout(action_row)

            row = index // tile_columns
            col = index % tile_columns
            tile_grid.addWidget(card, row, col)

        for col in range(tile_columns):
            tile_grid.setColumnStretch(col, 1)

        self._extra_result_widgets.append(tile_container)
        self.results_layout.insertWidget(self.results_layout.count() - 1, tile_container)

    def _on_open_featured_pack_query(self, query: str):
        """从推荐合集卡片进入应用内检索（按合集分组）。"""
        api_key = self._effective_api_key()
        if not api_key:
            InfoBar.warning(
                title="提示",
                content="请先输入 Freesound API Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return

        self.group_by_pack_combo.setCurrentIndex(1)
        self.search_edit.setText(query)
        self._query_mode = "text"
        self._source_sound_id = None
        self._source_pack_id = None
        self._last_query = query
        self._current_page = 1
        self._do_search(api_key, query, 1)
    
    def _on_test_connection(self):
        """兼容旧入口：现在改为展示推荐合集。"""
        self._on_show_featured_packs()
    
    def _on_test_finished(self, result):
        """兼容旧逻辑：保留接口但不再依赖测试按钮。"""
        
        if isinstance(result, Exception):
            if isinstance(result, FreesoundAuthError):
                InfoBar.error(
                    title="认证失败",
                    content="API Key 无效，请检查后重试",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
            else:
                InfoBar.error(
                    title="连接失败",
                    content=str(result)[:100],
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
        else:
            InfoBar.success(
                title="连接成功",
                content="API Key 有效，可直接使用“推荐合集”或搜索",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
    
    def _on_search(self):
        """执行搜索"""
        query = self.search_edit.text().strip()
        api_key = self._effective_api_key()
        
        if not api_key:
            InfoBar.warning(
                title="提示",
                content="请先输入 Freesound API Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return
        
        if not query:
            InfoBar.warning(
                title="提示",
                content="请输入搜索关键词",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return
        
        # Optimize Query (AI Polish)
        optimized_query = self._optimize_search_query(query)

        self._query_mode = "text"
        self._source_sound_id = None
        self._source_pack_id = None
        self._last_query = optimized_query
        self._current_page = 1
        self._do_search(api_key, optimized_query, 1)
    
    def _do_search(self, api_key: str, query: str, page: int):
        """执行搜索"""
        # 显示加载状态
        self.search_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定进度
        self.results_title.setText("搜索中...")
        
        # 清空旧结果
        self._clear_results()

        if self._search_worker and self._search_worker.isRunning():
            try:
                self._search_worker.requestInterruption()
            except Exception:
                pass
        
        # 启动搜索线程
        self._search_worker = SearchWorker(
            api_key,
            query,
            page,
            15,
            group_by_pack=self._group_by_pack,
            search_mode=self._query_mode,
            source_sound_id=self._source_sound_id,
            source_pack_id=self._source_pack_id,
        )
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.start()
    
    def _on_search_finished(self, result):
        """搜索完成"""
        worker = self.sender()
        if worker is not self._search_worker:
            try:
                worker.deleteLater()
            except Exception:
                pass
            return

        self.search_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        if self._search_worker is not None:
            try:
                self._search_worker.deleteLater()
            except Exception:
                pass
            self._search_worker = None
        
        if isinstance(result, Exception):
            self.results_title.setText("搜索失败")
            if isinstance(result, FreesoundAuthError):
                InfoBar.error(
                    title="认证失败",
                    content="API Key 无效或已过期",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
            else:
                InfoBar.error(
                    title="搜索失败",
                    content=str(result)[:100],
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
            return
        
        self._current_results = result
        self._display_results(result)
    
    def _clear_results(self):
        """清空搜索结果"""
        # Reset playing state (no internal player anymore, using global player)
        self._playing_card = None
        
        # 清空卡片
        for card in self._sound_cards:
            card.deleteLater()
        self._sound_cards.clear()

        for widget in self._extra_result_widgets:
            widget.deleteLater()
        self._extra_result_widgets.clear()
        
        # 显示空状态
        self.empty_label.setVisible(True)
    
    def _display_results(self, result: FreesoundSearchResult):
        """显示搜索结果"""
        self.empty_label.setVisible(False)
        
        if result.count == 0:
            self.results_title.setText("无搜索结果")
            self.page_info.setText("")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.empty_label.setText("没有找到匹配的音效\n\n尝试使用其他关键词")
            self.empty_label.setVisible(True)
            return
        
        # 更新标题
        if self._query_mode == "similar":
            self.results_title.setText(f"相似音效 ({result.count} 个)")
            self.back_to_search_btn.show()
        elif self._query_mode == "pack":
            self.results_title.setText(f"合集音效 ({result.count} 个)")
            self.back_to_search_btn.show()
        elif self._group_by_pack:
            self.results_title.setText(f"搜索结果（按合集分组）({result.count} 个)")
            self.back_to_search_btn.hide()
        else:
            self.results_title.setText(f"搜索结果 ({result.count} 个)")
            self.back_to_search_btn.hide()
        self.page_info.setText(f"第 {result.current_page} / {result.total_pages} 页")
        
        # 更新分页按钮
        self.prev_btn.setEnabled(result.previous_page is not None)
        self.next_btn.setEnabled(result.next_page is not None)
        
        # 创建音效卡片
        for sound in result.results:
            card = SoundCard(sound)
            card.play_clicked.connect(self._on_play_preview)
            card.download_clicked.connect(self._on_download_sound)
            card.send_to_translate.connect(self._on_send_to_translate)
            card.find_similar.connect(self._on_find_similar)
            card.open_pack.connect(self._on_open_pack)
            card.set_compact_mode(self._compact_mode, self._narrow_mode)
            self._sound_cards.append(card)
            # 插入到 stretch 之前
            self.results_layout.insertWidget(self.results_layout.count() - 1, card)

    def _on_find_similar(self, sound: FreesoundSound):
        """按当前音效查找相似音效。"""
        api_key = self._effective_api_key()
        if not api_key:
            InfoBar.warning(
                title="提示",
                content="请先输入 Freesound API Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return

        self._query_mode = "similar"
        self._source_sound_id = sound.id
        self._source_pack_id = None
        self._current_page = 1
        self._do_search(api_key, sound.name, 1)

    def _on_open_pack(self, pack_id: int):
        """查看某个合集中的音效。"""
        api_key = self._effective_api_key()
        if not api_key:
            InfoBar.warning(
                title="提示",
                content="请先输入 Freesound API Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return

        self._query_mode = "pack"
        self._source_pack_id = pack_id
        self._source_sound_id = None
        self._current_page = 1
        self._do_search(api_key, self.search_edit.text().strip(), 1)

    def _on_back_to_search(self):
        """从相似/合集结果返回普通搜索。"""
        query = self.search_edit.text().strip()
        api_key = self._effective_api_key()
        if not query or not api_key:
            return

        self._query_mode = "text"
        self._source_sound_id = None
        self._source_pack_id = None
        self._last_query = query
        self._current_page = 1
        self._do_search(api_key, query, 1)
    
    def _on_play_preview(self, preview_url: str):
        """播放预览 - 带缓存机制"""
        # Parse sound ID from URL or sound object
        # Note: preview_url might need to be associated with Sound object for better caching
        # But for now we can extract ID from URL regex or just hash it.
        # However, SoundCard emits preview_url. Let's modify SoundCard to emit sound object or we find sound by URL.
        # Actually simplest is to hash the URL or extract ID if possible.
        # Freesound preview URLs look like: .../previews/123/123456_1234-hq.mp3
        
        try:
            # 1. Determine cache path
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            filename = Path(preview_url).name
            cache_dir = get_data_dir() / "cache" / "previews"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cache_dir / filename
            
            # 2. If cached, play local
            if cache_path.exists() and cache_path.stat().st_size > 0:
                self.play_clicked.emit(str(cache_path))
                return

            # 3. If not cached, download then play
            InfoBar.info(
                title="正在缓冲",
                content="首次播放需要下载预览音频...",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            
            # Use QNetworkAccessManager for simple download without async complexity here if possible,
            # but we already have async mechanics. Let's use a simple thread worker.
            import requests
            from PySide6.QtCore import QThread, Signal
            
            class PreviewLoader(QThread):
                finished = Signal(str)
                error = Signal(str)
                
                def __init__(self, url, target):
                    super().__init__()
                    self.url = url
                    self.target = target
                
                def run(self):
                    try:
                        response = requests.get(self.url, stream=True, verify=False) # Skip SSL verify for speed/compat
                        if response.status_code == 200:
                            with open(self.target, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            self.finished.emit(str(self.target))
                        else:
                            self.error.emit(f"HTTP {response.status_code}")
                    except Exception as e:
                        self.error.emit(str(e))

            # Store worker to prevent GC
            worker = PreviewLoader(preview_url, cache_path)
            
            def on_loaded(path):
                self.play_clicked.emit(path)
                if worker in self._download_workers:
                    self._download_workers.remove(worker)
                worker.deleteLater()
            
            def on_error(err):
                logger.error(f"Preview download failed: {err}")
                if worker in self._download_workers:
                    self._download_workers.remove(worker)
                worker.deleteLater()
                # Fallback to stream if download fails
                self.play_clicked.emit(preview_url)
            
            worker.finished.connect(on_loaded)
            worker.error.connect(on_error)
            self._download_workers.append(worker)
            worker.start()
            
        except Exception as e:
            logger.error(f"Playback error: {e}")
            # Fallback
            self.play_clicked.emit(preview_url)
        
    def _on_playback_state_changed(self, state):
        """已停用：改由主窗口全局播放器处理"""
        pass
    
    def _download_sound_impl(self, sound: FreesoundSound, callback=None):
        """通用下载实现"""
        from transcriptionist_v3.core.config import AppConfig
        
        # Get download path
        download_path = AppConfig.get("freesound.download_path", "").strip()
        if not download_path:
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            data_dir = get_data_dir()
            download_path = str(data_dir / "downloads" / "freesound")
        
        # Ensure directory exists
        Path(download_path).mkdir(parents=True, exist_ok=True)
        
        # Get API key
        api_key = self._effective_api_key()
        if not api_key:
            InfoBar.warning(
                title="需要 API Key",
                content="请先输入 Freesound API Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return
        
        # Start download
        InfoBar.info(
            title="开始下载",
            content=f"正在下载: {sound.name}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
        
        # Prepare valid filename
        import re
        safe_name = re.sub(r'[\\/*?:"<>|]', "", sound.name).strip()
        if not safe_name:
            safe_name = f"freesound_{sound.id}"
        if not safe_name.endswith(f".{sound.type}"):
            safe_name += f".{sound.type}"
        target_path = Path(download_path) / safe_name
        
        # Define Worker
        import asyncio
        from PySide6.QtCore import QThread, Signal
        
        class DownloadWorker(QThread):
            finished = Signal(str)
            error = Signal(str)
            
            def __init__(self, download_url, target_path):
                super().__init__()
                self.download_url = download_url
                self.target_path = target_path
            
            def run(self):
                async def download():
                    import aiohttp
                    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                         async with session.get(self.download_url) as response:
                            if response.status != 200:
                                raise Exception(f"HTTP {response.status}")
                            content = await response.read()
                            self.target_path.write_bytes(content)
                            return str(self.target_path)
                
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(download())
                    loop.close()
                    self.finished.emit(result)
                except Exception as e:
                    self.error.emit(str(e))
        
        # Get Download URL (Using HQ Preview to avoid OAuth2 401 error)
        # Previews already include the token in some client implementations if handled,
        # but HQ previews are generally accessible with just an API token.
        # Actually, the previews in FreesoundSound object usually already have the token appended by SearchService.
        download_url = sound.previews.preview_hq_mp3 if sound.previews else ""
        if not download_url:
             # Fallback to search-friendly token addition if missing
             InfoBar.error(title="下载失败", content="无法获取有效的试听下载地址", parent=self)
             return

        # Create and Start Worker
        worker = DownloadWorker(download_url, target_path)
        
        def on_finished(path):
            if callback:
                callback(path)
            else:
                InfoBar.success(
                    title="下载完成",
                    content=f"已保存到: {path}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
            if worker in self._download_workers:
                self._download_workers.remove(worker)
            worker.deleteLater()
            
        def on_error(err):
            InfoBar.error(
                title="下载失败",
                content=str(err),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            if worker in self._download_workers:
                self._download_workers.remove(worker)
            worker.deleteLater()
            
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        
        self._download_workers.append(worker)
        worker.start()

    def _on_download_sound(self, sound: FreesoundSound):
        """点击下载按钮"""
        self._download_sound_impl(sound)
    
    def _on_send_to_translate(self, sound: FreesoundSound):
        """由右键菜单触发：下载后发送到翻译"""
        def on_downloaded(path):
            # Send signal with local file path
            self.send_to_translate.emit(path)
            InfoBar.success(
                title="已发送到 AI 翻译",
                content=f"文件已就绪: {Path(path).name}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
        
        InfoBar.info(
            title="正在获取文件",
            content="正在下载文件以便进行翻译...",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
        self._download_sound_impl(sound, callback=on_downloaded)
    
    def _on_prev_page(self):
        """上一页"""
        if self._current_results and self._current_page > 1:
            self._current_page -= 1
            api_key = self._effective_api_key()
            query = self._last_query or self.search_edit.text().strip()
            self._do_search(api_key, query, self._current_page)
    
    def _on_next_page(self):
        """下一页"""
        if self._current_results and self._current_results.next_page:
            self._current_page += 1
            api_key = self._effective_api_key()
            query = self._last_query or self.search_edit.text().strip()
            self._do_search(api_key, query, self._current_page)
    
    def _optimize_search_query(self, query: str) -> str:
        """AI 智能搜索优化：将用户描述转化为 Freesound 最佳搜索关键词"""
        # 如果是简单的英文单词，直接返回 (避免过度优化)
        if re.match(r'^[a-zA-Z0-9\s]+$', query) and len(query.split()) < 3:
            return query
            
        logger.info(f"Optimizing search query: {query}")
        
        try:
            from transcriptionist_v3.core.config import AppConfig
            from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
            from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
            
            api_key = AppConfig.get("ai.api_key", "").strip()
            if not api_key:
                logger.warning("No AI API key, skipping optimization")
                return query
            
            model_index = AppConfig.get("ai.model_index", 0)
            model_configs = {
                0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
                1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
                2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
            }
            config_data = model_configs.get(model_index, model_configs[0])
            
            config = AIServiceConfig(
                provider_id=config_data['provider'],
                model_name=config_data['model'],
                api_key=api_key,
                base_url=config_data['base_url'],
                temperature=0.3,
                max_tokens=60
            )
            
            # Smart Prompt - As advised by AI Expert
            system_prompt = (
                "You are an expert sound effects librarian for Freesound.org.\n"
                "Your task is to convert the user's search query (in any language) into "
                "2-4 precise English keywords that will match sound effect tags.\n"
                "Rules:\n"
                "1. Output ONLY the English keywords, separated by spaces.\n"
                "2. Remove unnecessary words like 'sound of', 'I want', etc.\n"
                "3. Use standard audio terminology (e.g., 'whoosh' instead of 'fast wind').\n"
                "Example: '呼呼的转场声' -> 'whoosh swish transition'\n"
                "Example: 'rain against window' -> 'rain window impact'\n"
                "Example: '恐怖的鬼叫' -> 'horror ghost scream'"
            )
            
            import asyncio
            import aiohttp
            
            async def get_keywords():
                try:
                    async with aiohttp.ClientSession() as session:
                        payload = {
                            "model": config.model_name,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": query}
                            ],
                            "temperature": 0.3
                        }
                        headers = {
                            "Authorization": f"Bearer {config.api_key}",
                            "Content-Type": "application/json"
                        }
                        async with session.post(f"{config.base_url}/chat/completions", json=payload, headers=headers) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                content = data['choices'][0]['message']['content'].strip()
                                # Remove quotes if any
                                return content.replace('"', '').replace("'", "")
                            return query
                except Exception as e:
                    logger.error(f"Optimization error: {e}")
                    return query
            
            # Run async in sync context (main thread blocking but short)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            optimized = loop.run_until_complete(get_keywords())
            loop.close()
            
            if optimized and optimized != query:
                logger.info(f"Optimized query: '{query}' -> '{optimized}'")
                return optimized
            
            return query
            
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            return query
    
    # NOTE:
    # 旧占位版 _on_send_to_translate 曾在此重复定义，
    # 会覆盖上方“下载后发给翻译”的正式实现，导致功能失效。
