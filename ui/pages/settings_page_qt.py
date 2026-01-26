"""
设置页面 - 现代化设计
"""

import logging
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
    SwitchButton, Slider, setTheme, Theme, InfoBar, InfoBarPosition,
    ElevatedCardWidget, ScrollArea, isDarkTheme, ProgressBar, MessageDialog
)

from transcriptionist_v3.ui.utils.workers import ModelDownloadWorker, cleanup_thread, MusicGenDownloadWorker
from transcriptionist_v3.core.config import AppConfig

logger = logging.getLogger(__name__)


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
        
        self._init_ui()
        self._load_ai_settings()
        self._load_gpu_settings()
        self._check_model_status()
    
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
        # AI 大模型配置 (LLM)
        # ═══════════════════════════════════════════════════════════
        ai_card = ElevatedCardWidget()
        ai_layout = QVBoxLayout(ai_card)
        ai_layout.setContentsMargins(20, 16, 20, 16)
        ai_layout.setSpacing(16)
        
        ai_title = SubtitleLabel("AI 大模型配置 (翻译/语义分析)")
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
            "豆包 (高并发)"
        ])
        self.model_combo.setFixedWidth(200)
        self.model_combo.currentIndexChanged.connect(self._save_ai_settings)
        model_row.addWidget(self.model_combo)
        ai_layout.addLayout(model_row)
        
        # API Key
        key_row = self._create_setting_row(
            "API 密钥",
            "输入对应模型的 API Key 以启用服务"
        )
        self.api_key_edit = LineEdit()
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setFixedWidth(300)
        self.api_key_edit.setEchoMode(LineEdit.EchoMode.Password)
        self.api_key_edit.textChanged.connect(self._save_ai_settings)
        key_row.addWidget(self.api_key_edit)
        ai_layout.addLayout(key_row)

        scroll_layout.addWidget(ai_card)

        # ═══════════════════════════════════════════════════════════
        # 性能管理
        # ═══════════════════════════════════════════════════════════
        performance_card = ElevatedCardWidget()
        performance_layout = QVBoxLayout(performance_card)
        performance_layout.setContentsMargins(20, 16, 20, 16)
        performance_layout.setSpacing(16)
        
        performance_title = SubtitleLabel("性能管理")
        performance_layout.addWidget(performance_title)
        
        # GPU 加速批量大小
        gpu_row = self._create_setting_row(
            "GPU 加速批量大小",
            "AI 推理时每批处理的文件数量，根据显存大小选择"
        )
        
        from qfluentwidgets import SpinBox
        
        self.batch_size_combo = ComboBox()
        self.batch_size_combo.addItems([
            "2 (适合 2GB 显存)",
            "4 (适合 4-6GB 显存，推荐)",
            "8 (适合 6-8GB 显存)",
            "16 (适合 8GB+ 显存)",
            "自定义..."
        ])
        self.batch_size_combo.setCurrentIndex(1)  # 默认 4
        self.batch_size_combo.setFixedWidth(250)
        self.batch_size_combo.currentIndexChanged.connect(self._on_batch_size_changed)
        gpu_row.addWidget(self.batch_size_combo)
        
        # 自定义输入框（默认隐藏）
        self.batch_size_spin = SpinBox()
        self.batch_size_spin.setRange(1, 64)
        self.batch_size_spin.setValue(4)
        self.batch_size_spin.setFixedWidth(100)
        self.batch_size_spin.setVisible(False)
        self.batch_size_spin.valueChanged.connect(self._save_performance_settings)
        gpu_row.addWidget(self.batch_size_spin)
        
        performance_layout.addLayout(gpu_row)
        
        # CPU 多进程并行数量
        cpu_row = self._create_setting_row(
            "CPU 音频预处理并行数",
            "音频预处理时使用的 CPU 进程数，根据 CPU 核心数选择"
        )
        
        self.cpu_processes_combo = ComboBox()
        
        # 自动检测 CPU 核心数
        import os
        cpu_count = os.cpu_count() or 4
        
        # 根据 CPU 核心数生成推荐选项
        if cpu_count >= 16:
            recommended_processes = cpu_count // 2
            self.cpu_processes_combo.addItems([
                f"4 (保守)",
                f"6 (平衡)",
                f"8 (推荐)",
                f"{recommended_processes} (激进)",
                "自定义..."
            ])
            default_index = 2  # 8 进程
        elif cpu_count >= 8:
            recommended_processes = cpu_count - 2
            self.cpu_processes_combo.addItems([
                f"2 (保守)",
                f"4 (平衡)",
                f"{recommended_processes} (推荐)",
                "自定义..."
            ])
            default_index = 2  # 推荐值
        else:
            recommended_processes = max(1, cpu_count - 1)
            self.cpu_processes_combo.addItems([
                f"1 (单进程)",
                f"2 (平衡)",
                f"{recommended_processes} (推荐)",
                "自定义..."
            ])
            default_index = 2  # 推荐值
        
        self.cpu_processes_combo.setCurrentIndex(default_index)
        self.cpu_processes_combo.setFixedWidth(250)
        self.cpu_processes_combo.currentIndexChanged.connect(self._on_cpu_processes_changed)
        cpu_row.addWidget(self.cpu_processes_combo)
        
        # 自定义输入框（默认隐藏）
        self.cpu_processes_spin = SpinBox()
        self.cpu_processes_spin.setRange(1, cpu_count)
        self.cpu_processes_spin.setValue(recommended_processes)
        self.cpu_processes_spin.setFixedWidth(100)
        self.cpu_processes_spin.setVisible(False)
        self.cpu_processes_spin.valueChanged.connect(self._save_performance_settings)
        cpu_row.addWidget(self.cpu_processes_spin)
        
        # 提示信息
        cpu_hint = CaptionLabel(f"检测到 {cpu_count} 个逻辑核心，推荐使用 {recommended_processes} 个进程")
        cpu_hint.setTextColor(Qt.GlobalColor.gray)
        performance_layout.addWidget(cpu_hint)
        
        performance_layout.addLayout(cpu_row)
        
        scroll_layout.addWidget(performance_card)
        
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
        # 关于
        # ═══════════════════════════════════════════════════════════
        about_card = ElevatedCardWidget()
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(20, 16, 20, 16)
        about_layout.setSpacing(8)
        
        about_title = SubtitleLabel("关于")
        about_layout.addWidget(about_title)
        
        version_label = BodyLabel("音译家 AI音效管理工具 v1.0.0")
        about_layout.addWidget(version_label)
        
        copyright_label = CaptionLabel("开源项目 | 免费使用")
        about_layout.addWidget(copyright_label)
        
        desc_label = CaptionLabel("集成 AI 智能翻译、语义检索、标签管理、UCS 命名规范、在线资源下载于一体的专业音效管理工具")
        about_layout.addWidget(desc_label)
        
        # 添加分隔线
        from PySide6.QtWidgets import QFrame
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: rgba(255, 255, 255, 0.1);")
        separator.setFixedHeight(1)
        about_layout.addWidget(separator)
        
        # 开源协议
        license_label = CaptionLabel("开源协议: GNU General Public License v2.0 (GPL-2.0)")
        license_label.setStyleSheet("color: #999999; background: transparent;")
        about_layout.addWidget(license_label)
        
        # 致谢信息
        thanks_title = BodyLabel("致谢")
        thanks_title.setStyleSheet("margin-top: 8px; background: transparent;")
        about_layout.addWidget(thanks_title)
        
        thanks_text = CaptionLabel(
            "本软件使用了 Quod Libet 项目的部分代码\n"
            "感谢 Quod Libet 团队及所有贡献者\n"
            "特别感谢: Joe Wreschnig, Michael Urman, Christoph Reiter, Nick Boultbee"
        )
        thanks_text.setStyleSheet("color: #999999; background: transparent; line-height: 1.5;")
        thanks_text.setWordWrap(True)
        about_layout.addWidget(thanks_text)
        
        # Quod Libet 链接按钮
        quodlibet_btn = PushButton(FluentIcon.LINK, "访问 Quod Libet 项目")
        quodlibet_btn.setFixedWidth(180)
        quodlibet_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/quodlibet/quodlibet")))
        about_layout.addWidget(quodlibet_btn)
        
        scroll_layout.addWidget(about_card)
        
        # 底部空白
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)
    
    def _create_setting_row(self, title: str, subtitle: str) -> QHBoxLayout:
        """创建设置行"""
        row = QHBoxLayout()
        row.setSpacing(12)
        
        info = QVBoxLayout()
        info.setSpacing(2)
        
        title_label = BodyLabel(title)
        info.addWidget(title_label)
        
        subtitle_label = CaptionLabel(subtitle)
        info.addWidget(subtitle_label)
        
        row.addLayout(info, 1)
        
        return row
    
    
    def _get_model_dir(self) -> Path:
        """获取模型存储目录"""
        # 使用 runtime_config 获取正确的数据目录
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        data_dir = get_data_dir()
        return data_dir / "models" / "clap-htsat-unfused"

    def _check_model_status(self):
        """检查模型是否已下载"""
        model_dir = self._get_model_dir()
        onnx_file = model_dir / "onnx" / "model.onnx"
        
        if onnx_file.exists() and onnx_file.stat().st_size > 0:
            self.model_status_label.setText("模型已就绪")
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
        """删除模型"""
        w = MessageDialog(
            "删除 AI 模型",
            "确定要删除所有已下载的 AI 模型文件吗？\n\n"
            "将删除：\n"
            "• AI 音频检索模型 (CLAP)\n"
            "• AI 音乐生成模型 (MusicGen)\n\n"
            "这将释放磁盘空间，但下次使用相关功能时需要重新下载。",
            self
        )
        w.yesButton.setText("确认删除")
        w.cancelButton.setText("取消")
        
        if w.exec():
            # 获取模型目录
            clap_dir = self._get_model_dir()
            
            # 获取 MusicGen 目录
            from transcriptionist_v3.application.ai_engine.musicgen.paths import get_models_dir as get_musicgen_dir
            musicgen_dir = get_musicgen_dir()
            
            deleted_count = 0
            errors = []
            
            try:
                # 1. Delete CLAP
                if clap_dir.exists():
                    shutil.rmtree(clap_dir)
                    clap_dir.mkdir(parents=True, exist_ok=True)
                    deleted_count += 1
                
                # 2. Delete MusicGen
                if musicgen_dir.exists():
                    shutil.rmtree(musicgen_dir)
                    musicgen_dir.mkdir(parents=True, exist_ok=True)
                    deleted_count += 1
                
                self._check_model_status()
                
                if deleted_count > 0:
                    InfoBar.success(
                        title="删除成功",
                        content="已清理所有 AI 模型文件",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000
                    )
                else:
                    InfoBar.info(
                        title="提示",
                        content="没有发现已下载的模型文件",
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2000
                    )
                    
            except Exception as e:
                logger.error(f"Failed to delete model: {e}")
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

    def _save_ai_settings(self):
        """保存 AI 设置到全局配置"""
        from transcriptionist_v3.core.config import AppConfig
        
        # Save Model Index
        model_idx = self.model_combo.currentIndex()
        AppConfig.set("ai.model_index", model_idx)
        
        # Save API Key
        api_key = self.api_key_edit.text().strip()
        AppConfig.set("ai.api_key", api_key)
        
        logger.info(f"AI Settings Saved: Local Model Idx={model_idx}")
        
    def _load_ai_settings(self):
        """加载 AI 设置"""
        from transcriptionist_v3.core.config import AppConfig
        
        model_idx = AppConfig.get("ai.model_index", 0)
        api_key = AppConfig.get("ai.api_key", "")
        
        self.model_combo.setCurrentIndex(model_idx)
        self.api_key_edit.setText(api_key)
        
        # Load Freesound path
        freesound_path = AppConfig.get("freesound.download_path", "")
        self.freesound_path_edit.setText(freesound_path)
    
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

    def _on_batch_size_changed(self, index):
        """批量大小选择改变"""
        # 预设值映射
        preset_values = {
            0: 2,   # 2GB
            1: 4,   # 4-6GB
            2: 8,   # 6-8GB
            3: 16,  # 8GB+
            4: -1   # 自定义
        }
        
        value = preset_values.get(index, 4)
        
        if value == -1:  # 自定义
            self.batch_size_spin.setVisible(True)
            self.batch_size_combo.setFixedWidth(200)
        else:
            self.batch_size_spin.setVisible(False)
            self.batch_size_combo.setFixedWidth(250)
            # 保存预设值
            AppConfig.set("ai.batch_size", value)
            logger.info(f"GPU batch_size set to: {value}")
            
            # 显示保存成功提示
            InfoBar.success(
                title="设置已保存",
                content=f"GPU 批量大小已设置为 {value}，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
    
    def _on_cpu_processes_changed(self, index):
        """CPU 进程数选择改变"""
        import os
        cpu_count = os.cpu_count() or 4
        
        # 根据 CPU 核心数生成预设值
        if cpu_count >= 16:
            preset_values = {0: 4, 1: 6, 2: 8, 3: cpu_count // 2, 4: -1}
        elif cpu_count >= 8:
            preset_values = {0: 2, 1: 4, 2: cpu_count - 2, 3: -1}
        else:
            preset_values = {0: 1, 1: 2, 2: max(1, cpu_count - 1), 3: -1}
        
        value = preset_values.get(index, -1)
        
        if value == -1:  # 自定义
            self.cpu_processes_spin.setVisible(True)
            self.cpu_processes_combo.setFixedWidth(200)
        else:
            self.cpu_processes_spin.setVisible(False)
            self.cpu_processes_combo.setFixedWidth(250)
            # 保存预设值
            AppConfig.set("ai.cpu_processes", value)
            logger.info(f"CPU processes set to: {value}")
            
            # 显示保存成功提示
            InfoBar.success(
                title="设置已保存",
                content=f"CPU 并行数已设置为 {value}，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
    
    def _save_performance_settings(self):
        """保存性能设置"""
        # 保存自定义 GPU batch_size
        if self.batch_size_spin.isVisible():
            batch_size = self.batch_size_spin.value()
            
            # 校验
            if not (1 <= batch_size <= 64):
                InfoBar.error(
                    title="数值无效",
                    content="GPU batch_size 必须在 1-64 之间",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return
            
            AppConfig.set("ai.batch_size", batch_size)
            logger.info(f"Custom GPU batch_size saved: {batch_size}")
            
            # 显示保存成功提示
            InfoBar.success(
                title="设置已保存",
                content=f"GPU 批量大小已设置为 {batch_size}，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
        
        # 保存自定义 CPU 进程数
        if self.cpu_processes_spin.isVisible():
            cpu_processes = self.cpu_processes_spin.value()
            
            import os
            cpu_count = os.cpu_count() or 4
            
            # 校验
            if not (1 <= cpu_processes <= cpu_count):
                InfoBar.error(
                    title="数值无效",
                    content=f"CPU 进程数必须在 1-{cpu_count} 之间",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return
            
            AppConfig.set("ai.cpu_processes", cpu_processes)
            logger.info(f"Custom CPU processes saved: {cpu_processes}")
            
            # 显示保存成功提示
            InfoBar.success(
                title="设置已保存",
                content=f"CPU 并行数已设置为 {cpu_processes}，下次建立索引时生效",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
    
    def _save_gpu_settings(self):
        """保存自定义 batch_size（已废弃，使用 _save_performance_settings）"""
        self._save_performance_settings()
    
    def _load_gpu_settings(self):
        """加载性能设置"""
        import os
        cpu_count = os.cpu_count() or 4
        
        # 加载 GPU batch_size
        batch_size = AppConfig.get("ai.batch_size", 4)
        
        # 映射到预设选项
        preset_map = {2: 0, 4: 1, 8: 2, 16: 3}
        if batch_size in preset_map:
            self.batch_size_combo.setCurrentIndex(preset_map[batch_size])
        else:
            # 自定义值
            self.batch_size_combo.setCurrentIndex(4)
            self.batch_size_spin.setValue(batch_size)
            self.batch_size_spin.setVisible(True)
        
        # 加载 CPU 进程数
        cpu_processes = AppConfig.get("ai.cpu_processes", None)
        
        # 如果没有配置，使用推荐值
        if cpu_processes is None:
            if cpu_count >= 16:
                cpu_processes = 8
            elif cpu_count >= 8:
                cpu_processes = cpu_count - 2
            else:
                cpu_processes = max(1, cpu_count - 1)
            AppConfig.set("ai.cpu_processes", cpu_processes)
        
        # 映射到预设选项
        if cpu_count >= 16:
            preset_map = {4: 0, 6: 1, 8: 2, cpu_count // 2: 3}
            default_index = 2
        elif cpu_count >= 8:
            preset_map = {2: 0, 4: 1, cpu_count - 2: 2}
            default_index = 2
        else:
            preset_map = {1: 0, 2: 1, max(1, cpu_count - 1): 2}
            default_index = 2
        
        if cpu_processes in preset_map:
            self.cpu_processes_combo.setCurrentIndex(preset_map[cpu_processes])
        else:
            # 自定义值
            last_index = len(preset_map)
            self.cpu_processes_combo.setCurrentIndex(last_index)
            self.cpu_processes_spin.setValue(cpu_processes)
            self.cpu_processes_spin.setVisible(True)
