"""
设置页面 - 现代化设计
"""

import logging
import json
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
import shutil
import sys
import os
import subprocess


from qfluentwidgets import (
    ComboBox, FluentIcon, PushButton, PrimaryPushButton, LineEdit,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    SwitchButton, Slider, SpinBox, setTheme, Theme, InfoBar, InfoBarPosition,
    ElevatedCardWidget, ScrollArea, isDarkTheme, ProgressBar, MessageDialog
)

from transcriptionist_v3.ui.utils.workers import ModelDownloadWorker, cleanup_thread, MusicGenDownloadWorker, HyMT15DownloadWorker
from transcriptionist_v3.core.config import AppConfig

logger = logging.getLogger(__name__)


def _detect_gpu_vram() -> tuple[int | None, str]:
    """
    检测 GPU 显存大小（MB）
    
    Returns:
        (vram_mb, gpu_name): 显存大小（MB，None 表示检测失败），GPU 名称
    """
    vram_mb = None
    gpu_name = "未知"
    
    # 方法1: 尝试使用 pynvml（如果已安装）
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_mb = int(info.total / (1024 * 1024))  # 转换为 MB
        gpu_name = pynvml.nvmlDeviceGetName(handle).decode('utf-8')
        pynvml.nvmlShutdown()
        logger.info(f"Detected GPU via pynvml: {gpu_name}, {vram_mb}MB")
        return vram_mb, gpu_name
    except ImportError:
        logger.debug("pynvml not available, trying nvidia-smi")
    except Exception as e:
        logger.debug(f"pynvml detection failed: {e}")
    
    # 方法2: 使用 nvidia-smi 命令行（Windows/Linux 通用）
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            if lines:
                parts = lines[0].split(',')
                if len(parts) >= 2:
                    vram_mb = int(parts[0].strip())
                    gpu_name = parts[1].strip()
                    logger.info(f"Detected GPU via nvidia-smi: {gpu_name}, {vram_mb}MB")
                    return vram_mb, gpu_name
    except FileNotFoundError:
        logger.debug("nvidia-smi not found")
    except Exception as e:
        logger.debug(f"nvidia-smi detection failed: {e}")
    
    # 方法3: Windows 使用 wmic（只能获取总显存，不是可用显存，且可能不准确）
    if sys.platform == 'win32':
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "AdapterRAM,Name", "/format:csv"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # wmic 输出格式复杂，这里简化处理
                # 实际上 wmic 返回的是字节数，但可能不准确，所以只作为最后备选
                logger.debug("wmic detection attempted (may be inaccurate)")
        except Exception as e:
            logger.debug(f"wmic detection failed: {e}")
    
    logger.warning("GPU VRAM detection failed, using default batch_size=4")
    return None, "未知"


class SettingsPage(QWidget):
    """设置页面 - 现代化设计"""
    
    theme_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        
        self._download_thread = None
        self._download_worker = None
        
        self._musicgen_download_thread = None
        self._musicgen_download_worker = None
        
        # 避免“加载配置时触发 textChanged/valueChanged 又把默认值写回磁盘”
        self._is_loading_settings = False

        self._init_ui()
        self._load_ai_settings()
        self._load_gpu_settings()
        self._load_indexing_settings()
        self._check_model_status()
    
    def showEvent(self, event):
        """每次显示设置页时从磁盘重新加载配置，确保重启后能正确显示已保存的设置。"""
        super().showEvent(event)
        try:
            from transcriptionist_v3.core.config import get_config_manager
            get_config_manager().load()
            self._load_ai_settings()
            self._load_gpu_settings()
            self._load_indexing_settings()
        except Exception as e:
            logger.debug(f"Reload settings on show: {e}")
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)
        
        # 标题
        title = TitleLabel("设置")
        title.setStyleSheet("background: transparent;")
        layout.addWidget(title)
        
        # 滚动区域
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_content.setStyleSheet("#settingsScrollContent { background: transparent; }")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(4, 4, 12, 4)
        scroll_layout.setSpacing(16)
        
        # ═══════════════════════════════════════════════════════════
        # 外观设置
        # ═══════════════════════════════════════════════════════════
        appearance_card = ElevatedCardWidget()
        appearance_layout = QVBoxLayout(appearance_card)
        appearance_layout.setContentsMargins(20, 16, 20, 16)
        appearance_layout.setSpacing(16)
        
        appearance_title = SubtitleLabel("外观")
        appearance_layout.addWidget(appearance_title)
        
        
        # 语言
        lang_row = self._create_setting_row(
            "界面语言",
            "选择界面显示语言"
        )
        self.lang_combo = ComboBox()
        self.lang_combo.addItems(["简体中文", "English"])
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.setFixedWidth(140)
        lang_row.addWidget(self.lang_combo)
        appearance_layout.addLayout(lang_row)
        
        scroll_layout.addWidget(appearance_card)
        
        # ═══════════════════════════════════════════════════════════
        # 音频设置
        # ═══════════════════════════════════════════════════════════
        audio_card = ElevatedCardWidget()
        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(20, 16, 20, 16)
        audio_layout.setSpacing(16)
        
        audio_title = SubtitleLabel("音频")
        audio_layout.addWidget(audio_title)
        
        # 默认音量
        volume_row = self._create_setting_row(
            "默认音量",
            "播放器默认音量"
        )
        self.volume_slider = Slider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(180)
        volume_row.addWidget(self.volume_slider)
        
        self.volume_label = BodyLabel("80%")
        self.volume_label.setFixedWidth(45)
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_label.setText(f"{v}%")
        )
        volume_row.addWidget(self.volume_label)
        audio_layout.addLayout(volume_row)
        
        # 自动播放
        autoplay_row = self._create_setting_row(
            "选中时自动播放",
            "选中音效文件时自动播放"
        )
        self.autoplay_switch = SwitchButton()
        self.autoplay_switch.setChecked(True)
        autoplay_row.addWidget(self.autoplay_switch)
        audio_layout.addLayout(autoplay_row)
        
        scroll_layout.addWidget(audio_card)
        
        # ═══════════════════════════════════════════════════════════
        # AI 服务商配置 (LLM)
        # ═══════════════════════════════════════════════════════════
        ai_card = ElevatedCardWidget()
        ai_layout = QVBoxLayout(ai_card)
        ai_layout.setContentsMargins(20, 16, 20, 16)
        ai_layout.setSpacing(12)
        
        ai_title = SubtitleLabel("AI 服务商配置（翻译/语义分析）")
        ai_layout.addWidget(ai_title)
        
        # AI 模型
        model_row = self._create_setting_row(
            "基础模型",
            "用于中英互译、标签润色和语义理解"
        )
        self.model_combo = ComboBox()
        self.model_combo.addItems([
            "DeepSeek V3 (推荐)",
            "ChatGPT (GPT-4o/mini)",
            "豆包 (高并发)",
            "本地模型 (Ollama/LM Studio)"
        ])
        self.model_combo.setFixedWidth(200)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo)
        ai_layout.addLayout(model_row)
        
        # API Key（非本地模型时显示）
        self.key_row_layout = self._create_setting_row(
            "API 密钥",
            "输入对应模型的 API Key 以启用服务"
        )
        self.key_row = QWidget()
        # 避免 QWidget 自带底色导致出现“黑条”
        self.key_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.key_row.setStyleSheet("background: transparent;")
        self.key_row.setLayout(self.key_row_layout)
        self.api_key_edit = LineEdit()
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setFixedWidth(300)
        self.api_key_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.api_key_edit.textChanged.connect(self._save_ai_settings)
        self.key_row_layout.addWidget(self.api_key_edit)
        ai_layout.addWidget(self.key_row)
        
        # 本地模型区块：右栏统一宽度 460px，与上方基础模型下拉对齐
        _local_right_width = 460

        # Base URL（仅本地模型时显示）
        self.base_url_row_layout = self._create_setting_row(
            "服务器地址 (Base URL)",
            "本地模型 API 地址，如 http://localhost:1234/v1 (LM Studio) 或 11434 (Ollama)"
        )
        self.base_url_row = QWidget()
        self.base_url_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.base_url_row.setStyleSheet("background: transparent;")
        self.base_url_row.setLayout(self.base_url_row_layout)
        base_url_controls = QVBoxLayout()
        base_url_controls.setContentsMargins(0, 0, 0, 0)
        base_url_controls.setSpacing(6)
        base_url_input_row = QHBoxLayout()
        base_url_input_row.setContentsMargins(0, 0, 0, 0)
        base_url_input_row.setSpacing(8)
        self.base_url_edit = LineEdit()
        self.base_url_edit.setPlaceholderText("http://localhost:1234/v1")
        self.base_url_edit.setFixedWidth(_local_right_width - 100)
        self.base_url_edit.textChanged.connect(self._on_base_url_changed)
        base_url_input_row.addWidget(self.base_url_edit)
        self.quick_url_btn = PushButton("快速选择", self)
        self.quick_url_btn.setFixedWidth(90)
        self.quick_url_btn.clicked.connect(self._on_quick_select_base_url)
        base_url_input_row.addWidget(self.quick_url_btn)
        base_url_controls.addLayout(base_url_input_row)
        self.base_url_hint = CaptionLabel("提示：LM Studio 默认 1234；Ollama 默认 11434")
        self.base_url_hint.setTextColor(Qt.GlobalColor.gray)
        self.base_url_hint.setStyleSheet("background: transparent;")
        base_url_controls.addWidget(self.base_url_hint)
        self.base_url_row_layout.addLayout(base_url_controls)
        self.base_url_row.setVisible(False)
        ai_layout.addWidget(self.base_url_row)

        # Model Name（仅本地模型时显示）
        self.model_name_row_layout = self._create_setting_row(
            "模型名称",
            "LM Studio/Ollama 中已加载的模型名（非文件路径），如 llama3.2、qwen2.5；可留空用默认"
        )
        self.model_name_row = QWidget()
        self.model_name_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.model_name_row.setStyleSheet("background: transparent;")
        self.model_name_row.setLayout(self.model_name_row_layout)
        model_name_controls = QVBoxLayout()
        model_name_controls.setContentsMargins(0, 0, 0, 0)
        model_name_controls.setSpacing(6)
        self.model_name_edit = LineEdit()
        self.model_name_edit.setPlaceholderText("例如：llama3.2（可留空，使用默认模型）")
        self.model_name_edit.setFixedWidth(_local_right_width)
        self.model_name_edit.textChanged.connect(self._on_model_name_changed)
        model_name_controls.addWidget(self.model_name_edit)
        model_name_hint = CaptionLabel("注意：只填“模型名称”，不要填 .gguf 文件路径")
        model_name_hint.setTextColor(Qt.GlobalColor.gray)
        model_name_hint.setStyleSheet("background: transparent;")
        model_name_hint.setWordWrap(True)
        model_name_controls.addWidget(model_name_hint)
        self.model_name_row_layout.addLayout(model_name_controls)
        self.model_name_row.setVisible(False)
        ai_layout.addWidget(self.model_name_row)

        # 使用前请确保 + 测试连接（与上方右栏对齐）
        self.test_connection_row_layout = self._create_setting_row(
            "使用前请确保",
            "1) LM Studio/Ollama 已启动  2) 已加载模型  3) LM Studio 开启“允许局域网服务”"
        )
        self.test_connection_row = QWidget()
        self.test_connection_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.test_connection_row.setStyleSheet("background: transparent;")
        self.test_connection_row.setLayout(self.test_connection_row_layout)
        self.test_connection_btn = PushButton("测试连接", self)
        self.test_connection_btn.setFixedWidth(100)
        self.test_connection_btn.clicked.connect(self._on_test_local_connection)
        self.test_connection_row_layout.addWidget(self.test_connection_btn)
        self.test_connection_row.setVisible(False)
        ai_layout.addWidget(self.test_connection_row)

        scroll_layout.addWidget(ai_card)

        # ═══════════════════════════════════════════════════════════
        # AI 翻译模型配置（专用翻译模型）- 已注释（HY-MT1.5 已禁用，此模块无实际意义）
        # ═══════════════════════════════════════════════════════════
        # translation_model_card = ElevatedCardWidget()
        # translation_model_layout = QVBoxLayout(translation_model_card)
        # translation_model_layout.setContentsMargins(20, 16, 20, 16)
        # translation_model_layout.setSpacing(16)
        # 
        # translation_model_title = SubtitleLabel("AI 翻译模型（专用翻译）")
        # translation_model_layout.addWidget(translation_model_title)
        # 
        # # 通用模型开关
        # general_model_row = self._create_setting_row(
        #     "使用通用模型",
        #     "使用上方「AI 大模型配置」中设置的模型进行翻译（DeepSeek/OpenAI/本地模型等）"
        # )
        # self.use_general_model_switch = SwitchButton()
        # self.use_general_model_switch.setChecked(True)  # 默认开启通用模型
        # self.use_general_model_switch.checkedChanged.connect(self._on_general_model_switch_changed)
        # general_model_row.addWidget(self.use_general_model_switch)
        # translation_model_layout.addLayout(general_model_row)
        
        # HY-MT1.5 专用模型开关 - 已注释（模型加载慢且翻译质量不稳定）
        # hy_mt15_model_row = self._create_setting_row(
        #     "使用 HY-MT1.5 ONNX（专用翻译模型）",
        #     "使用专用翻译模型，速度更快、质量更高，需要下载约 3.6GB 模型文件"
        # )
        # self.use_hy_mt15_switch = SwitchButton()
        # self.use_hy_mt15_switch.setChecked(False)
        # self.use_hy_mt15_switch.checkedChanged.connect(self._on_hy_mt15_switch_changed)
        # hy_mt15_model_row.addWidget(self.use_hy_mt15_switch)
        # translation_model_layout.addLayout(hy_mt15_model_row)
        
        # HY-MT1.5 模型状态和管理（仅在开关开启时显示）- 已注释
        # self.hy_mt15_row_layout = self._create_setting_row(
        #     "HY-MT1.5 ONNX 模型管理",
        #     "腾讯开源的高性能翻译模型（FP16，约 3.6GB）"
        # )
        # self.hy_mt15_row = QWidget()
        # self.hy_mt15_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # self.hy_mt15_row.setStyleSheet("background: transparent;")
        # self.hy_mt15_row.setLayout(self.hy_mt15_row_layout)
        
        # hy_mt15_btn_layout = QHBoxLayout()
        # hy_mt15_btn_layout.setSpacing(8)
        
        # self.hy_mt15_status_label = CaptionLabel("未检测到模型")
        # self.hy_mt15_status_label.setTextColor(Qt.GlobalColor.gray)
        # hy_mt15_btn_layout.addWidget(self.hy_mt15_status_label)
        # hy_mt15_btn_layout.addStretch()
        
        # self.hy_mt15_download_btn = PrimaryPushButton("下载模型", self)
        # self.hy_mt15_download_btn.setFixedWidth(100)
        # self.hy_mt15_download_btn.clicked.connect(self._on_download_hy_mt15)
        
        # self.hy_mt15_open_folder_btn = PushButton(FluentIcon.FOLDER, "打开目录", self)
        # self.hy_mt15_open_folder_btn.clicked.connect(self._on_open_hy_mt15_dir)
        
        # self.hy_mt15_delete_btn = PushButton(FluentIcon.DELETE, "删除", self)
        # self.hy_mt15_delete_btn.clicked.connect(self._on_delete_hy_mt15)
        
        # hy_mt15_btn_layout.addWidget(self.hy_mt15_open_folder_btn)
        # hy_mt15_btn_layout.addWidget(self.hy_mt15_delete_btn)
        # hy_mt15_btn_layout.addWidget(self.hy_mt15_download_btn)
        
        # self.hy_mt15_row_layout.addLayout(hy_mt15_btn_layout)
        
        # # 下载进度条
        # self.hy_mt15_download_progress = ProgressBar()
        # self.hy_mt15_download_progress.setVisible(False)
        # self.hy_mt15_row_layout.addWidget(self.hy_mt15_download_progress)
        
        # translation_model_layout.addWidget(self.hy_mt15_row)
        
        # # 提示信息
        # hy_mt15_hint = CaptionLabel("💡 专用翻译模型会用于所有“翻译/中英互转”环节（批量翻译、标签翻译、在线搜索翻译等）；语义向量、智能打标推理、音乐生成本身仍使用各自模型。")
        # hy_mt15_hint.setTextColor(Qt.GlobalColor.gray)
        # hy_mt15_hint.setWordWrap(True)
        # translation_model_layout.addWidget(hy_mt15_hint)
        
        # scroll_layout.addWidget(translation_model_card)  # 已注释：HY-MT1.5 已禁用，此模块无实际意义

        # ═══════════════════════════════════════════════════════════
        # AI 批量翻译性能（输入框 + 网络单独一行）
        # ═══════════════════════════════════════════════════════════
        translate_card = ElevatedCardWidget()
        translate_layout = QVBoxLayout(translate_card)
        translate_layout.setContentsMargins(20, 16, 20, 16)
        translate_layout.setSpacing(12)

        translate_title = SubtitleLabel("AI 批量翻译性能")
        translate_layout.addWidget(translate_title)

        # 批次大小（输入框）
        batch_row = self._create_setting_row(
            "批次大小",
            "一次请求中要翻译的文件名数量。批次越大，总请求次数越少，但单次耗时更长。"
        )
        self.translate_batch_spin = SpinBox()
        self.translate_batch_spin.setRange(5, 200)
        self.translate_batch_spin.setValue(40)
        self.translate_batch_spin.setFixedWidth(200)  # 与网络环境下拉框同宽
        self._translate_perf_signals_connected = False
        batch_row.addWidget(self.translate_batch_spin)
        translate_layout.addLayout(batch_row)

        # 并发请求数（输入框）
        conc_row = self._create_setting_row(
            "并发请求数",
            "同时向模型发起的请求数。并发越高翻译越快，但更容易触发限流。"
        )
        self.translate_conc_spin = SpinBox()
        self.translate_conc_spin.setRange(1, 32)
        self.translate_conc_spin.setValue(20)
        self.translate_conc_spin.setFixedWidth(200)  # 与网络环境下拉框同宽
        conc_row.addWidget(self.translate_conc_spin)
        translate_layout.addLayout(conc_row)

        # 网络环境（单独一行，用于推荐区间）
        network_row = self._create_setting_row(
            "网络环境",
            "用于推荐并发区间：一般网络 / 良好网络 / 局域网·机房同区"
        )
        self.network_profile_combo = ComboBox()
        self.network_profile_combo.addItems([
            "一般网络",
            "良好网络",
            "局域网 / 机房同区"
        ])
        self.network_profile_combo.setFixedWidth(200)
        network_row.addWidget(self.network_profile_combo)
        translate_layout.addLayout(network_row)

        # 推荐提示
        self.translate_conc_hint = CaptionLabel("并发/批次建议会根据模型和网络环境自动给出区间提示。")
        self.translate_conc_hint.setTextColor(Qt.GlobalColor.gray)
        translate_layout.addWidget(self.translate_conc_hint)

        scroll_layout.addWidget(translate_card)

        # ═══════════════════════════════════════════════════════════
        # 导入音效性能管理
        # ═══════════════════════════════════════════════════════════
        performance_card = ElevatedCardWidget()
        performance_layout = QVBoxLayout(performance_card)
        performance_layout.setContentsMargins(20, 16, 20, 16)
        performance_layout.setSpacing(16)
        
        performance_title = SubtitleLabel("导入音效性能管理")
        performance_layout.addWidget(performance_title)
        
        # 库扫描/元数据提取并行数（导入音效库时使用，支持百万级分批）
        from transcriptionist_v3.core.config import get_default_scan_workers
        scan_workers_default = get_default_scan_workers()
        scan_row = self._create_setting_row(
            "库扫描并行数",
            "导入音效库时提取元数据使用的进程数，根据 CPU 自动检测；超大批量会按批处理并流式输出"
        )
        self.scan_workers_combo = ComboBox()
        self.scan_workers_combo.addItems([
            "自动（根据 CPU）",
            "2", "4", "8", "16", "32", "64",
            "自定义..."
        ])
        self.scan_workers_combo.setFixedWidth(200)
        self.scan_workers_combo.currentIndexChanged.connect(self._on_scan_workers_changed)
        scan_row.addWidget(self.scan_workers_combo)
        self.scan_workers_spin = SpinBox()
        self.scan_workers_spin.setRange(1, 64)
        self.scan_workers_spin.setValue(min(scan_workers_default, 64))
        self.scan_workers_spin.setFixedWidth(100)
        self.scan_workers_spin.setVisible(False)
        self.scan_workers_spin.valueChanged.connect(self._save_performance_settings)
        scan_row.addWidget(self.scan_workers_spin)
        scan_hint = CaptionLabel(
            f"根据检测到的 CPU 核心数推荐: {scan_workers_default} 个进程（导入百万级音效时会按批处理，可自行调整）。"
        )
        scan_hint.setTextColor(Qt.GlobalColor.gray)
        performance_layout.addWidget(scan_hint)
        performance_layout.addLayout(scan_row)
        
        scroll_layout.addWidget(performance_card)
        
        # ═══════════════════════════════════════════════════════════
        # AI 检索性能设置
        # ═══════════════════════════════════════════════════════════
        indexing_card = ElevatedCardWidget()
        indexing_layout = QVBoxLayout(indexing_card)
        indexing_layout.setContentsMargins(20, 16, 20, 16)
        indexing_layout.setSpacing(16)
        
        indexing_title = SubtitleLabel("AI 检索性能设置")
        indexing_layout.addWidget(indexing_title)
        
        # GPU 加速（AI 检索用）：预处理（波形→Mel）与推理（Mel→向量）均使用 GPU（ONNX+DirectML）
        vram_mb, gpu_name = _detect_gpu_vram()
        # 推荐批量：显存(MB)/512，约每批占 512MB，限制 2–16（如 6GB→12、8GB→16）
        if vram_mb and vram_mb > 0:
            recommended_batch_size = max(2, min(16, int(vram_mb / 512)))
        else:
            recommended_batch_size = 4
        self._recommended_batch_size = recommended_batch_size
        
        gpu_row = self._create_setting_row(
            "GPU 加速",
            "开启后预处理（波形→Mel）与推理（Mel→向量）均使用 GPU（ONNX+DirectML）；关闭则均使用 CPU。批量大小仅在开启时生效。"
        )
        gpu_combo_options = [
            "关",
            "开（推荐）",
            "开（批量 4）",
            "开（批量 8）",
            "开（批量 12）",
            "自定义..."
        ]
        self.gpu_acceleration_combo = ComboBox()
        self.gpu_acceleration_combo.addItems(gpu_combo_options)
        self.gpu_acceleration_combo.setFixedWidth(220)
        self.gpu_acceleration_combo.currentIndexChanged.connect(self._on_gpu_acceleration_changed)
        gpu_row.addWidget(self.gpu_acceleration_combo)
        
        self.gpu_batch_spin = SpinBox()
        self.gpu_batch_spin.setRange(1, 64)
        self.gpu_batch_spin.setValue(recommended_batch_size)
        self.gpu_batch_spin.setFixedWidth(100)
        self.gpu_batch_spin.setVisible(False)
        self.gpu_batch_spin.valueChanged.connect(self._save_performance_settings)
        gpu_row.addWidget(self.gpu_batch_spin)
        
        if vram_mb:
            vram_text = f"{vram_mb // 1024}GB" if vram_mb >= 1024 else f"{vram_mb}MB"
            gpu_hint_text = f"检测到 {gpu_name} ({vram_text})，推荐批量 {recommended_batch_size}。关闭时预处理与推理均使用 CPU。"
        else:
            gpu_hint_text = "未检测到 NVIDIA GPU，可关闭 GPU 加速或使用较小批量。"
        gpu_hint = CaptionLabel(gpu_hint_text)
        gpu_hint.setTextColor(Qt.GlobalColor.gray)
        gpu_hint.setWordWrap(True)
        indexing_layout.addWidget(gpu_hint)
        indexing_layout.addLayout(gpu_row)
        
        # 块大小：根据检测到的内存大小按公式计算（约 80 文件/GB），不硬编码档位
        from transcriptionist_v3.core.config import get_recommended_indexing_chunk_size
        recommended_chunk = get_recommended_indexing_chunk_size()
        chunk_size_row = self._create_setting_row(
            "块大小（每块文件数）",
            "建立索引时每块处理的文件数，主要影响内存占用。根据本机内存大小计算推荐值。"
        )
        self.chunk_size_spin = SpinBox()
        self.chunk_size_spin.setRange(100, 3000)
        self.chunk_size_spin.setValue(recommended_chunk)
        self.chunk_size_spin.setFixedWidth(220)  # 与 GPU 加速下拉同宽，右侧对齐
        self.chunk_size_spin.setToolTip(
            "每块处理的文件数（100–3000）。\n"
            "• 块越大：单块内存占用越高，块数少、多进程起停少。\n"
            "• 块越小：内存更省，进度更新更频繁；块数过多会变慢。\n"
            "推荐值按本机内存 GB×80 计算，可自行调整。"
        )
        self.chunk_size_spin.valueChanged.connect(self._on_chunk_settings_changed)
        chunk_size_row.addWidget(self.chunk_size_spin)
        indexing_layout.addLayout(chunk_size_row)
        try:
            from transcriptionist_v3.core.utils import get_system_ram_gb
            ram_gb = get_system_ram_gb()
            chunk_hint = CaptionLabel(f"根据检测到的内存 {ram_gb:.1f}GB 计算，当前推荐 {recommended_chunk}（约 80 文件/GB）。")
        except Exception:
            chunk_hint = CaptionLabel(f"当前推荐块大小 {recommended_chunk}（根据本机内存计算）。")
        chunk_hint.setTextColor(Qt.GlobalColor.gray)
        indexing_layout.addWidget(chunk_hint)
        
        scroll_layout.addWidget(indexing_card)
        
        # ═══════════════════════════════════════════════════════════
        # AI 模型管理 (本地)
        # ═══════════════════════════════════════════════════════════
        model_card = ElevatedCardWidget()
        model_layout = QVBoxLayout(model_card)
        model_layout.setContentsMargins(20, 16, 20, 16)
        model_layout.setSpacing(16)
        
        model_title = SubtitleLabel("AI 模型管理")
        model_layout.addWidget(model_title)
        
        # CLAP 模型状态
        clap_row = self._create_setting_row(
            "AI 检索模型 (CLAP)",
            "用于语义搜索和声音分类 (DirectML 加速)"
        )
        
        # 按钮容器
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.download_btn = PrimaryPushButton("下载模型", self)
        self.download_btn.setFixedWidth(100)
        self.download_btn.clicked.connect(self._on_download_model)
        
        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "打开目录", self)
        self.open_folder_btn.clicked.connect(self._on_open_model_dir)
        
        self.delete_btn = PushButton(FluentIcon.DELETE, "删除", self)
        self.delete_btn.clicked.connect(self._on_delete_model)
        
        self.model_status_label = CaptionLabel("未检测到模型")
        self.model_status_label.setTextColor(Qt.GlobalColor.gray)
        
        btn_layout.addWidget(self.model_status_label)
        btn_layout.addStretch()
        btn_layout.addWidget(self.open_folder_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.download_btn)
        
        clap_row.addLayout(btn_layout)
        model_layout.addLayout(clap_row)
        
        # ───────────────────────────────────────────────────────────
        # MusicGen 模型状态
        # ───────────────────────────────────────────────────────────
        musicgen_row = self._create_setting_row(
            "AI 音乐生成模型 (MusicGen)",
            "用于生成音乐 (FP16, ~900MB)"
        )
        
        mg_btn_layout = QHBoxLayout()
        mg_btn_layout.setSpacing(8)
        
        self.mg_download_btn = PrimaryPushButton("下载模型", self)
        self.mg_download_btn.setFixedWidth(100)
        self.mg_download_btn.clicked.connect(self._on_download_musicgen)
        
        self.mg_status_label = CaptionLabel("未检测到模型")
        self.mg_status_label.setTextColor(Qt.GlobalColor.gray)
        
        mg_btn_layout.addWidget(self.mg_status_label)
        mg_btn_layout.addStretch()
        
        self.mg_open_folder_btn = PushButton(FluentIcon.FOLDER, "打开目录", self)
        self.mg_open_folder_btn.clicked.connect(self._on_open_musicgen_dir)
        mg_btn_layout.addWidget(self.mg_open_folder_btn)
        
        self.mg_delete_btn = PushButton(FluentIcon.DELETE, "删除", self)
        self.mg_delete_btn.clicked.connect(self._on_delete_musicgen)
        mg_btn_layout.addWidget(self.mg_delete_btn)
        
        mg_btn_layout.addWidget(self.mg_download_btn)
        
        musicgen_row.addLayout(mg_btn_layout)
        model_layout.addLayout(musicgen_row)

        # ───────────────────────────────────────────────────────────
        # HY-MT1.5 翻译模型（ONNX）- 已注释（模型加载慢且翻译质量不稳定）
        # ───────────────────────────────────────────────────────────
        # hy_mt15_mgmt_row = self._create_setting_row(
        #     "AI 翻译模型 (HY-MT1.5-1.8B ONNX)",
        #     "适配所有翻译场景（批量/标签/搜索） | FP16 · 3.6GB"
        # )
        
        # hy_mt15_mgmt_btn_layout = QHBoxLayout()
        # hy_mt15_mgmt_btn_layout.setSpacing(8)
        
        # self.hy_mt15_mgmt_status_label = CaptionLabel("未检测到模型")
        # self.hy_mt15_mgmt_status_label.setTextColor(Qt.GlobalColor.gray)
        
        # self.hy_mt15_mgmt_progress = ProgressBar()
        # self.hy_mt15_mgmt_progress.setVisible(False)
        # self.hy_mt15_mgmt_progress.setFixedWidth(180)
        
        # self.hy_mt15_mgmt_open_folder_btn = PushButton(FluentIcon.FOLDER, "打开目录", self)
        # self.hy_mt15_mgmt_open_folder_btn.clicked.connect(self._on_open_hy_mt15_dir)
        
        # self.hy_mt15_mgmt_delete_btn = PushButton(FluentIcon.DELETE, "删除", self)
        # self.hy_mt15_mgmt_delete_btn.clicked.connect(self._on_delete_hy_mt15)
        
        # self.hy_mt15_mgmt_download_btn = PrimaryPushButton("下载模型", self)
        # self.hy_mt15_mgmt_download_btn.setFixedWidth(100)
        # self.hy_mt15_mgmt_download_btn.clicked.connect(self._on_download_hy_mt15)
        
        # hy_mt15_mgmt_btn_layout.addWidget(self.hy_mt15_mgmt_status_label)
        # hy_mt15_mgmt_btn_layout.addStretch()
        # hy_mt15_mgmt_btn_layout.addWidget(self.hy_mt15_mgmt_progress)
        # hy_mt15_mgmt_btn_layout.addWidget(self.hy_mt15_mgmt_open_folder_btn)
        # hy_mt15_mgmt_btn_layout.addWidget(self.hy_mt15_mgmt_delete_btn)
        # hy_mt15_mgmt_btn_layout.addWidget(self.hy_mt15_mgmt_download_btn)
        
        # hy_mt15_mgmt_row.addLayout(hy_mt15_mgmt_btn_layout)
        # model_layout.addLayout(hy_mt15_mgmt_row)
        
        
        # 进度条 (默认隐藏)
        self.download_progress = ProgressBar()
        self.download_progress.setVisible(False)
        model_layout.addWidget(self.download_progress)
        
        self.download_info_label = CaptionLabel("")
        self.download_info_label.setVisible(False)
        model_layout.addWidget(self.download_info_label)
        
        scroll_layout.addWidget(model_card)
        
        # ═══════════════════════════════════════════════════════════
        # 音频输出路径 (Audio Output Paths)
        # ═══════════════════════════════════════════════════════════
        output_card = ElevatedCardWidget()
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(20, 16, 20, 16)
        output_layout.setSpacing(16)
        
        output_title = SubtitleLabel("音频输出")
        output_layout.addWidget(output_title)
        
        # Audio Output Path (for Freesound downloads and MusicGen generation)
        download_row = self._create_setting_row(
            "音频保存路径",
            "从 Freesound 下载的音效和 AI 生成的音频保存位置"
        )
        
        self.freesound_path_edit = LineEdit()
        self.freesound_path_edit.setPlaceholderText("默认: data/downloads/freesound")
        self.freesound_path_edit.setFixedWidth(300)
        self.freesound_path_edit.textChanged.connect(self._save_freesound_settings)
        download_row.addWidget(self.freesound_path_edit)
        
        browse_btn = PushButton(FluentIcon.FOLDER, "浏览")
        browse_btn.clicked.connect(self._on_browse_freesound_path)
        download_row.addWidget(browse_btn)
        
        output_layout.addLayout(download_row)
        scroll_layout.addWidget(output_card)
        
        # ═══════════════════════════════════════════════════════════
        # 数据管理 (Data Administration)
        # ═══════════════════════════════════════════════════════════
        data_card = ElevatedCardWidget()
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(20, 16, 20, 16)
        data_layout.setSpacing(16)
        
        data_title = SubtitleLabel("数据管理")
        data_layout.addWidget(data_title)
        
        # Factory Reset
        reset_row = self._create_setting_row(
            "数据清理 (恢复出厂设置)",
            "清除所有数据（包括音效库、标签、AI 索引、配置等）并重置软件"
        )
        
        self.reset_btn = PushButton(FluentIcon.DELETE, "彻底重置软件", self)
        self.reset_btn.setFixedWidth(160)
        # Style it to look dangerous (red text/border if possible, or just standard)
        # FluentWidgets doesn't have a built-in 'DangerButton', so we just use standard
        self.reset_btn.clicked.connect(self._on_factory_reset)
        
        reset_row.addWidget(self.reset_btn)
        data_layout.addLayout(reset_row)
        
        scroll_layout.addWidget(data_card)

        # ═══════════════════════════════════════════════════════════
        # 关于（紧凑布局）
        # ═══════════════════════════════════════════════════════════
        about_card = ElevatedCardWidget()
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(16, 12, 16, 12)
        about_layout.setSpacing(6)
        
        about_title = SubtitleLabel("关于")
        about_layout.addWidget(about_title)
        
        version_label = BodyLabel("音译家 AI 音效管理工具 v1.1.0")
        version_label.setStyleSheet("background: transparent; font-weight: 500;")
        about_layout.addWidget(version_label)
        
        copyright_label = CaptionLabel("开源项目 · 免费使用 · GPL-2.0")
        copyright_label.setStyleSheet("background: transparent; color: #888888;")
        about_layout.addWidget(copyright_label)
        
        features_text = CaptionLabel("核心功能：AI 智能翻译、语义检索、标签管理、UCS 命名规范、在线资源下载")
        features_text.setStyleSheet("background: transparent; color: #999999;")
        features_text.setWordWrap(True)
        about_layout.addWidget(features_text)
        
        from PySide6.QtWidgets import QFrame
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: rgba(255, 255, 255, 0.06);")
        separator.setFixedHeight(1)
        about_layout.addWidget(separator)
        
        thanks_text = CaptionLabel("致谢：基于 Quod Libet 部分代码，感谢 Quod Libet 团队及贡献者；特别感谢 Joe Wreschnig, Michael Urman, Christoph Reiter, Nick Boultbee。")
        thanks_text.setStyleSheet("background: transparent; color: #999999;")
        thanks_text.setWordWrap(True)
        about_layout.addWidget(thanks_text)
        
        quodlibet_btn = PushButton(FluentIcon.LINK, "访问 Quod Libet 项目")
        quodlibet_btn.setFixedWidth(160)
        quodlibet_btn.setFixedHeight(32)
        quodlibet_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/quodlibet/quodlibet")))
        about_layout.addWidget(quodlibet_btn)
        
        scroll_layout.addWidget(about_card)
        
        # 底部空白
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)
    
    def _create_setting_row(self, title: str, subtitle: str) -> QHBoxLayout:
        """创建设置行（左侧文字区 + 右侧控件区）。"""
        row = QHBoxLayout()
        row.setSpacing(12)
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        info = QVBoxLayout()
        info.setSpacing(0)
        info.setContentsMargins(0, 0, 0, 0)
        info.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        title_label = BodyLabel(title)
        # 确保背景透明，避免在暗色主题下出现“黑块”
        title_label.setStyleSheet("background: transparent;")
        info.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)
        
        subtitle_label = CaptionLabel(subtitle)
        subtitle_label.setStyleSheet("background: transparent;")
        info.addWidget(subtitle_label, 0, Qt.AlignmentFlag.AlignLeft)
        
        row.addLayout(info, 1)
        
        return row
    
    
    def _get_model_dir(self) -> Path:
        """获取模型存储目录"""
        # 使用 runtime_config 获取正确的数据目录
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        data_dir = get_data_dir()
        return data_dir / "models" / "larger-clap-general"

    def _check_model_status(self):
        """检查 CLAP（larger_clap_general）是否已下载：优先检查 model.onnx，否则检查 audio_model + text_model"""
        model_dir = self._get_model_dir()
        unified_onnx = model_dir / "onnx" / "model.onnx"
        audio_onnx = model_dir / "onnx" / "audio_model.onnx"
        text_onnx = model_dir / "onnx" / "text_model.onnx"
        tokenizer_json = model_dir / "tokenizer.json"
        
        # 优先检查统一模型
        has_unified = unified_onnx.exists() and unified_onnx.stat().st_size > 0
        has_separate = (audio_onnx.exists() and audio_onnx.stat().st_size > 0
                       and text_onnx.exists() and text_onnx.stat().st_size > 0)
        has_tokenizer = tokenizer_json.exists()
        
        if (has_unified or has_separate) and has_tokenizer:
            model_type = "统一模型" if has_unified else "双模型"
            self.model_status_label.setText(f"模型已就绪 ({model_type})")
            self.model_status_label.setTextColor(Qt.GlobalColor.green)
            self.download_btn.setText("重新下载")
            self.download_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
        else:
            self.model_status_label.setText("未检测到模型")
            self.model_status_label.setTextColor(Qt.GlobalColor.gray)
            self.download_btn.setText("下载模型")
            self.download_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True) # Always allow opening folder
            self.delete_btn.setEnabled(False)

        # check MusicGen
        from transcriptionist_v3.application.ai_engine.musicgen.downloader import MusicGenDownloader
        mg_downloader = MusicGenDownloader()
        if mg_downloader.is_installed():
            self.mg_status_label.setText("模型已就绪 (FP16)")
            self.mg_status_label.setTextColor(Qt.GlobalColor.green)
            self.mg_download_btn.setText("重新下载")
            self.mg_open_folder_btn.setEnabled(True)
            self.mg_delete_btn.setEnabled(True)
        else:
            missing = len(mg_downloader.get_missing_files())
            if missing < len(MusicGenDownloader.MODEL_CONFIGS):
                 self.mg_status_label.setText(f"下载不完整 (缺 {missing} 文件)")
                 self.mg_status_label.setTextColor(Qt.GlobalColor.darkYellow)
                 self.mg_download_btn.setText("继续下载")
                 self.mg_open_folder_btn.setEnabled(True)
                 self.mg_delete_btn.setEnabled(True) # Allow deleting partial downloads
            else:
                 self.mg_status_label.setText("未检测到模型")
                 self.mg_status_label.setTextColor(Qt.GlobalColor.gray)
                 self.mg_download_btn.setText("下载模型")
                 self.mg_open_folder_btn.setEnabled(True)
                 self.mg_delete_btn.setEnabled(False)

    def _on_download_model(self):
        """开始下载模型"""
        model_dir = self._get_model_dir()
        
        self.download_btn.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_info_label.setVisible(True)
        self.download_info_label.setText("准备下载...")
        self.download_progress.setValue(0)
        
        # 启动线程
        self._download_thread = QThread()
        self._download_worker = ModelDownloadWorker(str(model_dir))
        self._download_worker.moveToThread(self._download_thread)
        
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        
        self._download_thread.start()
        logger.info(f"Started model download to {model_dir}")

    def _on_download_musicgen(self):
        """开始下载 MusicGen 模型"""
        self.mg_download_btn.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_info_label.setVisible(True)
        self.download_info_label.setText("准备下载 MusicGen...")
        self.download_progress.setValue(0)
        
        self._musicgen_download_thread = QThread()
        self._musicgen_download_worker = MusicGenDownloadWorker()
        self._musicgen_download_worker.moveToThread(self._musicgen_download_thread)
        
        self._musicgen_download_thread.started.connect(self._musicgen_download_worker.run)
        self._musicgen_download_worker.progress.connect(self._on_download_progress)
        self._musicgen_download_worker.finished.connect(self._on_musicgen_finished)
        self._musicgen_download_worker.error.connect(self._on_download_error)
        
        self._musicgen_download_thread.start()
        logger.info("Started MusicGen download")

    def _on_musicgen_finished(self, result):
        """MusicGen 下载完成"""
        logger.info("MusicGen download finished")
        cleanup_thread(self._musicgen_download_thread, self._musicgen_download_worker)
        
        self.download_progress.setVisible(False)
        self.download_info_label.setVisible(False)
        self.mg_download_btn.setEnabled(True)
        
        self._check_model_status()
        
        InfoBar.success(
            title="下载完成",
            content="MusicGen 模型已准备就绪",
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=3000
        )

    def _on_open_musicgen_dir(self):
        """打开 MusicGen 模型目录"""
        from transcriptionist_v3.application.ai_engine.musicgen.downloader import MusicGenDownloader
        model_dir = MusicGenDownloader().models_dir
        if not model_dir.exists():
            model_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(model_dir)))

    def _on_delete_musicgen(self):
        """删除 MusicGen 模型"""
        w = MessageDialog(
            "删除模型",
            "确定要删除已下载的 MusicGen 模型文件吗？这将释放磁盘空间，但下次使用时需要重新下载。",
            self
        )
        if w.exec():
            from transcriptionist_v3.application.ai_engine.musicgen.downloader import MusicGenDownloader
            model_dir = MusicGenDownloader().models_dir
            try:
                if model_dir.exists():
                    shutil.rmtree(model_dir)
                    model_dir.mkdir(parents=True, exist_ok=True)
                
                self._check_model_status()
                InfoBar.success(
                    title="删除成功",
                    content="MusicGen 模型文件已清理",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
            except Exception as e:
                logger.error(f"Failed to delete MusicGen model: {e}")
                InfoBar.error(
                    title="删除失败",
                    content=str(e),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )

    def _on_download_progress(self, current: int, total: int, msg: str):
        """下载进度回调"""
        self.download_progress.setValue(current)
        self.download_info_label.setText(msg)

    def _on_download_finished(self, result):
        """下载完成"""
        logger.info("Model download finished")
        cleanup_thread(self._download_thread, self._download_worker)
        
        self.download_progress.setVisible(False)
        self.download_info_label.setVisible(False)
        self.download_btn.setEnabled(True)
        
        InfoBar.success(
            title="下载完成",
            content="CLAP 模型已成功下载并安装",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000
        )
        self._check_model_status()

    def _on_download_error(self, error_msg: str):
        """下载错误"""
        logger.error(f"Model download error: {error_msg}")
        cleanup_thread(self._download_thread, self._download_worker)
        
        self.download_progress.setVisible(False)
        self.download_info_label.setText("下载失败")
        self.download_btn.setEnabled(True)
        
        InfoBar.error(
            title="下载失败",
            content=error_msg,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000
        )


    def _on_open_model_dir(self):
        """打开模型目录"""
        model_dir = self._get_model_dir()
        if not model_dir.exists():
            model_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(model_dir)))

    def _on_delete_model(self):
        """删除 AI 检索模型 (CLAP)"""
        w = MessageDialog(
            "删除检索模型",
            "确定要删除已下载的 AI 检索模型 (CLAP) 吗？\n\n"
            "这将释放磁盘空间，但下次使用语义检索功能时需要重新下载该模型。",
            self
        )
        w.yesButton.setText("确认删除")
        w.cancelButton.setText("取消")
        
        if w.exec():
            # 仅删除 CLAP 模型目录
            clap_dir = self._get_model_dir()
            
            try:
                if clap_dir.exists():
                    shutil.rmtree(clap_dir)
                    clap_dir.mkdir(parents=True, exist_ok=True)
                    self._check_model_status()
                    InfoBar.success(
                        title="删除成功",
                        content="AI 检索模型 (CLAP) 文件已删除，下次使用语义检索时需要重新下载。",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000
                    )
                else:
                    InfoBar.info(
                        title="提示",
                        content="未检测到可删除的 CLAP 模型文件。",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000
                    )
            except Exception as e:
                logger.error(f"Failed to delete CLAP model: {e}")
                InfoBar.error(
                    title="删除失败",
                    content=str(e),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )

    def _on_factory_reset(self):
        """执行恢复出厂设置"""
        w = MessageDialog(
            "⚠️ 危险操作：完全重置软件",
            "确定要清除软件产生的所有数据吗？此操作不可撤销！\n\n"
            "将删除的内容：\n"
            "• 音效库数据库（所有音频文件记录、标签、元数据）\n"
            "• AI 检索索引和缓存\n"
            "• 所有项目数据\n"
            "• 配置文件（API Key、偏好设置等）\n"
            "• 数据备份文件\n"
            "• 术语表和命名规则\n"
            "• AI 模型文件（CLAP、MusicGen）\n"
            "• 运行日志\n\n"
            "注意：音频源文件不会被删除，只删除软件管理的数据。\n"
            "操作完成后，软件将自动重启并恢复到初始状态。",
            self
        )
        w.yesButton.setText("确认重置")
        w.cancelButton.setText("取消")
        
        if w.exec():
            try:
                # 使用 runtime_config 获取正确的路径（支持开发和打包环境）
                from transcriptionist_v3.runtime.runtime_config import get_app_root, get_data_dir, get_config_dir
                
                app_root = get_app_root()
                data_dir = get_data_dir()
                config_dir = get_config_dir()
                
                deleted_items = []
                
                # 1. 配置文件
                config_path = config_dir / "config.json"
                if config_path.exists():
                    config_path.unlink()
                    deleted_items.append("配置文件")
                    logger.info("Deleted config.json")
                
                # 2. 数据库目录（包含主数据库和备份）
                database_dir = data_dir / "database"
                if database_dir.exists():
                    shutil.rmtree(database_dir)
                    database_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("数据库")
                    logger.info("Deleted database directory")
                
                # 3. AI 索引
                index_dir = data_dir / "index"
                if index_dir.exists():
                    shutil.rmtree(index_dir)
                    index_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("AI 索引")
                    logger.info("Deleted index directory")
                
                # 4. 缓存
                cache_dir = data_dir / "cache"
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("缓存")
                    logger.info("Deleted cache directory")
                
                # 5. 项目数据
                projects_dir = data_dir / "projects"
                if projects_dir.exists():
                    shutil.rmtree(projects_dir)
                    projects_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("项目数据")
                    logger.info("Deleted projects directory")
                
                # 6. 备份
                backups_dir = data_dir / "backups"
                if backups_dir.exists():
                    shutil.rmtree(backups_dir)
                    backups_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("备份文件")
                    logger.info("Deleted backups directory")
                
                # 7. 数据文件（术语表、命名规则等）
                data_files = [
                    data_dir / "cleaning_rules.json",
                    data_dir / "glossary.json",
                    data_dir / "naming_settings.json"
                ]
                for data_file in data_files:
                    if data_file.exists():
                        data_file.unlink()
                        logger.info(f"Deleted {data_file.name}")
                deleted_items.append("数据文件")
                
                # 8. AI 模型
                models_dir = data_dir / "models"
                if models_dir.exists():
                    shutil.rmtree(models_dir)
                    models_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("AI 模型")
                    logger.info("Deleted models directory")
                
                # 9. 日志
                logs_dir = data_dir / "logs"
                if logs_dir.exists():
                    shutil.rmtree(logs_dir)
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    deleted_items.append("日志")
                    logger.info("Deleted logs directory")
                
                logger.info(f"Factory reset completed. Deleted: {', '.join(deleted_items)}")
                logger.info("Restarting application...")
                
                # 重启应用
                subprocess.Popen([sys.executable] + sys.argv)
                
                # 退出当前进程
                from PySide6.QtWidgets import QApplication
                QApplication.quit()
                
            except Exception as e:
                logger.error(f"Factory reset failed: {e}", exc_info=True)
                InfoBar.error(
                    title="重置失败",
                    content=f"清理数据时发生错误：{str(e)}\n\n请尝试手动删除以下目录：\n• data/database\n• data/cache\n• data/index\n• config",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=8000
                )

    def _on_model_changed(self, index: int):
        """模型选择改变时的处理"""
        is_local = (index == 3)  # 本地模型是第4个选项（索引3）
        
        # 显示/隐藏相关控件
        self.key_row.setVisible(not is_local)
        self.base_url_row.setVisible(is_local)
        self.model_name_row.setVisible(is_local)
        self.test_connection_row.setVisible(is_local)
        
        # 如果是本地模型，显示使用说明
        if is_local:
            self._show_local_model_help()
        
        # 保存设置
        self._save_ai_settings()
        
        # 更新性能推荐提示
        self._update_translate_perf_hint()
    
    def _on_base_url_changed(self, text: str):
        """Base URL 改变时的验证和提示"""
        text = text.strip()
        
        # 自动修正常见错误
        if text and not text.startswith("http"):
            # 如果用户只输入了端口号，自动补全
            if text.isdigit():
                text = f"http://localhost:{text}/v1"
                self.base_url_edit.setText(text)
            elif text.startswith("localhost:") or text.startswith("127.0.0.1:"):
                if not text.startswith("http://"):
                    text = f"http://{text}"
                if not text.endswith("/v1"):
                    text = f"{text}/v1"
                self.base_url_edit.setText(text)
        
        # 检查常见错误路径
        if "/v8" in text or "/v2" in text or "/v3" in text:
            InfoBar.warning(
                title="路径可能不正确",
                content=f"检测到路径 '{text.split('/')[-1]}'，LM Studio/Ollama 通常使用 /v1 路径。\n已自动修正为 /v1",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000
            )
            # 自动修正
            corrected = text.rsplit("/", 1)[0] + "/v1"
            self.base_url_edit.setText(corrected)
        
        self._save_ai_settings()
    
    def _on_model_name_changed(self, text: str):
        """模型名称改变时的验证"""
        text = text.strip()
        
        # 检查是否填写了文件路径（常见错误）
        if text and (".gguf" in text.lower() or "/" in text or "\\" in text):
            if ".gguf" in text.lower():
                InfoBar.warning(
                    title="模型名称格式提醒",
                    content="检测到文件路径格式。请填写在 LM Studio/Ollama 中显示的模型名称（如 llama3.2），而不是 .gguf 文件路径。\n如果留空，将使用默认模型。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000
                )
            elif "/" in text or "\\" in text:
                InfoBar.warning(
                    title="模型名称格式提醒",
                    content="模型名称不应包含路径分隔符。请填写在 LM Studio/Ollama 中显示的模型名称（如 llama3.2），而不是文件路径。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000
                )
        
        self._save_ai_settings()
    
    def _on_quick_select_base_url(self):
        """快速选择 Base URL"""
        from PySide6.QtWidgets import QMenu
        
        menu = QMenu(self)
        
        lm_studio_action = menu.addAction("LM Studio (http://localhost:1234/v1)")
        ollama_action = menu.addAction("Ollama (http://localhost:11434/v1)")
        menu.addSeparator()
        custom_action = menu.addAction("自定义...")
        
        action = menu.exec(self.base_url_edit.mapToGlobal(self.base_url_edit.rect().bottomLeft()))
        
        if action == lm_studio_action:
            self.base_url_edit.setText("http://localhost:1234/v1")
        elif action == ollama_action:
            self.base_url_edit.setText("http://localhost:11434/v1")
        elif action == custom_action:
            # 保持当前值，让用户手动编辑
            pass
    
    def _show_local_model_help(self):
        """显示本地模型使用说明"""
        InfoBar.info(
            title="本地模型使用提示",
            content="使用本地模型前，请确保：\n"
                   "1. LM Studio/Ollama 已启动\n"
                   "2. 已在 LM Studio/Ollama 中加载模型\n"
                   "3. LM Studio 需开启「允许局域网服务」\n"
                   "4. 点击「测试连接」验证配置是否正确",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=8000
        )
    
    def _save_ai_settings(self):
        """保存 AI 设置到全局配置"""
        from transcriptionist_v3.core.config import AppConfig

        # 初始化/回填控件时不要触发保存（否则会把控件默认值写回磁盘，覆盖用户配置）
        if getattr(self, "_is_loading_settings", False):
            return
        
        # Save Model Index
        model_idx = self.model_combo.currentIndex()
        AppConfig.set("ai.model_index", model_idx)
        
        # Save API Key（本地模型时可为空）
        api_key = self.api_key_edit.text().strip()
        AppConfig.set("ai.api_key", api_key)
        
        # 保存本地模型配置（如果选择了本地模型）
        if model_idx == 3:
            base_url = self.base_url_edit.text().strip()
            model_name = self.model_name_edit.text().strip()
            AppConfig.set("ai.local_base_url", base_url)
            AppConfig.set("ai.local_model_name", model_name)
        
        # 保存翻译批次大小 & 并发设置
        batch_size = self.translate_batch_spin.value()
        conc = self.translate_conc_spin.value()

        AppConfig.set("ai.translate_chunk_size", int(batch_size))
        AppConfig.set("ai.translate_concurrency", int(conc))

        # 网络环境
        profile_map = {0: "normal", 1: "good", 2: "lan"}
        profile = profile_map.get(self.network_profile_combo.currentIndex(), "normal")
        AppConfig.set("ai.translate_network_profile", profile)

        # 强制保存配置到磁盘（确保重启后能加载）
        try:
            from transcriptionist_v3.core.config import get_config_manager
            config_manager = get_config_manager()
            saved = config_manager.save()
            if saved:
                # 验证保存的值是否正确
                saved_batch = AppConfig.get("ai.translate_chunk_size", None)
                saved_conc = AppConfig.get("ai.translate_concurrency", None)
                saved_profile = AppConfig.get("ai.translate_network_profile", None)
                logger.info(f"AI Settings Saved: Model Idx={model_idx}, batch={batch_size}, conc={conc}, profile={profile}")
                logger.info(f"AI Settings Verified: batch={saved_batch}, conc={saved_conc}, profile={saved_profile}")
            else:
                logger.error("Failed to save AI settings to disk! Check config file permissions.")
        except Exception as e:
            logger.error(f"Error saving AI settings: {e}", exc_info=True)
        
        # 更新提示
        self._update_translate_perf_hint()
        
    def _load_ai_settings(self):
        """加载 AI 设置"""
        from transcriptionist_v3.core.config import AppConfig

        self._is_loading_settings = True
        try:
            model_idx = AppConfig.get("ai.model_index", 0)
            api_key = AppConfig.get("ai.api_key", "")

            # 回填控件时显式屏蔽信号，避免触发 _save_ai_settings 把默认值写回
            self.model_combo.blockSignals(True)
            self.api_key_edit.blockSignals(True)
            self.model_combo.setCurrentIndex(model_idx)
            self.api_key_edit.setText(api_key)
            self.model_combo.blockSignals(False)
            self.api_key_edit.blockSignals(False)

            # 加载本地模型配置
            base_url = AppConfig.get("ai.local_base_url", "http://localhost:1234/v1")
            model_name = AppConfig.get("ai.local_model_name", "")
            self.base_url_edit.setText(base_url)
            self.model_name_edit.setText(model_name)

            # 根据模型类型显示/隐藏控件
            is_local = (model_idx == 3)
            self.key_row.setVisible(not is_local)
            self.base_url_row.setVisible(is_local)
            self.model_name_row.setVisible(is_local)
            self.test_connection_row.setVisible(is_local)

            # 加载翻译批次大小 & 并发设置（带默认值）
            # 先断开信号，避免设置值时触发保存
            if hasattr(self, '_translate_perf_signals_connected') and self._translate_perf_signals_connected:
                try:
                    self.translate_batch_spin.valueChanged.disconnect(self._on_translate_perf_changed)
                    self.translate_conc_spin.valueChanged.disconnect(self._on_translate_perf_changed)
                    self.network_profile_combo.currentIndexChanged.disconnect(self._on_translate_perf_changed)
                except Exception:
                    pass
                self._translate_perf_signals_connected = False

            batch_size = AppConfig.get("ai.translate_chunk_size", 40)
            try:
                batch_size = int(batch_size)
            except (TypeError, ValueError):
                batch_size = 40
            batch_size = max(5, min(200, batch_size))
            logger.debug(f"Loading ai.translate_chunk_size = {batch_size}")
            self.translate_batch_spin.setValue(batch_size)

            conc = AppConfig.get("ai.translate_concurrency", 20)
            try:
                conc = int(conc)
            except (TypeError, ValueError):
                conc = 20
            conc = max(1, min(32, conc))
            logger.debug(f"Loading ai.translate_concurrency = {conc}")
            self.translate_conc_spin.setValue(conc)

            profile = AppConfig.get("ai.translate_network_profile", "normal")
            profile_idx_map = {"normal": 0, "good": 1, "lan": 2}
            logger.debug(f"Loading ai.translate_network_profile = {profile}")
            self.network_profile_combo.setCurrentIndex(profile_idx_map.get(profile, 0))

            # 加载完成后，连接信号（避免初始化时触发保存）
            self.translate_batch_spin.valueChanged.connect(self._on_translate_perf_changed)
            self.translate_conc_spin.valueChanged.connect(self._on_translate_perf_changed)
            self.network_profile_combo.currentIndexChanged.connect(self._on_translate_perf_changed)
            self._translate_perf_signals_connected = True
            logger.info(f"Translation performance signals connected, loaded values: batch={batch_size}, conc={conc}, profile={profile}")

            # 加载翻译模型选择（开关形式）- 整个模块已注释，强制使用通用模型
            translation_model_type = AppConfig.get("ai.translation_model_type", "general")
            # 强制使用通用模型（HY-MT1.5 已禁用）
            if translation_model_type == "hy_mt15_onnx":
                AppConfig.set("ai.translation_model_type", "general")
                translation_model_type = "general"

            # 初始化提示文字
            self._update_translate_perf_hint()

            # Load Freesound path
            freesound_path = AppConfig.get("freesound.download_path", "")
            self.freesound_path_edit.setText(freesound_path)
        finally:
            self._is_loading_settings = False
    
    # def _on_general_model_switch_changed(self, checked: bool):
    #     """通用模型开关改变时的处理 - 已注释（整个翻译模型选择模块已移除）"""
    #     # 强制使用通用模型
    #     from transcriptionist_v3.core.config import AppConfig
    #     AppConfig.set("ai.translation_model_type", "general")
    #     self._update_translate_perf_hint()
    #     logger.info("Translation model switched to: general")
    
    # def _on_hy_mt15_switch_changed(self, checked: bool):
    #     """HY-MT1.5 模型开关改变时的处理 - 已注释（模型加载慢且翻译质量不稳定）"""
    #     pass
    
    # def _check_hy_mt15_model(self):
    #     """检查 HY-MT1.5 模型是否存在 - 已注释（模型加载慢且翻译质量不稳定）"""
    #     pass
    
    # def _is_hy_mt15_model_available(self) -> bool:
    #     """检查 HY-MT1.5 模型是否可用 - 已注释"""
    #     return False
    
    # def _on_download_hy_mt15(self):
    #     """下载 HY-MT1.5 ONNX 模型 - 已注释"""
    #     pass
    
    # def _on_hy_mt15_download_progress(self, current: int, total: int, message: str):
    #     """下载进度更新 - 已注释"""
    #     pass
    
    # def _on_hy_mt15_download_finished(self):
    #     """下载完成 - 已注释"""
    #     pass
    
    # def _on_hy_mt15_download_error(self, error_msg: str):
    #     """下载错误 - 已注释"""
    #     pass
    
    # def _on_open_hy_mt15_dir(self):
    #     """打开 HY-MT1.5 模型目录 - 已注释"""
    #     pass
    
    # def _on_delete_hy_mt15(self):
    #     """删除 HY-MT1.5 模型 - 已注释"""
    #     pass
    
    def _on_test_local_connection(self):
        """测试本地模型连接"""
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        from pathlib import Path
        
        model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        
        # 检查必需文件
        required_files = [
            "model_fp16.onnx",
            "model_fp16.onnx_data",
            "model_fp16.onnx_data_1",
            "tokenizer.json",  # tokenizer 文件
            "config.json"  # 配置文件（如果有）
        ]
        
        all_exist = all((model_dir / f).exists() for f in required_files[:3])  # 至少需要三个 ONNX 文件
        
        if all_exist:
            # 检查 tokenizer（必需）
            has_tokenizer = (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer_config.json").exists()
            if has_tokenizer:
                self.hy_mt15_status_label.setText("✅ 模型已就绪")
                self.hy_mt15_status_label.setTextColor(Qt.GlobalColor.green)
                self.hy_mt15_download_btn.setText("重新下载")
                if hasattr(self, "hy_mt15_mgmt_status_label"):
                    self.hy_mt15_mgmt_status_label.setText("✅ 模型已就绪")
                    self.hy_mt15_mgmt_status_label.setTextColor(Qt.GlobalColor.green)
                if hasattr(self, "hy_mt15_mgmt_download_btn"):
                    self.hy_mt15_mgmt_download_btn.setText("重新下载")
                # 模型完整可用时，允许删除
                if hasattr(self, "hy_mt15_delete_btn"):
                    self.hy_mt15_delete_btn.setEnabled(True)
                if hasattr(self, "hy_mt15_mgmt_delete_btn"):
                    self.hy_mt15_mgmt_delete_btn.setEnabled(True)
                # 打开目录按钮始终可用
                if hasattr(self, "hy_mt15_open_folder_btn"):
                    self.hy_mt15_open_folder_btn.setEnabled(True)
                if hasattr(self, "hy_mt15_mgmt_open_folder_btn"):
                    self.hy_mt15_mgmt_open_folder_btn.setEnabled(True)
            else:
                self.hy_mt15_status_label.setText("⚠️ 缺少 tokenizer 文件")
                self.hy_mt15_status_label.setTextColor(Qt.GlobalColor.orange)
                if hasattr(self, "hy_mt15_mgmt_status_label"):
                    self.hy_mt15_mgmt_status_label.setText("⚠️ 缺少 tokenizer 文件")
                    self.hy_mt15_mgmt_status_label.setTextColor(Qt.GlobalColor.orange)
                # 视为“半下载”状态：允许删除以便用户清理重下
                if hasattr(self, "hy_mt15_delete_btn"):
                    self.hy_mt15_delete_btn.setEnabled(True)
                if hasattr(self, "hy_mt15_mgmt_delete_btn"):
                    self.hy_mt15_mgmt_delete_btn.setEnabled(True)
                if hasattr(self, "hy_mt15_open_folder_btn"):
                    self.hy_mt15_open_folder_btn.setEnabled(True)
                if hasattr(self, "hy_mt15_mgmt_open_folder_btn"):
                    self.hy_mt15_mgmt_open_folder_btn.setEnabled(True)
        else:
            self.hy_mt15_status_label.setText("未检测到模型")
            self.hy_mt15_status_label.setTextColor(Qt.GlobalColor.gray)
            if hasattr(self, "hy_mt15_mgmt_status_label"):
                self.hy_mt15_mgmt_status_label.setText("未检测到模型")
                self.hy_mt15_mgmt_status_label.setTextColor(Qt.GlobalColor.gray)
            if hasattr(self, "hy_mt15_mgmt_download_btn"):
                self.hy_mt15_mgmt_download_btn.setText("下载模型")
            # 未检测到模型时，保持“删除”按钮为灰色不可点
            if hasattr(self, "hy_mt15_delete_btn"):
                self.hy_mt15_delete_btn.setEnabled(False)
            if hasattr(self, "hy_mt15_mgmt_delete_btn"):
                self.hy_mt15_mgmt_delete_btn.setEnabled(False)
            # 打开目录按钮依然可以用（方便用户查看/手动放文件）
            if hasattr(self, "hy_mt15_open_folder_btn"):
                self.hy_mt15_open_folder_btn.setEnabled(True)
            if hasattr(self, "hy_mt15_mgmt_open_folder_btn"):
                self.hy_mt15_mgmt_open_folder_btn.setEnabled(True)
    
    def _is_hy_mt15_model_available(self) -> bool:
        """检查 HY-MT1.5 模型是否可用"""
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        from pathlib import Path
        
        model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        required_files = [
            "model_fp16.onnx",
            "model_fp16.onnx_data",
            "model_fp16.onnx_data_1"
        ]
        
        all_exist = all((model_dir / f).exists() for f in required_files)
        has_tokenizer = (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer_config.json").exists()
        
        return all_exist and has_tokenizer
    
    def _on_download_hy_mt15(self):
        """下载 HY-MT1.5 ONNX 模型"""
        
        # 检查是否正在下载
        if hasattr(self, "_hy_mt15_download_thread") and self._hy_mt15_download_thread and self._hy_mt15_download_thread.isRunning():
            InfoBar.warning(
                title="下载中",
                content="模型正在下载中，请稍候...",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return
        
        # 创建下载线程
        self._hy_mt15_download_thread = QThread()
        self._hy_mt15_download_worker = HyMT15DownloadWorker()
        self._hy_mt15_download_worker.moveToThread(self._hy_mt15_download_thread)
        
        # 连接信号
        self._hy_mt15_download_thread.started.connect(self._hy_mt15_download_worker.run)
        self._hy_mt15_download_worker.finished.connect(self._on_hy_mt15_download_finished)
        self._hy_mt15_download_worker.error.connect(self._on_hy_mt15_download_error)
        self._hy_mt15_download_worker.progress.connect(self._on_hy_mt15_download_progress)

        # 统一进度条风格：复用模型管理卡片底部的大进度条（与 CLAP/MusicGen 一致）
        if hasattr(self, "download_progress"):
            self.download_progress.setVisible(True)
            self.download_progress.setValue(0)
        if hasattr(self, "download_info_label"):
            self.download_info_label.setVisible(True)
            self.download_info_label.setText("准备下载 HY‑MT 模型...")

        # 行内小进度条不再使用，保持隐藏（避免 UI 风格不一致）
        if hasattr(self, "hy_mt15_mgmt_progress"):
            self.hy_mt15_mgmt_progress.setVisible(False)

        self.hy_mt15_download_btn.setEnabled(False)
        self.hy_mt15_download_btn.setText("下载中...")
        if hasattr(self, "hy_mt15_mgmt_download_btn"):
            self.hy_mt15_mgmt_download_btn.setEnabled(False)
            self.hy_mt15_mgmt_download_btn.setText("下载中...")
        
        # 启动下载
        self._hy_mt15_download_thread.start()
        
        InfoBar.info(
            title="开始下载",
            content="HY-MT1.5 ONNX 模型开始下载（约 3.6GB），请保持网络连接",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000
        )
    
    def _on_hy_mt15_download_progress(self, current: int, total: int, message: str):
        """下载进度更新"""
        # 统一进度条风格：使用底部的大进度条展示百分比
        progress = 0
        if total > 0:
            progress = int((current / total) * 100)

        if hasattr(self, "download_progress"):
            self.download_progress.setVisible(True)
            self.download_progress.setValue(progress)

        # 统一与 CLAP/MusicGen 一样：用底部的提示文字展示当前阶段
        text = message or ""
        if hasattr(self, "download_info_label"):
            if text:
                self.download_info_label.setVisible(True)
                self.download_info_label.setText(f"{text} ({progress}%)...")
            else:
                self.download_info_label.setVisible(True)
                self.download_info_label.setText(f"正在下载 HY‑MT 模型 ({progress}%)...")

        # 行内小进度条保持隐藏（避免 UI 风格不一致）
        if hasattr(self, "hy_mt15_mgmt_progress"):
            self.hy_mt15_mgmt_progress.setVisible(False)

        # 状态标签保持简洁（不在右侧重复进度条信息）
        color = "#0078d4" if text.startswith("下载中") else "#888888"
        if hasattr(self, "hy_mt15_status_label"):
            self.hy_mt15_status_label.setText(text or "下载中...")
            self.hy_mt15_status_label.setStyleSheet(f"color: {color};")
        if hasattr(self, "hy_mt15_mgmt_status_label"):
            self.hy_mt15_mgmt_status_label.setText(text or "下载中...")
            self.hy_mt15_mgmt_status_label.setStyleSheet(f"color: {color};")
    
    def _on_hy_mt15_download_finished(self):
        """下载完成"""
        # 正确清理下载线程，避免下次点击仍被认为“正在下载中”
        if hasattr(self, "_hy_mt15_download_thread") and self._hy_mt15_download_thread:
            self._hy_mt15_download_thread.quit()
            self._hy_mt15_download_thread.wait()
            self._hy_mt15_download_thread = None
        
        # 统一进度条风格：隐藏底部的大进度条
        if hasattr(self, "download_progress"):
            self.download_progress.setVisible(False)
        if hasattr(self, "download_info_label"):
            self.download_info_label.setVisible(False)
            self.download_info_label.setText("")
        # 行内小进度条保持隐藏
        if hasattr(self, "hy_mt15_mgmt_progress"):
            self.hy_mt15_mgmt_progress.setVisible(False)
        
        self.hy_mt15_download_btn.setEnabled(True)
        self.hy_mt15_download_btn.setText("下载模型")
        if hasattr(self, "hy_mt15_mgmt_download_btn"):
            self.hy_mt15_mgmt_download_btn.setEnabled(True)
            self.hy_mt15_mgmt_download_btn.setText("下载模型")
        
        # 检查模型
        self._check_hy_mt15_model()
        
        InfoBar.success(
            title="下载完成",
            content="HY-MT1.5 ONNX 模型下载完成，可以开始使用",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000
        )
        
        # 如果用户之前尝试开启但模型不存在，现在可以自动开启
        if hasattr(self, "use_hy_mt15_switch") and not self.use_hy_mt15_switch.isChecked():
            # 询问是否立即启用
            from qfluentwidgets import MessageDialog
            dialog = MessageDialog("下载完成", "HY-MT1.5 ONNX 模型已下载完成，是否立即启用？", self)
            if dialog.exec():
                self.use_hy_mt15_switch.setChecked(True)
    
    def _on_hy_mt15_download_error(self, error_msg: str):
        """下载错误"""
        # 正确清理下载线程，避免下次点击仍被认为“正在下载中”
        if hasattr(self, "_hy_mt15_download_thread") and self._hy_mt15_download_thread:
            self._hy_mt15_download_thread.quit()
            self._hy_mt15_download_thread.wait()
            self._hy_mt15_download_thread = None
        
        # 统一进度条风格：隐藏底部的大进度条
        if hasattr(self, "download_progress"):
            self.download_progress.setVisible(False)
        if hasattr(self, "download_info_label"):
            self.download_info_label.setVisible(False)
            self.download_info_label.setText("")
        # 行内小进度条保持隐藏
        if hasattr(self, "hy_mt15_mgmt_progress"):
            self.hy_mt15_mgmt_progress.setVisible(False)
        
        self.hy_mt15_download_btn.setEnabled(True)
        self.hy_mt15_download_btn.setText("下载模型")
        if hasattr(self, "hy_mt15_mgmt_download_btn"):
            self.hy_mt15_mgmt_download_btn.setEnabled(True)
            self.hy_mt15_mgmt_download_btn.setText("下载模型")
        
        InfoBar.error(
            title="下载失败",
            content=f"HY-MT1.5 ONNX 模型下载失败：{error_msg}\n\n请检查网络连接后重试",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=8000
        )
    
    def _on_open_hy_mt15_dir(self):
        """打开 HY-MT1.5 模型目录"""
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        from pathlib import Path
        
        model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        model_dir.mkdir(parents=True, exist_ok=True)
        
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(model_dir)))
    
    def _on_delete_hy_mt15(self):
        """删除 HY-MT1.5 模型"""
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        from pathlib import Path
        import shutil
        
        model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        
        if not model_dir.exists():
            InfoBar.warning(
                title="模型不存在",
                content="模型目录不存在，无需删除",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return
        
        # 确认删除
        from qfluentwidgets import MessageDialog
        dialog = MessageDialog("确认删除", f"确定要删除 HY-MT1.5 ONNX 模型吗？\n\n模型文件约 3.6GB，删除后需要重新下载。", self)
        dialog.setIcon(MessageDialog.Icon.Warning)
        
        if dialog.exec():
            try:
                shutil.rmtree(model_dir)
                self._check_hy_mt15_model()
                InfoBar.success(
                    title="删除成功",
                    content="HY-MT1.5 ONNX 模型已删除",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
            except Exception as e:
                logger.error(f"Failed to delete HY-MT1.5 model: {e}")
                InfoBar.error(
                    title="删除失败",
                    content=f"删除模型时发生错误：{str(e)}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000
                )
    
    def _on_test_local_connection(self):
        """测试本地模型连接"""
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        import asyncio
        
        base_url = self.base_url_edit.text().strip()
        model_name = self.model_name_edit.text().strip()
        
        if not base_url:
            InfoBar.warning(
                title="配置不完整",
                content="请先输入服务器地址 (Base URL)",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return
        
        # 模型名称可以为空（将使用默认模型），但需要检查格式
        if model_name:
            # 检查是否填写了文件路径（常见错误）
            if ".gguf" in model_name.lower() or "/" in model_name or "\\" in model_name:
                InfoBar.warning(
                    title="模型名称格式提醒",
                    content="检测到文件路径格式。请填写在 LM Studio/Ollama 中显示的模型名称（如 llama3.2），而不是文件路径。\n留空将使用默认模型。",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=5000
                )
                # 不阻止测试，但给出警告
        else:
            # 模型名称为空时，使用 "default" 或空字符串
            model_name = "default"  # 或者留空，取决于服务端实现
        
        # 禁用按钮，显示测试中
        self.test_connection_btn.setEnabled(False)
        self.test_connection_btn.setText("测试中...")
        
        # 创建测试配置
        config = AIServiceConfig(
            provider_id="local",
            api_key="",  # 本地模型通常不需要 API Key
            base_url=base_url,
            model_name=model_name,
            system_prompt="You are a helpful assistant.",
            timeout=10,
            max_tokens=10,
            temperature=0.3,
        )
        
        # 使用 QThread 运行异步测试，避免阻塞 UI
        class ConnectionTestThread(QThread):
            result_received = Signal(object)  # AIResult
            error_received = Signal(str)
            
            def __init__(self, config):
                super().__init__()
                self.config = config
            
            def run(self):
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        service = OpenAICompatibleService(self.config)
                        result = loop.run_until_complete(service.test_connection())
                        loop.run_until_complete(service.cleanup())
                        self.result_received.emit(result)
                    finally:
                        loop.close()
                except Exception as e:
                    self.error_received.emit(str(e))
        
        self._test_thread = ConnectionTestThread(config)
        self._test_thread.result_received.connect(self._on_connection_test_result)
        self._test_thread.error_received.connect(self._on_connection_test_error)
        self._test_thread.start()
    
    def _on_connection_test_result(self, result):
        """连接测试结果回调"""
        self.test_connection_btn.setEnabled(True)
        self.test_connection_btn.setText("测试连接")
        
        if result.status.value == "success":
            InfoBar.success(
                title="连接成功",
                content="本地模型服务连接正常，可以开始使用",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000
            )
        else:
            error_msg = result.error or "未知错误"
            
            # 根据错误类型提供更详细的排查建议
            base_url = self.base_url_edit.text().strip()
            model_name = self.model_name_edit.text().strip()
            
            troubleshooting = []
            
            # 检查 Base URL 格式
            if not base_url.startswith("http://"):
                troubleshooting.append("• Base URL 应以 http:// 开头")
            if "/v8" in base_url or "/v2" in base_url or "/v3" in base_url:
                troubleshooting.append("• Base URL 路径应为 /v1，不是 /v8 或其他版本")
            if not base_url.endswith("/v1"):
                troubleshooting.append("• Base URL 应以 /v1 结尾（例如：http://localhost:1234/v1）")
            
            # 检查常见问题
            troubleshooting.append("• LM Studio/Ollama 是否已启动？")
            troubleshooting.append("• 是否已在 LM Studio/Ollama 中加载模型？")
            troubleshooting.append("• LM Studio 是否开启了「允许局域网服务」？")
            
            if model_name and (".gguf" in model_name.lower() or "/" in model_name or "\\" in model_name):
                troubleshooting.append("• 模型名称不应是文件路径，应是在 LM Studio/Ollama 中显示的模型名称")
            
            troubleshooting_text = "\n".join(troubleshooting)
            
            InfoBar.error(
                title="连接失败",
                content=f"无法连接到本地模型服务\n\n错误信息：{error_msg}\n\n排查步骤：\n{troubleshooting_text}\n\n如果问题仍然存在，请检查防火墙设置或尝试重启 LM Studio/Ollama。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=12000
            )
    
    def _on_connection_test_error(self, error_msg: str):
        """连接测试错误回调"""
        self.test_connection_btn.setEnabled(True)
        self.test_connection_btn.setText("测试连接")
        
        InfoBar.error(
            title="测试失败",
            content=f"连接测试时发生错误：{error_msg}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000
        )
    
    def _save_freesound_settings(self):
        """保存 Freesound 设置"""
        from transcriptionist_v3.core.config import AppConfig
        path = self.freesound_path_edit.text().strip()
        AppConfig.set("freesound.download_path", path)
        logger.info(f"Freesound download path saved: {path}")
    
    def _on_browse_freesound_path(self):
        """浏览 Freesound 下载路径"""
        from PySide6.QtWidgets import QFileDialog
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        
        current_path = self.freesound_path_edit.text().strip()
        if not current_path:
            # Default path - 使用 runtime_config 获取数据目录
            data_dir = get_data_dir()
            current_path = str(data_dir / "downloads" / "freesound")
        
        path = QFileDialog.getExistingDirectory(
            self,
            "选择 Freesound 下载目录",
            current_path
        )
        
        if path:
            self.freesound_path_edit.setText(path)
            AppConfig.set("freesound.download_path", path)

    def _on_gpu_acceleration_changed(self, index):
        """GPU 加速选择改变：0=关，1=开（推荐），2=开(4)，3=开(8)，4=开(12)，5=自定义"""
        if index == 0:
            AppConfig.set("ai.gpu_acceleration", False)
            self.gpu_batch_spin.setVisible(False)
            self.gpu_acceleration_combo.setFixedWidth(220)
            InfoBar.success(
                title="设置已保存",
                content="已关闭 GPU 加速，预处理与推理将使用 CPU，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return
        AppConfig.set("ai.gpu_acceleration", True)
        rec = getattr(self, "_recommended_batch_size", 4)
        batch_map = {1: rec, 2: 4, 3: 8, 4: 12, 5: -1}
        value = batch_map.get(index, rec)
        if value == -1:  # 自定义
            self.gpu_batch_spin.setVisible(True)
            self.gpu_batch_spin.setValue(max(1, min(64, AppConfig.get("ai.batch_size", rec))))
            self.gpu_acceleration_combo.setFixedWidth(180)
        else:
            self.gpu_batch_spin.setVisible(False)
            self.gpu_acceleration_combo.setFixedWidth(220)
            AppConfig.set("ai.batch_size", value)
            logger.info(f"GPU acceleration on, batch_size={value}")
            InfoBar.success(
                title="设置已保存",
                content=f"已开启 GPU 加速，批量 {value}，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )

    def _on_scan_workers_changed(self, index):
        """库扫描并行数选择改变：0=自动，1-6=2/4/8/16/32/64，7=自定义"""
        preset_values = {0: None, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32, 6: 64, 7: -1}
        value = preset_values.get(index, -1)
        if value == -1:
            self.scan_workers_spin.setVisible(True)
            self.scan_workers_combo.setFixedWidth(200)
        else:
            self.scan_workers_spin.setVisible(False)
            self.scan_workers_combo.setFixedWidth(250)
            AppConfig.set("performance.scan_workers", value)
            logger.info(f"Scan workers set to: {value if value is not None else 'auto'}")
            label = "自动（根据 CPU）" if value is None else str(value)
            InfoBar.success(
                title="设置已保存",
                content=f"库扫描并行数已设置为 {label}，下次导入音效库时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )

    def _on_chunk_settings_changed(self, *args):
        """块大小变更：仅保存块大小，少于 500 文件时不拆块已固定为 500"""
        chunk_size = self.chunk_size_spin.value()
        chunk_size = max(100, min(3000, chunk_size))
        self.chunk_size_spin.blockSignals(True)
        self.chunk_size_spin.setValue(chunk_size)
        self.chunk_size_spin.blockSignals(False)
        AppConfig.set("ai.indexing_chunk_size", chunk_size)
        logger.info(f"Chunk settings saved: chunk_size={chunk_size}")
        InfoBar.success(
            title="设置已保存",
            content=f"块大小 {chunk_size}，下次建立索引时生效",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )

    def _on_translate_perf_changed(self, *args):
        """AI 批量翻译性能参数变更（批次大小 / 并发数 / 网络环境）。

        这里除了通过 AppConfig 写入外，再额外直接同步一次 config.json，
        避免某些情况下旧配置覆盖新值，导致重启后参数恢复为默认。
        """
        from transcriptionist_v3.core.config import AppConfig, get_config_manager
        
        # 如果信号还没连接完成，或正在回填控件，忽略（避免初始化时触发/覆盖用户配置）
        if (not hasattr(self, '_translate_perf_signals_connected')
                or not self._translate_perf_signals_connected
                or getattr(self, "_is_loading_settings", False)):
            return

        batch_size = self.translate_batch_spin.value()
        conc = self.translate_conc_spin.value()
        profile_map = {0: "normal", 1: "good", 2: "lan"}
        profile = profile_map.get(self.network_profile_combo.currentIndex(), "normal")

        # 先通过 AppConfig 写入内存配置，并触发一次保存
        AppConfig.set("ai.translate_chunk_size", int(batch_size))
        AppConfig.set("ai.translate_concurrency", int(conc))
        AppConfig.set("ai.translate_network_profile", profile)
        logger.debug(f"Setting ai.translate_chunk_size = {batch_size}, conc = {conc}, profile = {profile}")

        try:
            cm = get_config_manager()
            saved = cm.save()
            if not saved:
                logger.error("Failed to save AI translate perf settings to disk via ConfigManager.save()")
        except Exception as e:
            logger.error(f"Error saving AI translate perf settings via ConfigManager.save(): {e}", exc_info=True)
        else:
            logger.info(f"AI translate perf saved to disk: batch={batch_size}, conc={conc}, profile={profile}")

        # 为确保无论 ConfigManager 内部状态如何，磁盘上的 config.json 一定包含最新值，
        # 再直接对 config.json 做一次精确覆盖（只改 ai.* 相关键，其它键原样保留）。
        try:
            cm = get_config_manager()
            config_path = cm.config_path
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ai_cfg = data.get("ai") or {}
            ai_cfg["translate_chunk_size"] = int(batch_size)
            ai_cfg["translate_concurrency"] = int(conc)
            ai_cfg["translate_network_profile"] = profile
            data["ai"] = ai_cfg
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(
                "AI translate perf force-synced to %s: batch=%s, conc=%s, profile=%s",
                config_path,
                batch_size,
                conc,
                profile,
            )
        except Exception as e:
            logger.error(f"Failed to force-sync AI translate perf to config.json: {e}", exc_info=True)

        # 更新推荐提示
        self._update_translate_perf_hint()

    def _update_translate_perf_hint(self):
        """根据当前模型 + 网络环境，给出推荐并发区间提示。"""
        if not hasattr(self, "translate_conc_hint"):
            return

        # 检查是否使用专用翻译模型（通过开关状态）- HY-MT1.5 已禁用
        translation_model_type = "general"
        # if hasattr(self, "use_hy_mt15_switch") and self.use_hy_mt15_switch.isChecked():
        #     translation_model_type = "hy_mt15_onnx"
        
        # 如果使用专用翻译模型，给出不同的推荐 - HY-MT1.5 已禁用
        # if translation_model_type == "hy_mt15_onnx" and self._is_hy_mt15_model_available():
        #     # HY-MT1.5 ONNX 是本地推理，性能取决于硬件
        #     # 检测 GPU 可用性
        #     try:
        #         import onnxruntime as ort
        #         providers = ort.get_available_providers()
        #         has_gpu = "CUDAExecutionProvider" in providers or "DmlExecutionProvider" in providers
        #     except:
        #         has_gpu = False
        #     
        #     current = self.translate_conc_slider.value()
        #     batch_current = self.translate_batch_slider.value()
        #     
        #     if has_gpu:
        #         # GPU 模式：可以更高并发和批次
        #         conc_range = "20-50"
        #         batch_range = "50-150"
        #         hint_text = (
        #             f"HY-MT1.5 ONNX (GPU 加速) 建议并发区间约为 {conc_range} 路，批次大小建议 {batch_range}，"
        #             f"当前设置：并发 {current} 路，批次 {batch_current}。"
        #             f"GPU 模式下可以设置更高的并发和批次以获得最佳性能。"
        #         )
        #     else:
        #         # CPU 模式：较低并发和批次
        #         conc_range = "4-8"
        #         batch_range = "20-50"
        #         hint_text = (
        #             f"HY-MT1.5 ONNX (CPU 模式) 建议并发区间约为 {conc_range} 路，批次大小建议 {batch_range}，"
        #             f"当前设置：并发 {current} 路，批次 {batch_current}。"
        #             f"CPU 模式下建议使用较低的并发和批次以避免过载。"
        #         )
        #     
        #     self.translate_conc_hint.setText(hint_text)
        #     return

        model_idx = self.model_combo.currentIndex()
        net_idx = self.network_profile_combo.currentIndex() if hasattr(self, "network_profile_combo") else 0

        # 本地模型特殊处理
        if model_idx == 3:  # 本地模型
            # 本地模型通常可以设置更高的并发，但取决于硬件
            # 网络档位对本地模型意义不大，但可以用于表示"本地性能"
            ranges = [(10, 20), (15, 30), (20, 40)]  # 本地模型可以更高并发
            lo, hi = ranges[max(0, min(2, net_idx))]
            current = self.translate_conc_spin.value()
            
            # 批次大小推荐（本地模型可以更大批次）
            batch_current = self.translate_batch_spin.value()
            batch_recommended = "50-100" if net_idx >= 1 else "30-50"
            
            self.translate_conc_hint.setText(
                f"本地模型建议并发区间约为 {lo}–{hi} 路，批次大小建议 {batch_recommended}，"
                f"当前设置：并发 {current} 路，批次 {batch_current}。"
                f"实际性能取决于模型大小和硬件配置（GPU/CPU）。"
            )
            return

        # 模型映射到 provider
        if model_idx == 0:
            provider = "deepseek"
        elif model_idx == 1:
            provider = "openai"
        else:
            provider = "doubao"

        # 网络档位：0=一般，1=良好，2=局域网/机房
        if provider == "deepseek":
            ranges = [(4, 8), (8, 16), (12, 24)]
        elif provider == "openai":
            ranges = [(2, 3), (3, 5), (4, 6)]
        else:  # doubao / volcengine
            ranges = [(6, 12), (10, 20), (16, 24)]

        lo, hi = ranges[max(0, min(2, net_idx))]
        current = self.translate_conc_spin.value()

        provider_name = {
            "deepseek": "DeepSeek",
            "openai": "OpenAI",
            "doubao": "豆包/火山方舟",
        }.get(provider, provider)

        net_name = ["一般网络", "良好网络", "局域网 / 机房同区"][max(0, min(2, net_idx))]

        self.translate_conc_hint.setText(
            f"{provider_name} + {net_name} 建议并发区间约为 {lo}–{hi} 路，"
            f"当前设置：{current} 路。若频繁出现 429/超时，可适当下调。"
        )
    
    def _save_performance_settings(self):
        """保存性能设置"""
        # 保存自定义 GPU 批量（仅当「自定义」时）
        if getattr(self, "gpu_batch_spin", None) and self.gpu_batch_spin.isVisible():
            batch_size = self.gpu_batch_spin.value()
            if not (1 <= batch_size <= 64):
                InfoBar.error(
                    title="数值无效",
                    content="GPU 批量大小必须在 1-64 之间",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return
            AppConfig.set("ai.gpu_acceleration", True)
            AppConfig.set("ai.batch_size", batch_size)
            logger.info(f"GPU acceleration on, custom batch_size={batch_size}")
            InfoBar.success(
                title="设置已保存",
                content=f"GPU 加速已开启，批量 {batch_size}，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
        
        # 保存自定义库扫描并行数
        if self.scan_workers_spin.isVisible():
            scan_workers = self.scan_workers_spin.value()
            if not (1 <= scan_workers <= 64):
                InfoBar.error(
                    title="数值无效",
                    content="库扫描并行数必须在 1-64 之间",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return
            AppConfig.set("performance.scan_workers", scan_workers)
            logger.info(f"Scan workers saved: {scan_workers}")
            InfoBar.success(
                title="设置已保存",
                content=f"库扫描并行数已设置为 {scan_workers}，下次导入音效库时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
    
    def _save_gpu_settings(self):
        """保存自定义 batch_size（已废弃，使用 _save_performance_settings）"""
        self._save_performance_settings()
    
    def _load_gpu_settings(self):
        """加载性能设置"""
        use_gpu = AppConfig.get("ai.gpu_acceleration", True)
        batch_size = AppConfig.get("ai.batch_size", None)
        rec = getattr(self, "_recommended_batch_size", 4)
        if batch_size is None:
            vram_mb, _ = _detect_gpu_vram()
            if vram_mb and vram_mb > 0:
                batch_size = max(2, min(16, int(vram_mb / 512)))
            else:
                batch_size = 4
            AppConfig.set("ai.batch_size", batch_size)
        batch_size = int(batch_size)
        
        if not use_gpu:
            self.gpu_acceleration_combo.setCurrentIndex(0)
            self.gpu_batch_spin.setVisible(False)
        else:
            if batch_size == rec:
                self.gpu_acceleration_combo.setCurrentIndex(1)
                self.gpu_batch_spin.setVisible(False)
            elif batch_size == 4:
                self.gpu_acceleration_combo.setCurrentIndex(2)
                self.gpu_batch_spin.setVisible(False)
            elif batch_size == 8:
                self.gpu_acceleration_combo.setCurrentIndex(3)
                self.gpu_batch_spin.setVisible(False)
            elif batch_size == 12:
                self.gpu_acceleration_combo.setCurrentIndex(4)
                self.gpu_batch_spin.setVisible(False)
            else:
                self.gpu_acceleration_combo.setCurrentIndex(5)
                self.gpu_batch_spin.setValue(max(1, min(64, int(batch_size))))
                self.gpu_batch_spin.setVisible(True)
        
        # 加载库扫描并行数（None=自动，或 1-64；用 get_raw 区分「自动」与具体值）
        from transcriptionist_v3.core.config import get_config_manager
        scan_workers = get_config_manager().get_raw("performance.scan_workers")
        if scan_workers is None:
            self.scan_workers_combo.setCurrentIndex(0)
            self.scan_workers_spin.setVisible(False)
        elif scan_workers in (2, 4, 8, 16, 32, 64):
            self.scan_workers_combo.setCurrentIndex({2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6}[scan_workers])
            self.scan_workers_spin.setVisible(False)
        else:
            self.scan_workers_combo.setCurrentIndex(7)
            self.scan_workers_spin.setValue(max(1, min(64, int(scan_workers))))
            self.scan_workers_spin.setVisible(True)
    
    def _load_indexing_settings(self):
        """加载块大小设置（索引固定为平衡模式，少于 500 文件不拆块已硬编码）"""
        raw_chunk = AppConfig.get("ai.indexing_chunk_size", None)
        if raw_chunk is not None and raw_chunk != "":
            try:
                v = max(100, min(3000, int(raw_chunk)))
                self.chunk_size_spin.setValue(v)
            except (TypeError, ValueError):
                pass
        else:
            from transcriptionist_v3.core.config import get_recommended_indexing_chunk_size
            default_chunk = get_recommended_indexing_chunk_size()
            self.chunk_size_spin.setValue(default_chunk)
            AppConfig.set("ai.indexing_chunk_size", default_chunk)
            logger.info(f"Default chunk_size={default_chunk} (auto from RAM)")
        logger.info(f"Loaded chunk_size={self.chunk_size_spin.value()} (small_threshold=500 fixed)")
