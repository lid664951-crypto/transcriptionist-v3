import logging
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    ElevatedCardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    Slider,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
)

from transcriptionist_v3.core.config import AppConfig
from transcriptionist_v3.ui.utils.workers import KlingTextToAudioWorker, cleanup_thread

logger = logging.getLogger(__name__)


class AIGenerationPage(QWidget):
    """AI 音效工坊页面（可灵文本生成音效）。"""

    request_play = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiGenerationPage")

        self._duration_min_seconds, self._duration_max_seconds = self._get_duration_bounds()

        self._gen_worker = None
        self._gen_thread = None
        self._last_generated_path: Path | None = None
        self._last_task_id: str = ""

        self._init_ui()

    def _get_duration_bounds(self) -> tuple[float, float]:
        min_seconds = 1.0
        max_seconds = 10.0
        try:
            from transcriptionist_v3.application.ai_engine.providers.kling_audio import KlingAudioService

            min_seconds = float(getattr(KlingAudioService, "DURATION_MIN_SECONDS", min_seconds))
            max_seconds = float(getattr(KlingAudioService, "DURATION_MAX_SECONDS", max_seconds))
        except Exception:
            pass

        if min_seconds <= 0:
            min_seconds = 1.0
        if max_seconds <= min_seconds:
            max_seconds = min_seconds + 1.0

        return round(min_seconds, 1), round(max_seconds, 1)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        title = TitleLabel("AI 音效工坊")
        title.setObjectName("aiGenerationTitle")
        layout.addWidget(title)

        subtitle = CaptionLabel("使用可灵 AI 文本生成音效，支持任务状态追踪与结果回放")
        subtitle.setObjectName("aiGenerationSubtitle")
        layout.addWidget(subtitle)

        scroll = ScrollArea()
        scroll.setObjectName("aiGenerationScroll")
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setObjectName("aiGenerationContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 10, 0)
        content_layout.setSpacing(16)

        input_card = ElevatedCardWidget()
        input_card.setObjectName("aiGenerationInputCard")
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(20, 16, 20, 16)
        input_layout.setSpacing(12)

        input_title = SubtitleLabel("文本描述")
        input_title.setObjectName("aiGenerationInputTitle")
        input_layout.addWidget(input_title)

        self.prompt_edit = TextEdit()
        self.prompt_edit.setObjectName("aiGenerationPromptEdit")
        self.prompt_edit.setPlaceholderText("请输入音效描述，例如：雨夜中的城市街道，远处有轻微雷声")
        self.prompt_edit.setMinimumHeight(96)
        self.prompt_edit.setMaximumHeight(120)
        input_layout.addWidget(self.prompt_edit)

        hint = CaptionLabel("建议：描述场景 + 声源 + 强弱 + 节奏，可显著提升结果质量")
        hint.setObjectName("aiGenerationPromptHint")
        input_layout.addWidget(hint)

        content_layout.addWidget(input_card)

        params_card = ElevatedCardWidget()
        params_card.setObjectName("aiGenerationParamsCard")
        params_layout = QVBoxLayout(params_card)
        params_layout.setContentsMargins(20, 16, 20, 16)
        params_layout.setSpacing(12)

        params_title = SubtitleLabel("生成参数")
        params_title.setObjectName("aiGenerationParamsTitle")
        params_layout.addWidget(params_title)

        duration_row = QHBoxLayout()
        duration_row.setSpacing(10)
        duration_label = BodyLabel("时长")
        duration_label.setObjectName("aiGenerationDurationLabel")
        self.duration_value = CaptionLabel("5.0s")
        self.duration_value.setObjectName("aiGenerationDurationValue")
        self.duration_slider = Slider(Qt.Orientation.Horizontal)
        self.duration_slider.setObjectName("aiGenerationDurationSlider")
        self.duration_slider.setRange(
            int(round(self._duration_min_seconds * 10)),
            int(round(self._duration_max_seconds * 10)),
        )
        self.duration_slider.setSingleStep(1)
        default_duration = min(max(5.0, self._duration_min_seconds), self._duration_max_seconds)
        self.duration_slider.setValue(int(round(default_duration * 10)))
        self.duration_value.setText(f"{default_duration:.1f}s")
        self.duration_slider.valueChanged.connect(self._on_duration_changed)
        duration_row.addWidget(duration_label)
        duration_row.addWidget(self.duration_slider, 1)
        duration_row.addWidget(self.duration_value)
        params_layout.addLayout(duration_row)

        format_row = QHBoxLayout()
        format_row.setSpacing(10)
        format_label = BodyLabel("输出格式")
        format_label.setObjectName("aiGenerationFormatLabel")
        self.format_combo = ComboBox()
        self.format_combo.setObjectName("aiGenerationFormatCombo")
        self.format_combo.addItems(["WAV（优先）", "MP3（优先）"])
        self.format_combo.setFixedWidth(180)
        format_row.addWidget(format_label)
        format_row.addStretch(1)
        format_row.addWidget(self.format_combo)
        params_layout.addLayout(format_row)

        task_row = QHBoxLayout()
        task_row.setSpacing(10)
        task_label = BodyLabel("任务 ID")
        task_label.setObjectName("aiGenerationTaskIdLabel")
        self.task_id_edit = LineEdit()
        self.task_id_edit.setObjectName("aiGenerationTaskIdEdit")
        self.task_id_edit.setReadOnly(True)
        self.task_id_edit.setPlaceholderText("提交后自动生成")
        task_row.addWidget(task_label)
        task_row.addWidget(self.task_id_edit, 1)
        params_layout.addLayout(task_row)

        self.generate_btn = PrimaryPushButton("生成音效")
        self.generate_btn.setObjectName("aiGenerationGenerateBtn")
        self.generate_btn.setMinimumHeight(42)
        self.generate_btn.clicked.connect(self._on_generate)
        params_layout.addWidget(self.generate_btn)

        self.gen_progress = ProgressBar()
        self.gen_progress.setObjectName("aiGenerationProgress")
        self.gen_progress.setVisible(False)
        params_layout.addWidget(self.gen_progress)

        self.gen_status = CaptionLabel("")
        self.gen_status.setObjectName("aiGenerationStatus")
        self.gen_status.setVisible(False)
        params_layout.addWidget(self.gen_status)

        content_layout.addWidget(params_card)

        result_card = ElevatedCardWidget()
        result_card.setObjectName("aiGenerationResultCard")
        result_layout = QHBoxLayout(result_card)
        result_layout.setContentsMargins(20, 16, 20, 16)
        result_layout.setSpacing(10)

        self.result_label = BodyLabel("等待生成")
        self.result_label.setObjectName("aiGenerationResultLabel")
        result_layout.addWidget(self.result_label, 1)

        self.play_btn = PushButton(FluentIcon.PLAY, "播放")
        self.play_btn.setObjectName("aiGenerationPlayBtn")
        self.play_btn.setVisible(False)
        self.play_btn.clicked.connect(self._on_play_generated)
        result_layout.addWidget(self.play_btn)

        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "打开位置")
        self.open_folder_btn.setObjectName("aiGenerationOpenFolderBtn")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        result_layout.addWidget(self.open_folder_btn)

        content_layout.addWidget(result_card)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _on_duration_changed(self, value: int):
        self.duration_value.setText(f"{value / 10:.1f}s")

    def _get_duration_seconds(self) -> float:
        return round(self.duration_slider.value() / 10.0, 1)

    def _get_preferred_format(self) -> str:
        return "wav" if self.format_combo.currentIndex() == 0 else "mp3"

    def _build_provider_config(self) -> dict:
        provider = str(AppConfig.get("ai.audio_provider", "kling") or "kling").strip().lower()
        access_key = AppConfig.get("ai.audio_access_key", "")
        secret_key = AppConfig.get("ai.audio_secret_key", "")
        base_url = AppConfig.get("ai.audio_base_url", "https://api-beijing.klingai.com")
        callback_url = AppConfig.get("ai.audio_callback_url", "")
        poll_interval = AppConfig.get("ai.audio_poll_interval", 1.5)
        return {
            "provider": provider,
            "access_key": access_key,
            "secret_key": secret_key,
            "base_url": base_url,
            "callback_url": callback_url,
            "poll_interval": poll_interval,
        }

    def _get_output_dir(self) -> Path:
        configured_path = AppConfig.get("freesound.download_path", "")
        if configured_path and str(configured_path).strip():
            return Path(str(configured_path))

        from transcriptionist_v3.runtime.runtime_config import get_data_dir

        return get_data_dir() / "downloads" / "generated_audio"

    def _on_generate(self):
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            InfoBar.warning(
                title="提示",
                content="请先输入音效描述",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            return

        provider_config = self._build_provider_config()
        if provider_config.get("provider") != "kling":
            InfoBar.warning(
                title="配置不匹配",
                content="当前仅支持可灵音效服务商，请到设置页检查配置",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            return

        has_aksk = bool(str(provider_config.get("access_key") or "").strip() and str(provider_config.get("secret_key") or "").strip())
        if not has_aksk:
            InfoBar.warning(
                title="未配置鉴权信息",
                content="请先到设置页 -> AI音效服务商配置 填写 Access Key + Secret Key",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4500,
            )
            return

        self.generate_btn.setEnabled(False)
        self.gen_progress.setVisible(True)
        self.gen_progress.setValue(0)
        self.gen_status.setVisible(True)
        self.gen_status.setText("正在提交任务...")
        self.result_label.setText("任务进行中...")
        self.play_btn.setVisible(False)
        self.open_folder_btn.setVisible(False)

        self._gen_worker = KlingTextToAudioWorker(
            prompt=prompt,
            duration=self._get_duration_seconds(),
            preferred_format=self._get_preferred_format(),
            provider_config=provider_config,
            output_dir=self._get_output_dir(),
            timeout_seconds=float(AppConfig.get("ai.audio_task_timeout_seconds", 300.0) or 300.0),
        )
        self._gen_thread = QThread(self)
        self._gen_worker.moveToThread(self._gen_thread)

        self._gen_thread.started.connect(self._gen_worker.run)
        self._gen_worker.progress.connect(self._on_gen_progress)
        self._gen_worker.finished.connect(self._on_gen_finished)
        self._gen_worker.error.connect(self._on_gen_error)

        self._gen_thread.start()

    def _on_gen_progress(self, current: int, total: int, message: str):
        if total > 0:
            try:
                percent = int((float(current) / float(total)) * 100)
            except Exception:
                percent = 0
            self.gen_progress.setValue(max(0, min(100, percent)))
        self.gen_status.setText(message or "处理中...")

    def _on_gen_finished(self, result: dict):
        cleanup_thread(self._gen_thread, self._gen_worker)

        self.generate_btn.setEnabled(True)
        self.gen_progress.setVisible(False)
        self.gen_status.setVisible(False)

        local_path = Path(str(result.get("local_path", "")))
        task_id = str(result.get("task_id", "")).strip()
        self._last_task_id = task_id
        if task_id:
            self.task_id_edit.setText(task_id)

        if not local_path.exists():
            self._on_gen_error("生成完成但未找到输出文件")
            return

        self._last_generated_path = local_path
        self.result_label.setText(f"已生成：{local_path.name}")
        self.play_btn.setVisible(True)
        self.open_folder_btn.setVisible(True)

        InfoBar.success(
            title="生成成功",
            content=f"音效已保存：{local_path.name}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3500,
        )

    def _on_gen_error(self, err_msg: str):
        logger.error(f"Kling generation error: {err_msg}")
        cleanup_thread(self._gen_thread, self._gen_worker)

        self.generate_btn.setEnabled(True)
        self.gen_progress.setVisible(False)
        self.gen_status.setVisible(False)
        self.result_label.setText("生成失败")

        InfoBar.error(
            title="生成失败",
            content=str(err_msg),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5500,
        )

    def _on_play_generated(self):
        if self._last_generated_path and self._last_generated_path.exists():
            self.request_play.emit(str(self._last_generated_path))

    def _on_open_folder(self):
        if not self._last_generated_path or not self._last_generated_path.exists():
            return

        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(self._last_generated_path)])
        elif sys.platform == "darwin":
            subprocess.run(["open", str(self._last_generated_path.parent)])
        else:
            subprocess.run(["xdg-open", str(self._last_generated_path.parent)])
