"""
在线资源页面 - Freesound等在线音效资源
连接到后端 FreesoundClient 和 FreesoundSearchService
"""

import asyncio
import logging
import re
from pathlib import Path
import requests
from typing import Optional, List
from PySide6.QtCore import Qt, Signal, QThread, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSizePolicy, QFrame
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from qfluentwidgets import (
    ScrollArea, PrimaryPushButton, PushButton, SearchLineEdit, LineEdit,
    FluentIcon, CardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, CaptionLabel, IconWidget, ElevatedCardWidget,
    TransparentToolButton, InfoBar, InfoBarPosition,
    ProgressBar, ComboBox, SpinBox, ToolButton, FlowLayout
)

from transcriptionist_v3.application.online_resources.freesound import (
    FreesoundClient, FreesoundSearchService, FreesoundSettings,
    FreesoundSound, FreesoundSearchResult, FreesoundSearchOptions,
    FreesoundError, FreesoundAuthError
)

logger = logging.getLogger(__name__)


class SearchWorker(QThread):
    """后台搜索线程"""
    finished = Signal(object)  # FreesoundSearchResult or Exception
    
    def __init__(self, api_key: str, query: str, page: int = 1, page_size: int = 15):
        super().__init__()
        self.api_key = api_key
        self.query = query
        self.page = page
        self.page_size = page_size
    
    def _build_translate_func(self):
        """
        构建统一翻译函数（优先 HY-MT1.5 ONNX，其次通用大模型）。
        
        注意：这是一个同步函数，方便在 QThread 中直接调用，
        内部会自行管理事件循环和服务生命周期。
        """
        import re as _re
        import asyncio as _asyncio
        from transcriptionist_v3.core.config import AppConfig as _AppConfig
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig as _AIServiceConfig
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService as _OpenAIService
        
        def translate(text: str) -> str:
            # 空字符串直接返回
            if not text:
                return text
            
            # 根据是否包含中文，自动判断目标语言：
            # - 如果文本中含中文：翻译成英文（用于查询）
            # - 如果文本中不含中文：翻译成中文（用于结果名称）
            has_zh = bool(_re.search(r'[\u4e00-\u9fff]', text))
            target_lang = "en" if has_zh else "zh"
            
            # 1. 优先尝试 HY-MT1.5 ONNX 本地翻译模型 - 已注释（模型加载慢且翻译质量不稳定）
            # try:
            #     translation_model_type = _AppConfig.get("ai.translation_model_type", "general")
            #     if translation_model_type == "hy_mt15_onnx":
            #         from transcriptionist_v3.runtime.runtime_config import get_data_dir as _get_data_dir
            #         from transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx import HyMT15OnnxService as _HyMTService
            #         
            #         model_dir = _get_data_dir() / "models" / "hy-mt1.5-onnx"
            #         required = ["model_fp16.onnx", "model_fp16.onnx_data", "model_fp16.onnx_data_1"]
            #         has_model = all((model_dir / f).exists() for f in required) and (
            #             (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer_config.json").exists()
            #         )
            #         if has_model:
            #             cfg = _AIServiceConfig(provider_id="hy_mt15_onnx", model_name="hy-mt1.5-onnx")
            #             svc = _HyMTService(cfg)
            #             loop = _asyncio.new_event_loop()
            #             _asyncio.set_event_loop(loop)
            #             try:
            #                 loop.run_until_complete(svc.initialize())
            #                 src_lang = "zh" if target_lang == "en" else "en"
            #                 r = loop.run_until_complete(
            #                     svc.translate(text, source_lang=src_lang, target_lang=target_lang)
            #                 )
            #                 if r and r.success and r.data:
            #                     return r.data.translated.strip()
            #             finally:
            #                 try:
            #                     loop.run_until_complete(svc.cleanup())
            #                 except Exception:
            #                     pass
            #                 loop.close()
            # except Exception as e:
            #     logger.debug(f"HY-MT1.5 ONNX translate failed in Freesound search, fallback to general: {e}")
            
            # 2. 回退到通用大模型（DeepSeek / OpenAI / Doubao）
            api_key = _AppConfig.get("ai.api_key", "").strip()
            if not api_key:
                # 没有配置通用模型时，直接返回原文，避免影响搜索
                return text
            
            model_idx = _AppConfig.get("ai.model_index", 0)
            model_configs = {
                0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
                1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
                2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
            }
            config = model_configs.get(model_idx, model_configs[0])
            
            # 根据目标语言构造简单提示词
            if target_lang == "en":
                sys_prompt = (
                    "You are a translator. Translate the following Chinese audio-related search query "
                    "to concise English keywords suitable for Freesound.org search. "
                    "Output ONLY the English translation, one line per input line."
                )
            else:
                sys_prompt = (
                    "你是一位专业的影视音效标签翻译助手。\n"
                    "任务：将以下英文音效名称翻译为简短、自然的简体中文标签，用于展示给用户。\n"
                    "要求：\n"
                    "- 保持意思准确，不要添加不存在的内容；\n"
                    "- 结果尽量简洁，一般不超过 8 个汉字；\n"
                    "- 一行一个结果，对应输入的每一行。\n"
                )
            
            svc_cfg = _AIServiceConfig(
                provider_id=config["provider"],
                api_key=api_key,
                base_url=config["base_url"],
                model_name=config["model"],
                system_prompt=sys_prompt,
            )
            
            svc = _OpenAIService(svc_cfg)
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                # 这里直接使用 translate 接口，内部会按一段文本整体处理
                src_lang = "zh" if target_lang == "en" else "en"
                r = loop.run_until_complete(
                    svc.translate(text, source_lang=src_lang, target_lang=target_lang)
                )
                if r and r.success and r.data:
                    return (r.data.translated or text).strip()
            except Exception as e:
                logger.error(f"General model translate failed in Freesound search: {e}")
            finally:
                try:
                    loop.run_until_complete(svc.cleanup())
                except Exception:
                    pass
                loop.close()
            
            # 最终兜底：返回原文
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
        translate_func = self._build_translate_func()
        
        async with FreesoundClient(self.api_key) as client:
            service = FreesoundSearchService(
                client=client,
                settings=settings,
                translate_func=translate_func,
            )
            # 使用高级搜索服务（带翻译与缓存）
            return await service.search(self.query, page=self.page)


class SoundCard(ElevatedCardWidget):
    """音效卡片 - 显示单个搜索结果"""
    play_clicked = Signal(str)  # preview_url
    download_clicked = Signal(object)  # FreesoundSound
    send_to_translate = Signal(object)  # FreesoundSound
    
    def __init__(self, sound: FreesoundSound, parent=None):
        super().__init__(parent)
        self.sound = sound
        self.setFixedHeight(80)  # Reduced from 120
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._init_ui()
    
    def mouseDoubleClickEvent(self, event):
        """的双击播放"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_play()
        super().mouseDoubleClickEvent(event)
    
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)  # Reduced padding
        layout.setSpacing(10)
        
        # 左侧：播放按钮
        self.play_btn = ToolButton(FluentIcon.PLAY)
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self._on_play)
        layout.addWidget(self.play_btn)
        
        # 中间：信息区域
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # 标题行
        title_row = QHBoxLayout()
        name_label = SubtitleLabel(self.sound.name[:50] + ('...' if len(self.sound.name) > 50 else ''))
        name_label.setToolTip(self.sound.name)
        name_label.setStyleSheet("background: transparent;")
        title_row.addWidget(name_label)
        title_row.addStretch()
        
        # 许可证标签
        license_info = self.sound.license_info
        license_label = CaptionLabel(license_info.get('name_zh', self.sound.license[:20]))
        license_label.setStyleSheet(f"color: {license_info.get('color', '#666')};")
        title_row.addWidget(license_label)
        info_layout.addLayout(title_row)
        
        # 描述
        desc = self.sound.description[:100] + ('...' if len(self.sound.description) > 100 else '')
        desc_label = CaptionLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666;")
        desc_label.setToolTip(self.sound.description[:500])
        info_layout.addWidget(desc_label)
        
        # 元数据行
        meta_row = QHBoxLayout()
        meta_row.setSpacing(16)
        
        # 时长
        duration_label = CaptionLabel(f"⏱ {self.sound.duration_formatted}")
        duration_label.setStyleSheet("background: transparent;")
        meta_row.addWidget(duration_label)
        
        # 格式
        format_label = CaptionLabel(f"📁 {self.sound.type.upper()}")
        format_label.setStyleSheet("background: transparent;")
        meta_row.addWidget(format_label)
        
        # 大小
        size_label = CaptionLabel(f"💾 {self.sound.filesize_formatted}")
        size_label.setStyleSheet("background: transparent;")
        meta_row.addWidget(size_label)
        
        # 作者
        author_label = CaptionLabel(f"👤 {self.sound.username}")
        author_label.setStyleSheet("background: transparent;")
        meta_row.addWidget(author_label)
        
        # 下载次数
        downloads_label = CaptionLabel(f"⬇ {self.sound.num_downloads}")
        downloads_label.setStyleSheet("background: transparent;")
        meta_row.addWidget(downloads_label)
        
        meta_row.addStretch()
        info_layout.addLayout(meta_row)
        
        layout.addLayout(info_layout, 1)
        
        # 右侧：下载按钮
        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "下载")
        self.download_btn.setFixedWidth(80)
        self.download_btn.clicked.connect(self._on_download)
        layout.addWidget(self.download_btn)
    
    def _on_play(self):
        if self.sound.previews and self.sound.previews.best_preview:
            self.play_clicked.emit(self.sound.previews.best_preview)
    
    def _on_download(self):
        self.download_clicked.emit(self.sound)
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        from qfluentwidgets import RoundMenu, Action
        menu = RoundMenu(parent=self)
        
        download_action = Action(FluentIcon.DOWNLOAD, "下载音效")
        download_action.triggered.connect(lambda: self.download_clicked.emit(self.sound))
        menu.addAction(download_action)
        
        translate_action = Action(FluentIcon.SEND, "发送到 AI 翻译")
        translate_action.triggered.connect(lambda: self.send_to_translate.emit(self.sound))
        menu.addAction(translate_action)
        
        menu.exec(self.mapToGlobal(pos))
    
    def set_playing(self, playing: bool):
        """设置播放状态"""
        if playing:
            self.play_btn.setIcon(FluentIcon.PAUSE)
        else:
            self.play_btn.setIcon(FluentIcon.PLAY)


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
        self._playing_card: Optional[SoundCard] = None
        
        # 移除内部播放器，改用信号
        self._media_player = None 
        
        self._download_workers = []  # Keep references to prevent GC
        
        self._init_ui()
    
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
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(12, 12, 12, 12) # Compact
        search_layout.setSpacing(8)
        
        # API Key 设置行
        api_row = QHBoxLayout()
        api_label = BodyLabel("API Key:")
        api_label.setFixedWidth(70)
        api_label.setStyleSheet("background: transparent;")
        api_row.addWidget(api_label)
        
        self.api_key_edit = LineEdit()
        self.api_key_edit.setPlaceholderText("输入 Freesound API Key (从 freesound.org/apiv2/apply 获取)")
        self.api_key_edit.setEchoMode(LineEdit.EchoMode.Password)
        
        # Load saved API Key
        from transcriptionist_v3.core.config import AppConfig
        saved_key = AppConfig.get("freesound.api_key", "")
        self.api_key_edit.setText(saved_key)
        
        # Save on change
        self.api_key_edit.textChanged.connect(lambda text: AppConfig.set("freesound.api_key", text))
        
        api_row.addWidget(self.api_key_edit, 1)

        # 帮助按钮 - 跳转到申请页面
        self.help_btn = TransparentToolButton(FluentIcon.QUESTION, self)
        self.help_btn.setToolTip("如何获取 API Key？")
        self.help_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://freesound.org/apiv2/apply")))
        api_row.addWidget(self.help_btn)
        
        # 测试连接按钮
        self.test_btn = PushButton("测试")
        self.test_btn.setFixedWidth(60)
        self.test_btn.clicked.connect(self._on_test_connection)
        api_row.addWidget(self.test_btn)
        
        search_layout.addLayout(api_row)
        
        # 搜索框行
        search_row = QHBoxLayout()
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索音效... (支持英文关键词，如: explosion, footsteps, rain)")
        self.search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_edit, 1)
        
        self.search_btn = PrimaryPushButton(FluentIcon.SEARCH, "搜索")
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        
        search_layout.addLayout(search_row)
        layout.addWidget(search_card)
        
        # 搜索结果区域 - Flat Design NO CARD
        
        # 结果标题行
        results_header = QHBoxLayout()
        results_header.setContentsMargins(4, 0, 4, 0)
        self.results_title = SubtitleLabel("搜索结果")
        self.results_title.setStyleSheet("background: transparent;")
        results_header.addWidget(self.results_title)
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
    
    def _on_test_connection(self):
        """测试 API 连接"""
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            InfoBar.warning(
                title="提示",
                content="请先输入 API Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return
        
        self.test_btn.setEnabled(False)
        self.test_btn.setText("...")
        
        # 使用搜索线程测试
        self._test_worker = SearchWorker(api_key, "test", 1, 1)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.start()
    
    def _on_test_finished(self, result):
        """测试完成"""
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试")
        
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
                content="API Key 有效，可以开始搜索",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
    
    def _on_search(self):
        """执行搜索"""
        query = self.search_edit.text().strip()
        api_key = self.api_key_edit.text().strip()
        
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
        
        # 启动搜索线程
        self._search_worker = SearchWorker(api_key, query, page, 15)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.start()
    
    def _on_search_finished(self, result):
        """搜索完成"""
        self.search_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
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
        self.results_title.setText(f"搜索结果 ({result.count} 个)")
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
            self._sound_cards.append(card)
            # 插入到 stretch 之前
            self.results_layout.insertWidget(self.results_layout.count() - 1, card)
    
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
        api_key = self.api_key_edit.text().strip()
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
            api_key = self.api_key_edit.text().strip()
            query = self.search_edit.text().strip()
            self._do_search(api_key, query, self._current_page)
    
    def _on_next_page(self):
        """下一页"""
        if self._current_results and self._current_results.next_page:
            self._current_page += 1
            api_key = self.api_key_edit.text().strip()
            query = self.search_edit.text().strip()
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
    
    def _on_send_to_translate(self, sound: FreesoundSound):
        """发送到AI翻译 - 先下载再发送路径"""
        # TODO: Implement download and send path
        InfoBar.info(
            title="发送到翻译",
            content=f"将下载并发送: {sound.name}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
